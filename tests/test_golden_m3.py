"""Golden tests G5 and G7 (SPEC section 9), on your real imported slates.

To run them:
  1. Import the Week 3 TNF ATL@GB showdown as slate 2026-wk03-tnf: post-game SaberSim export,
     your entries file, and the mini-MAX standings zip (contest 195943225).
  2. In slate 2026-wk02-main, put "pre-swap" in the name of the entries file from before the late swap.
     Optionally put "post-swap" in the one from after it; otherwise your entered lineups from the
     standings are used as the after-swap lineups.
  3. DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m3.py -v
"""

import os

import pytest

from core import field, grade, lateswap
from core.names import normalize_name

pytestmark = pytest.mark.skipif(not os.environ.get("DFS_LAB_GOLDEN"),
                                reason="set DFS_LAB_GOLDEN=1 to run on your real imported slates")

TNF, MINI_MAX = "2026-wk03-tnf", "195943225"
WK2 = "2026-wk02-main"


def _set_with(slate_id, label, default=None):
    sets = grade.available_sets(slate_id)
    hits = [k for k, name, _ in sets if label in name.lower() and k != grade.ENTERED_KEY]
    if not hits and default:
        return default
    assert len(hits) == 1, f"Expected one lineup set with '{label}' in its name in {slate_id}; sets are: " \
                           + "; ".join(name for _, name, _ in sets)
    return hits[0]


def test_g5_mini_max_field():
    f = field.load_field(TNF, MINI_MAX)
    assert f.n == 237_812 and round(f.top_score, 1) == 152.1


def test_g5_legal_optimal():
    info, _ = grade.grade(TNF, MINI_MAX, [grade.ENTERED_KEY], save=False)
    p = info.perfect
    assert p is not None, "No perfect lineup: check the SaberSim export's positions (DST) and salaries."
    assert (p["score"], p["salary"]) == (152.10, 48_600), p
    names = [normalize_name(n.replace("CPT ", "")) for n in p["players"]]
    assert "london" in names[0], p["players"]                                   # captain London
    flex = names[1:]
    for part in ("bijan", "watson", "golden", "hooper"):
        assert any(part in n for n in flex), (part, p["players"])
    assert any("robinson" in n and "bijan" not in n for n in flex), p["players"]  # B. Robinson Jr.


def test_g5_best_entered_lineup():
    _, [g] = grade.grade(TNF, MINI_MAX, [grade.ENTERED_KEY], only_contest=True, save=False)
    assert not g.problems, "\n".join(g.problems)
    assert (g.summary["best_score"], g.summary["best_rank"]) == (146.33, 1_170)


def test_g7_week2_late_swap():
    before = _set_with(WK2, "pre-swap")
    after = _set_with(WK2, "post-swap", default=grade.ENTERED_KEY)
    r = lateswap.grade_swap(WK2, before, after)
    s = r.summary
    assert (s["paired"], s["changed"], s["better"], s["worse"]) == (240, 133, 42, 90), lateswap.to_text(r)
    assert round(s["net"], 1) == -1028.3
