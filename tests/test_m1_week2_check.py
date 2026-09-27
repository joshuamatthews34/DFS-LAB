"""The Milestone 1 check on Savage's real Week 2 main-slate files (SPEC section 8).

Real contest files never go in git, so this runs only when you point it at them:

  DFS_LAB_WEEK2_DIR=~/Downloads/week2 ./run.sh test tests/test_m1_week2_check.py
"""

import os
from pathlib import Path

import pytest

from core import slate

WEEK2 = os.environ.get("DFS_LAB_WEEK2_DIR")


@pytest.mark.skipif(not WEEK2, reason="set DFS_LAB_WEEK2_DIR to a folder holding the Week 2 main-slate files")
def test_week2_main_slate(home):
    files = [p for p in Path(WEEK2).expanduser().iterdir() if p.suffix.lower() in (".csv", ".zip", ".json")]
    report = slate.import_files("2026-wk02-main", files)
    print(report.to_text())
    assert report.fpts_checked, report.fpts_note
    assert (report.entries, report.standings_files, len(report.fpts_mismatches)) == (242, 3, 0)
