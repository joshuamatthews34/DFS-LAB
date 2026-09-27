"""Golden tests G1-G4 (SPEC section 9): numbers Savage already verified by hand.

They run on your real, imported slates, which never go in git. To run them:
  1. Import Week 1 main as slate 2026-wk01-main and Week 2 main as slate 2026-wk02-main
     (post-game SaberSim export, your entries files, the standings zips, and the fill files).
  2. Put these labels in the fill files' names: "Unique Rank 3", "Portfolio+", "UR1", "UR2", "UR4", "UR5".
  3. DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m2.py -v
"""

import os

import pytest

from core import field, grade

pytestmark = pytest.mark.skipif(not os.environ.get("DFS_LAB_GOLDEN"),
                                reason="set DFS_LAB_GOLDEN=1 to run on your real imported slates")

WK1, WK2 = "2026-wk01-main", "2026-wk02-main"
PLAY_ACTION, MILLIONAIRE_35, MILLIONAIRE_25 = "195648006", "193028206", "193028199"


def _grade(slate_id, contest, key, only=False):
    info, [g] = grade.grade(slate_id, contest, [key], only_contest=only, save=False)
    assert not g.problems, "\n".join(g.problems)
    return info, g.summary


def _set_with(slate_id, label):
    """The one lineup set whose file name contains `label`."""
    sets = grade.available_sets(slate_id)
    hits = [k for k, name, _ in sets if label.lower() in name.lower() and k != grade.ENTERED_KEY]
    assert len(hits) == 1, f"Expected one lineup file with '{label}' in its name in {slate_id}; sets are: " \
                           + "; ".join(name for _, name, _ in sets)
    return hits[0]


def _counts(s):
    return s["counts"]["top 1%"], s["counts"]["top 5%"], s["counts"]["top 20%"]


def test_g1_entered_lineups_in_play_action():
    info, s = _grade(WK2, PLAY_ACTION, grade.ENTERED_KEY, only=True)
    assert info.n == 317_082
    assert s["best_rank"] == 2_406 and round(100 * s["best_share"], 2) == 0.76


def test_g1_all_242_lineups_against_play_action():
    _, s = _grade(WK2, PLAY_ACTION, grade.ENTERED_KEY)
    assert s["lineups"] == 242
    assert s["best_score"] == 190.18 and round(100 * s["best_share"], 2) == 0.27
    assert _counts(s) == (4, 14, 74)
    assert round(100 * s["median_share"], 1) == 38.7


@pytest.mark.parametrize("label, expected", [
    ("Unique Rank 3", (5, 21, 83)), ("Portfolio+", (8, 36, 87)), ("UR1", (8, 36, 90)),
    ("UR2", (7, 33, 85)), ("UR4", (4, 21, 77)), ("UR5", (5, 27, 77)),
])
def test_g2_fill_files_against_play_action(label, expected):
    _, s = _grade(WK2, PLAY_ACTION, _set_with(WK2, label))
    assert _counts(s) == expected


def test_g3_week1_millionaire():
    info, s = _grade(WK1, MILLIONAIRE_35, _set_with(WK1, "UR1"))
    assert info.n == 832_342 and info.top_score == 273.98
    assert [round(info.lines[x], 1) for x in (0.01, 0.05, 0.20)] == [209.0, 189.6, 166.3]
    assert (s["counts"]["top 1%"], s["counts"]["top 5%"], s["counts"]["top 20%"]) == (2, 7, 28)


def test_g4_week1_25m_millionaire():
    f = field.load_field(WK1, MILLIONAIRE_25)
    assert f.n == 27_777 and f.top_score == 244.60
    assert [round(f.line(x), 1) for x in (0.01, 0.05)] == [210.6, 192.0]
