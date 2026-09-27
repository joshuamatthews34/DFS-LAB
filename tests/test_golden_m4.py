"""Milestone 4 check and golden test G6 (SPEC sections 4.3, 8, 9), on your real imported slates.

To run them (needs the internet for G6's nflverse download):
  1. Weeks 1 and 2 main slates imported as 2026-wk01-main and 2026-wk02-main, each with its
     post-game SaberSim export (a pre-lock export too if you have it).
  2. DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m4.py -v -s
"""

import os

import pandas as pd
import pytest

from core import calibration, correlations, detect, dkscoring, slate
from core.names import normalize_name

pytestmark = pytest.mark.skipif(not os.environ.get("DFS_LAB_GOLDEN"),
                                reason="set DFS_LAB_GOLDEN=1 to run on your real imported slates")

WEEKS = {"2026-wk01-main": 1, "2026-wk02-main": 2}


def test_m4_calibration_reproduces_the_85th_percentile_finding():
    df, notes = calibration.collect(list(WEEKS))
    assert not notes, notes
    t = calibration.table(df).set_index("Level")
    print(f"\n{len(df):,} players projected {calibration.DEFAULT_MIN_PROJ}+ points")
    print(t.to_string())
    above_85 = t.loc["above the 85th percentile", "SaberSim %"]
    assert abs(above_85 - 20.8) <= 2, f"{above_85}% above the 85th percentile; SPEC found 20.8% (within 2 points)"


def _qb_check(slate_id, week):
    folder = slate.project_root() / "cache" / "nflverse"
    correlations.download(folder, seasons=[2026])
    stats = pd.read_csv(folder / "stats_player_week_2026.csv", low_memory=False)
    stats = stats[(stats["week"] == week) & (stats["position"] == "QB") & (stats["season_type"] == "REG")].copy()
    stats["computed"] = dkscoring.player_points(stats)
    stats["name_key"] = stats["player_display_name"].map(normalize_name)
    computed = stats.drop_duplicates("name_key").set_index("name_key")["computed"]

    post = [d for _, _, d in slate.load_parsed(slate_id)[detect.SABERSIM] if d.has_actuals][-1]
    qbs = post.players[(post.players["pos"] == "QB") & (post.players["roster_slot"] != "CPT")]
    qbs = qbs[qbs["name_key"].isin(computed.index)]
    qbs = qbs.assign(computed=qbs["name_key"].map(computed))
    bad = qbs[(qbs["computed"] - qbs["actual"]).abs() > 0.01]
    return qbs, bad


@pytest.mark.parametrize("slate_id, expected_qbs", [("2026-wk01-main", 27), ("2026-wk02-main", 32)])
def test_g6_qb_scoring_matches_sabersim(slate_id, expected_qbs):
    qbs, bad = _qb_check(slate_id, WEEKS[slate_id])
    print(f"\n{slate_id}: {len(qbs)} QBs compared")
    assert bad.empty, "\n" + bad[["name", "team", "actual", "computed"]].to_string()
    assert len(qbs) == expected_qbs, (f"{len(qbs)} QBs were compared (QBs in the SaberSim export who have "
                                      f"nflverse stats that week); SPEC's check had {expected_qbs}")
