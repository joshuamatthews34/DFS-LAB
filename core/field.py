"""A contest's field, read from its DraftKings standings file (SPEC 3.4, 6.1).

Scores are compared in whole hundredths of a point so ties are exact.
Percentile = share of the field scoring strictly higher (SPEC 6.1).
"""

import math
import pickle
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import detect, slate
from .importers import standings as standings_imp
from .io_utils import FileProblem, clean_header, open_text, sha256_file
from .names import normalize_name

CACHE_VERSION = 1
LEFT = ["Rank", "EntryId", "Points", "Lineup"]
RIGHT = ["Player", "Roster Position", "%Drafted", "FPTS"]


def to_cents(points):
    """Points -> whole hundredths, rounding halves up (a captain's 1.5x can land on a half-hundredth)."""
    return np.floor(np.asarray(points, dtype=float) * 100 + 0.5 + 1e-6).astype(np.int64)


@dataclass
class Field:
    contest_id: str
    source_file: str
    entries: pd.DataFrame      # rank, entry_id, points, lineup; in rank order
    players: pd.DataFrame      # player, name_key, roster_position, pct_drafted, fpts

    def __post_init__(self):
        self._asc = np.sort(to_cents(self.entries["points"].to_numpy()))

    @property
    def n(self):
        return len(self._asc)

    @property
    def top_score(self):
        return self._asc[-1] / 100 if self.n else None

    def higher(self, points):
        """How many field entries scored strictly more than each of `points`."""
        return self.n - np.searchsorted(self._asc, to_cents(points), side="right")

    def equal(self, points):
        c = to_cents(points)
        return np.searchsorted(self._asc, c, side="right") - np.searchsorted(self._asc, c, side="left")

    def line(self, share):
        """Lowest score that still finishes in the top `share` (e.g. 0.01 for top 1%)."""
        k = math.floor(share * self.n + 1e-9)
        return self._asc[::-1][k] / 100 if k < self.n else None

    def score_at_rank(self, rank):
        return self._asc[::-1][rank - 1] / 100 if 1 <= rank <= self.n else None

    def top_lineups(self, share):
        """Lineup strings of every field entry finishing in the top `share`."""
        pts = self.entries["points"].to_numpy()
        keep = self.higher(pts) <= share * self.n + 1e-9
        return self.entries.loc[keep, "lineup"]

    def fmt(self):
        from . import rosters
        for text in self.entries["lineup"].head(200):
            pairs = standings_imp.parse_lineup(text)
            fmt = rosters.format_for_tags([t for t, _ in pairs]) if pairs else None
            if fmt:
                return fmt
        return None


def find_standings(slate_id, contest_id, root=None):
    for path in reversed(slate.raw_files(slate_id, root)):
        det = detect.detect(path)
        if det.kind == detect.STANDINGS and det.contest_id == str(contest_id):
            return det
    raise FileProblem(f"No standings file for contest {contest_id} in slate {slate_id}.")


def load_field(slate_id, contest_id, root=None):
    det = find_standings(slate_id, contest_id, root)
    digest = sha256_file(det.path)
    cache = slate.slate_dir(slate_id, root) / "results" / "cache" / f"field-{contest_id}-{digest[:16]}.pkl"
    if cache.exists():
        try:
            with cache.open("rb") as f:
                version, entries, players = pickle.load(f)
            if version == CACHE_VERSION:
                return Field(str(contest_id), det.path.name, entries, players)
        except Exception:
            pass
    entries, players = _read(det)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with cache.open("wb") as f:
        pickle.dump((CACHE_VERSION, entries, players), f)
    return Field(str(contest_id), det.path.name, entries, players)


def _read(det):
    left, right = [], []
    with open_text(det.path, det.member) as f:
        reader = pd.read_csv(f, dtype=str, keep_default_na=False, chunksize=200_000,
                             usecols=lambda c: clean_header([c])[0] in LEFT + RIGHT)
        for chunk in reader:
            chunk.columns = clean_header(chunk.columns)
            rows = chunk[chunk["Rank"].str.strip() != ""]
            left.append(rows[LEFT])
            right.append(chunk.loc[chunk["Player"].str.strip() != "", RIGHT])
    entries = pd.concat(left, ignore_index=True)
    entries.columns = ["rank", "entry_id", "points", "lineup"]
    entries["rank"] = pd.to_numeric(entries["rank"], errors="coerce")
    entries["points"] = pd.to_numeric(entries["points"], errors="coerce")
    if entries[["rank", "points"]].isna().any().any():
        raise FileProblem(f"{det.path.name}: some Rank or Points values aren't numbers.")
    entries["rank"] = entries["rank"].astype("int64")
    entries["entry_id"] = entries["entry_id"].str.strip()
    entries = entries.sort_values("rank", kind="stable").reset_index(drop=True)

    players = pd.concat(right, ignore_index=True)
    players.columns = ["player", "roster_position", "pct_drafted", "fpts"]
    players["player"] = players["player"].str.strip()
    players["roster_position"] = players["roster_position"].str.strip()
    players["pct_drafted"] = pd.to_numeric(players["pct_drafted"].str.replace("%", "", regex=False),
                                           errors="coerce")
    players["fpts"] = pd.to_numeric(players["fpts"], errors="coerce")
    players["name_key"] = players["player"].map(normalize_name)
    return entries, players
