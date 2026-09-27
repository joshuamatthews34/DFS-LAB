"""DraftKings entries file (SPEC 3.2): your entries on the left, DK's player pool on the right."""

import csv
import re
from dataclasses import dataclass, field

import pandas as pd

from .. import rosters
from ..io_utils import FileProblem, clean_header, open_text, parse_money_cents

_ID_IN_PARENS = re.compile(r"\((\d+)\)\s*$")


def cell_to_id(cell):
    """'44191176' or 'Matthew Stafford (44191176)' -> 44191176; blank -> None."""
    s = str(cell).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    m = _ID_IN_PARENS.search(s)
    if m:
        return int(m.group(1))
    raise ValueError(s)


@dataclass
class Entry:
    entry_id: str
    contest_id: str
    contest_name: str
    fee_cents: int
    player_ids: list


@dataclass
class EntriesData:
    fmt: str
    entries: list
    reservations: int = 0
    pool: pd.DataFrame = None
    warnings: list = field(default_factory=list)


def parse(path, fmt):
    with open_text(path) as f:
        rows = list(csv.reader(f))
    if not rows:
        raise FileProblem("Entries file is empty.")
    n = len(rosters.SLOTS[fmt])
    data = EntriesData(fmt, [])
    incomplete, seen = [], set()

    for line_no, row in enumerate(rows[1:], start=2):
        row = row + [""] * (4 + n - len(row))
        entry_id = row[0].strip()
        if not entry_id:
            continue  # instruction or player-pool rows
        if not entry_id.isdigit():
            raise FileProblem(f"Entries file row {line_no}: Entry ID '{entry_id}' isn't a number.")
        try:
            ids = [cell_to_id(c) for c in row[4:4 + n]]
        except ValueError as e:
            raise FileProblem(f"Entries file row {line_no}: lineup cell '{e}' has no DFS ID.") from None
        if all(i is None for i in ids):
            data.reservations += 1
            continue
        if any(i is None for i in ids):
            incomplete.append(entry_id)
            continue
        if entry_id in seen:
            data.warnings.append(f"Entry ID {entry_id} appears more than once in this file.")
            continue
        seen.add(entry_id)
        try:
            fee = parse_money_cents(row[3])
        except ValueError:
            raise FileProblem(f"Entries file row {line_no}: entry fee '{row[3]}' isn't a dollar amount.") from None
        data.entries.append(Entry(entry_id, row[2].strip(), row[1].strip(), fee, ids))

    if incomplete:
        data.warnings.append(f"{len(incomplete)} entr{'y has' if len(incomplete) == 1 else 'ies have'} a partly "
                             f"filled lineup and were skipped: {', '.join(incomplete[:5])}.")
    data.pool = _player_pool(rows)
    return data


POOL_HEADER = ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary", "Game Info", "TeamAbbrev"]


def _player_pool(rows):
    """The player list DK prints to the right of the entries (ID, roster position, salary, team)."""
    for i, row in enumerate(rows):
        cells = clean_header(row)
        if "Name + ID" not in cells:
            continue
        start = cells.index("Position")
        if cells[start:start + len(POOL_HEADER)] != POOL_HEADER:
            return None
        pool = []
        for r in rows[i + 1:]:
            r = r[start:start + len(POOL_HEADER)]
            if len(r) < len(POOL_HEADER) or not r[3].strip():
                continue
            pool.append({
                "dfs_id": int(r[3]), "name": r[2].strip(), "pos": r[0].strip(),
                "roster_position": r[4].strip(), "salary": int(float(r[5])),
                "game_info": r[6].strip(), "team": r[7].strip(),
            })
        return pd.DataFrame(pool) if pool else None
    return None
