"""Head-to-head comparison and season view (SPEC 6.5, section 7).

Builds on the graded contest from test_grade.py:
  DK   = DKEntries.csv: entry 1 (the usual lineup) and entry 2 (with Harrison + McBride)
  Army = army.csv: L1 (same as entry 1), L2 (Perez for Smith-Njigba), L3 (Harrison for Nabers)
"""

import pytest

import builders as b
from core import builds, compare, slate
from core.io_utils import FileProblem
from test_grade import graded_slate  # noqa: F401  (fixture)

DK, ARMY = "entries:DKEntries.csv", "lineups:army.csv"
L1 = b.CLASSIC_LINEUP
L2 = [1001, 1004, 1007, 1002, 1012, 1006, 1003, 1011, 1010]
L3 = [1001, 1004, 1007, 1002, 1005, 1008, 1003, 1011, 1010]


@pytest.fixture
def two_builds(graded_slate, downloads):  # noqa: F811
    army = downloads / "army.csv"
    b.lineups_csv(army, "classic", [L1, L2, L3], b.NAMES)
    slate.import_files("wk2", [army])
    builds.save_meta("wk2", {DK: {"name": "SaberSim UR3 (entered)", "method": "SaberSim UR3"},
                             ARMY: {"name": "DFS Army v4", "method": "DFS Army v4"}})


def test_side_by_side_summary(two_builds):
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    assert c.names == ["SaberSim UR3 (entered)", "DFS Army v4"]
    s = c.summary.set_index("Build")
    assert s.loc["SaberSim UR3 (entered)", "Lineups"] == 2 and s.loc["DFS Army v4", "Lineups"] == 3
    assert s.loc["DFS Army v4", "Best"] == 140.34 and s.loc["DFS Army v4", "Method"] == "DFS Army v4"
    # Projection average of My Proj (L1 122.1, L2 110.1, L3 117.1); no pre-lock export here, so it's flagged.
    assert s.loc["DFS Army v4", "Avg proj"] == round((122.1 + 110.1 + 117.1) / 3, 2)
    assert any("post-game SaberSim export" in w for w in c.warnings)


def test_exposure_differences_and_leans(two_builds):
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    e = c.exposure.set_index("Player")
    assert c.exposure.iloc[0]["Player"] == "Trey McBride"             # biggest spread: 50% vs 0%
    assert (e.loc["Trey McBride", "SaberSim UR3 (entered)"], e.loc["Trey McBride", "DFS Army v4"]) == (50.0, 0.0)
    assert e.loc["José Pérez", "Spread"] == 33.3
    assert e.loc["Tyrone Tracy Jr.", "Spread"] == 0.0
    dk = c.leans["SaberSim UR3 (entered)"]
    assert list(dk["Player"][:3]) == ["Trey McBride", "Jaxon Smith-Njigba", "Marvin Harrison Jr."]
    assert dk.iloc[0]["Final"] == 12.4
    # Army has Ferguson in all 3 lineups vs 1 of 2 for DK.
    assert list(c.leans["DFS Army v4"]["Player"]) == ["Jake Ferguson", "José Pérez", "Malik Nabers"]


def test_shared_lineups(two_builds):
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    assert c.shared.loc["SaberSim UR3 (entered)", "DFS Army v4"] == 1       # L1 is entry 1
    assert c.shared.loc["DFS Army v4", "DFS Army v4"] == 3


def test_statistics_always_carry_the_warning(two_builds):
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    row = c.stats.iloc[0]
    assert (row["Top 5% A"], row["Top 5% B"]) == ("0/2", "0/3")
    assert 0 <= row["Mann-Whitney p (scores)"] <= 1 and row["Fisher p (top 5%)"] == 1.0
    assert compare.STATS_WARNING in compare.to_text(c)
    assert compare.STATS_WARNING == ("All lineups on one slate share one set of game results; "
                                     "these p-values are too generous.")


def test_two_to_six_builds(two_builds):
    with pytest.raises(FileProblem, match="2 to 6"):
        compare.compare("wk2", "195648006", [DK])


def test_hindsight_builds_are_left_out(two_builds):
    meta = builds.load_meta("wk2")
    meta[ARMY]["hindsight"] = True
    builds.save_meta("wk2", meta)
    with pytest.raises(FileProblem, match="2 to 6"):
        compare.compare("wk2", "195648006", [DK, ARMY])
    c = compare.compare("wk2", "195648006", [DK, ARMY], include_hindsight=True)
    assert "DFS Army v4 [hindsight]" in c.names
    assert any("Hindsight builds are included" in w for w in c.warnings)
    assert builds.season_rows()["method"].tolist() == ["SaberSim UR3"]       # hindsight never recorded


def test_refill_vs_original_warns(two_builds):
    meta = builds.load_meta("wk2")
    meta[ARMY]["refill"] = True
    builds.save_meta("wk2", meta)
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    assert any("not with the original entries" in w for w in c.warnings)


def test_prelock_projections_are_used_when_imported(two_builds, downloads):
    pre = downloads / "prelock.csv"
    players = [(*p[:7], p[7] + 1.0, p[8]) for p in b.CLASSIC_PLAYERS]     # My Proj 1 point higher each
    b.sabersim_csv(pre, players, actuals=False)
    slate.import_files("wk2", [pre])
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    assert not any("post-game SaberSim export" in w for w in c.warnings)
    assert c.summary.set_index("Build").loc["DFS Army v4", "Avg proj"] == round((122.1 + 110.1 + 117.1) / 3 + 9, 2)


def test_season_view(two_builds):
    compare.compare("wk2", "195648006", [DK, ARMY])
    compare.compare("wk2", "195648006", [DK, ARMY])                       # re-running replaces, not doubles
    table, n = builds.season_table()
    t = table.set_index("Method")
    assert n == 1 and list(t.index) == ["DFS Army v4", "SaberSim UR3"]
    assert (t.loc["DFS Army v4", "Lineups"], t.loc["DFS Army v4", "Top 1 %"]) == (3, 0.0)
    # DK: 2 lineups, both cashed (ranks 3 and 6), won $30 on $6 of fees.
    assert (t.loc["SaberSim UR3", "Cash rate %"], t.loc["SaberSim UR3", "ROI %"]) == (100.0, 400.0)
    assert t.loc["DFS Army v4", "ROI %"] is not None                       # contest fee known from entries
    assert builds.season_note(n) == ("1 slate in the season record so far. "
                                     "About 10+ slates are needed before switching methods.")


def test_refills_are_a_separate_season_row(two_builds):
    meta = builds.load_meta("wk2")
    meta[ARMY]["refill"] = True
    builds.save_meta("wk2", meta)
    compare.compare("wk2", "195648006", [DK, ARMY])
    table, _ = builds.season_table()
    assert "DFS Army v4 (refill)" in set(table["Method"])


def test_unnamed_builds_are_not_recorded(two_builds):
    builds.save_meta("wk2", {})
    c = compare.compare("wk2", "195648006", [DK, ARMY])
    assert c.recorded == 0 and builds.season_rows().empty
