"""Milestone 6 check (SPEC section 8): DFS Lab's ATL@GB builds graded against the real mini-MAX field,
next to SaberSim's entered lineups and DFS Army v4 (re-run without the hindsight minimums).

To run it:
  1. Slate 2026-wk03-tnf (from the M3/M5 checks) with: the pre-lock SaberSim export, your DKEntries
     file, the mini-MAX standings zip (contest 195943225), the mini-MAX payout table saved as
     payouts-195943225.csv, and your DFS Army v4 lineup file re-run without the Hooper and Sturdivant
     minimums, with "v4" in its file name.
  2. At least one *other* showdown slate with its standings and SaberSim export, so DFS Lab can
     learn how showdown fields spend salary and stack. (Or set DFS_LAB_M6_FIELD=real to use the
     mini-MAX's own lineups; those builds are marked hindsight.)
  3. DFS_LAB_GOLDEN=1 ./run.sh test tests/test_golden_m6.py -v -s
"""

import os

import pytest

from core import builder, cli, compare, detect, grade, slate

pytestmark = pytest.mark.skipif(not os.environ.get("DFS_LAB_GOLDEN"),
                                reason="set DFS_LAB_GOLDEN=1 to run on your real imported slates")

TNF, MINI_MAX, MINI_MAX_ENTRIES = "2026-wk03-tnf", "195943225", 237_812


def test_m6_builds_graded_against_the_real_mini_max():
    field_source = os.environ.get("DFS_LAB_M6_FIELD", "synthetic")
    parsed = slate.load_parsed(TNF)
    has_pre = any(not d.has_actuals for _, _, d in parsed[detect.SABERSIM])
    has_pay = any(det.contest_id == MINI_MAX for _, det, _ in parsed[detect.PAYOUTS])
    common = dict(contests=[MINI_MAX], roi_contest=MINI_MAX, contest_size=MINI_MAX_ENTRIES,
                  field_source=field_source, allow_post_game_export=not has_pre)
    keys = []
    for fill in ["projection", "portfolio"] + (["roi"] if has_pay else []):
        r = builder.build(TNF, builder.BuildSettings(name=f"m6-{fill}", fill=fill, **common))
        print(f"\nDFS Lab {builder.FILL_METHODS[fill]}: {r.checks['lineups']} lineups")
        print(cli.simulated_text(r.sim))
        assert r.checks["illegal"] == [] and r.checks["duplicates"] == 0
        assert r.checks["lineups"] == r.checks["target"]
        keys.append(f"build:m6-{fill}")

    v4 = [k for k, name, _ in grade.available_sets(TNF) if "v4" in name.lower() and not k.startswith("build:")]
    c = compare.compare(TNF, MINI_MAX, [grade.ENTERED_KEY] + keys + v4[:1], only_contest=True,
                        include_hindsight=field_source == "real")
    print()
    print(compare.to_text(c))
    if not has_pre:
        print("\n! No pre-lock SaberSim export, so the DFS Lab builds are refills.")
    if not has_pay:
        print("\n! No payouts-195943225.csv, so the simulated-ROI build (method 1) was skipped.")
    if not v4:
        print("\n! No lineup file with 'v4' in its name, so DFS Army v4 isn't in the comparison.")
    problems = [p for g in c.grades for p in g.problems]
    assert not problems, "\n".join(problems)
