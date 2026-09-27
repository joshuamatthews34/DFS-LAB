"""Lineup exports such as DFS Army's (SPEC 3.3): header is just the roster slots."""

import csv
from dataclasses import dataclass, field

from .. import rosters
from ..io_utils import FileProblem, open_text
from .entries import cell_to_id


@dataclass
class LineupsData:
    fmt: str
    lineups: list                      # each a list of DFS IDs in slot order
    names: dict = field(default_factory=dict)   # DFS ID -> name as written in the file
    warnings: list = field(default_factory=list)


def parse(path, fmt):
    n = len(rosters.SLOTS[fmt])
    data = LineupsData(fmt, [])
    partial = 0
    with open_text(path) as f:
        rows = list(csv.reader(f))
    for line_no, row in enumerate(rows[1:], start=2):
        cells = (row + [""] * n)[:n]
        if not any(c.strip() for c in cells):
            continue
        try:
            ids = [cell_to_id(c) for c in cells]
        except ValueError as e:
            raise FileProblem(f"Lineup file row {line_no}: cell '{e}' has no DFS ID in brackets.") from None
        if any(i is None for i in ids):
            partial += 1
            continue
        for cell, pid in zip(cells, ids):
            name = cell.rsplit("(", 1)[0].strip()
            if name:
                data.names.setdefault(pid, name)
        data.lineups.append(ids)
    if partial:
        data.warnings.append(f"{partial} lineup row(s) had empty slots and were skipped.")
    if not data.lineups:
        raise FileProblem("Lineup file has no complete lineups.")
    return data
