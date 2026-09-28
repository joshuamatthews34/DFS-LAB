"""Milestone 5 check (SPEC section 8): build on ATL@GB; every lineup legal; a clean DraftKings file.

To run it:
  1. The Week 3 TNF ATL@GB showdown imported as slate 2026-wk03-tnf, with its DraftKings entries
     file and the pre-lock SaberSim export (the post-game one works for this check too).
  2. DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m5.py -v -s
  3. Then upload the file it prints in DraftKings' entry editor yourself. No errors = pass.
"""

import csv
import os

import pytest

from core import builder, detect, slate

pytestmark = pytest.mark.skipif(not os.environ.get("DFS_LAB_GOLDEN"),
                                reason="set DFS_LAB_GOLDEN=1 to run on your real imported slates")

TNF = "2026-wk03-tnf"


def test_m5_atl_gb_build_is_legal_and_uploadable():
    r = builder.build(TNF, builder.BuildSettings(name="m5-check", allow_post_game_export=True))
    print(f"\nUpload this file in DraftKings' entry editor: {r.csv_path}")
    assert r.checks["illegal"] == [] and r.checks["duplicates"] == 0
    assert r.checks["lineups"] == r.checks["target"]

    # Cross-check against DraftKings' own player pool from the entries file, not DFS Lab's tables.
    ent = slate.load_parsed(TNF)[detect.DK_ENTRIES][-1][2]
    assert ent.pool is not None, "The entries file has no DraftKings player pool on the right."
    dk = ent.pool.set_index("dfs_id")
    mine = {e.entry_id: e for e in ent.all_entries}
    rows = list(csv.reader(open(r.csv_path)))
    assert rows[0] == ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", "CPT", "FLEX", "FLEX", "FLEX",
                       "FLEX", "FLEX"]
    assert len(rows) - 1 == r.checks["lineups"]
    for row in rows[1:]:
        assert row[0] in mine and row[2] == mine[row[0]].contest_id
        ids = [int(x) for x in row[4:]]
        assert all(i in dk.index for i in ids), f"entry {row[0]}: an ID isn't in DraftKings' pool"
        assert dk.at[ids[0], "roster_position"] == "CPT", f"entry {row[0]}: first player isn't a CPT ID"
        assert all(dk.at[i, "roster_position"] == "FLEX" for i in ids[1:]), f"entry {row[0]}: a FLEX ID is wrong"
        assert dk.loc[ids, "salary"].sum() <= 50_000, f"entry {row[0]}: over the cap"
        assert dk.loc[ids, "team"].nunique() == 2, f"entry {row[0]}: needs both teams"
        names = list(dk.loc[ids, "name"])
        assert len(set(names)) == 6, f"entry {row[0]}: the same player twice"
