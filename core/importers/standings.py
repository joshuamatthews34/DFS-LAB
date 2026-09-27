"""DraftKings contest standings (SPEC 3.4).

Left block: one row per entry with the lineup as a single string.
Right block: one row per drafted player with actual ownership (%Drafted) and FPTS.
Files can be huge (832,342 entries / 167 MB), so only the needed columns are read, in chunks.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from .. import rosters
from ..io_utils import FileProblem, clean_header, open_text
from ..names import normalize_name

WANTED = {"Rank", "EntryId", "EntryName", "Points", "Lineup", "Player", "Roster Position", "%Drafted", "FPTS"}
CHUNK_ROWS = 200_000

_TAG_SPLIT = re.compile(r"(?:^|(?<=\s))(" + "|".join(rosters.LINEUP_TAGS) + r") ")


def parse_lineup(text):
    """'QB Dak Prescott RB ... DST Panthers ' -> [('QB', 'Dak Prescott'), ...]; None if empty or odd."""
    if not isinstance(text, str) or not text.strip():
        return None
    parts = _TAG_SPLIT.split(text.strip() + " ")
    if parts[0].strip():
        return None
    pairs = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts), 2)]
    if not pairs or any(not name for _, name in pairs):
        return None
    return pairs


@dataclass
class StandingsData:
    contest_id: str
    fmt: str
    entries: int                 # entries with a readable lineup
    skipped: int                 # empty or odd lineups
    top_score: float
    players: pd.DataFrame        # player, name_key, roster_position, pct_drafted, fpts
    warnings: list = field(default_factory=list)


def parse(path, member, contest_id):
    fmt_counts, rows_with_rank, unparsed = Counter(), 0, 0
    top, players = None, []

    with open_text(path, member) as f:
        reader = pd.read_csv(f, dtype=str, keep_default_na=False, chunksize=CHUNK_ROWS,
                             usecols=lambda c: clean_header([c])[0] in WANTED)
        for chunk in reader:
            chunk.columns = clean_header(chunk.columns)
            missing = WANTED - set(chunk.columns)
            if missing:
                raise FileProblem("Standings file is missing column(s): " + ", ".join(sorted(missing)) + ".")
            left = chunk[chunk["Rank"].str.strip() != ""]
            rows_with_rank += len(left)
            for lineup in left["Lineup"]:
                pairs = parse_lineup(lineup)
                fmt = rosters.format_for_tags([t for t, _ in pairs]) if pairs else None
                if fmt:
                    fmt_counts[fmt] += 1
                else:
                    unparsed += 1
            pts = pd.to_numeric(left["Points"], errors="coerce").max()
            if pd.notna(pts):
                top = pts if top is None else max(top, pts)
            right = chunk[chunk["Player"].str.strip() != ""]
            players.append(right[["Player", "Roster Position", "%Drafted", "FPTS"]])

    if not fmt_counts:
        raise FileProblem("Standings file has no readable lineups.")
    fmt, entries = fmt_counts.most_common(1)[0]
    skipped = rows_with_rank - entries

    players = pd.concat(players, ignore_index=True)
    players.columns = ["player", "roster_position", "pct_drafted", "fpts"]
    players["player"] = players["player"].str.strip()
    players["roster_position"] = players["roster_position"].str.strip()
    players["pct_drafted"] = _numbers(players["pct_drafted"].str.replace("%", "", regex=False), "%Drafted")
    players["fpts"] = _numbers(players["fpts"], "FPTS")
    players["name_key"] = players["player"].map(normalize_name)

    data = StandingsData(contest_id, fmt, entries, skipped, float(top) if top is not None else None, players)
    if skipped:
        data.warnings.append(f"{skipped:,} field entr{'y' if skipped == 1 else 'ies'} had an empty or unreadable "
                             f"lineup and {'was' if skipped == 1 else 'were'} skipped.")
    return data


def _numbers(series, column):
    values = pd.to_numeric(series.str.strip(), errors="coerce")
    bad = values.isna() & (series.str.strip() != "")
    if bad.any():
        raise FileProblem(f"Standings column '{column}' has values that aren't numbers, e.g. '{series[bad].iloc[0]}'.")
    return values
