"""Simulator (SPEC 5.1): distributions, correlations, tail widths, no hindsight."""

import numpy as np
import pytest
from scipy.stats import spearmanr

import builders as b
from core import correlations, grade, sim, slate
from core.sim import SimSettings, U_GRID, _trapezoid

FAST = SimSettings(n_sims=20_000, seed=7)


@pytest.fixture
def sim_slate(home, classic_slate):
    slate.import_files("wk2", classic_slate.values())
    return sim.simulate("wk2", FAST)


def _col(s, name):
    return s.points[:, list(s.players["name"]).index(name)]


# ---------------------------------------------------------------- one player's curve

@pytest.mark.parametrize("values, mean", [([5, 10, 15, 18, 24, 30], 11.5), ([2, 6, 11, 14, 20, 28], 8.0),
                                          ([8, 14, 19, 22, 27, 34], 16.0)])
def test_curve_hits_the_mean_and_never_decreases(values, mean):
    q, ok = sim.quantile_curve(values, mean)
    assert ok and abs(_trapezoid(q, U_GRID) - mean) < 1e-6
    assert np.all(np.diff(q) >= -1e-9)
    assert np.interp(0.5, U_GRID, q) == pytest.approx(values[1])          # the median never moves
    assert q[-1] < values[-1] * 1.5                                        # no absurd best case


def test_curve_flags_a_projection_it_cant_match():
    q, ok = sim.quantile_curve([3, 6, 9, 11, 15, 20], 12.0)
    assert not ok


def test_zero_projection_is_a_flat_zero():
    q, ok = sim.quantile_curve([0, 0, 0, 0, 0, 0], 0.0)
    assert ok and not q.any()


def test_widen():
    assert list(sim.widen([5, 10, 15, 18, 24, 30], 1.2, 1.5)) == [4.0, 10.0, 17.5, 22.0, 31.0, 40.0]


def test_nearest_correlation_is_valid():
    m = np.array([[1, .9, -.9], [.9, 1, .9], [-.9, .9, 1]])
    fixed = sim.nearest_correlation(m)
    assert np.linalg.eigvalsh(fixed).min() > 0 and np.allclose(np.diag(fixed), 1)


# ---------------------------------------------------------------- the slate

def test_simulated_means_match_projections(sim_slate):
    p = sim_slate.players
    live = p[p["dk_points"] >= 1]
    assert np.allclose(live["sim_mean"], live["dk_points"], rtol=0.03)
    assert sim_slate.points.shape == (20_000, 12)


def test_simulated_percentiles_follow_sabersim(sim_slate):
    s = sim_slate.summary().set_index("name")
    for name in ("Dak Prescott", "CeeDee Lamb", "Malik Nabers"):
        assert s.loc[name, "sim 50th"] == pytest.approx(s.loc[name, "dk_50"], rel=0.03)
        assert s.loc[name, "sim 25th"] == pytest.approx(s.loc[name, "dk_25"], rel=0.05)


def test_roles(sim_slate):
    roles = dict(zip(sim_slate.players["name"], sim_slate.players["role"]))
    assert (roles["Dak Prescott"], roles["CeeDee Lamb"], roles["Jake Ferguson"], roles["Cowboys"]) == \
        ("QB1", "WR1", "TE1", "DST")
    assert (roles["Kenneth Walker III"], roles["Kenny Gainwell"]) == ("RB1", "RB1")    # different teams


def test_teammates_move_together_other_games_dont(sim_slate):
    table = correlations.lookup()
    rho = spearmanr(_col(sim_slate, "Dak Prescott"), _col(sim_slate, "CeeDee Lamb")).statistic
    target = 6 / np.pi * np.arcsin(table[("QB1", "WR1", "same")] / 2)                 # the rank correlation
    assert rho == pytest.approx(target, abs=0.03) and rho > 0.3
    other_game = spearmanr(_col(sim_slate, "Dak Prescott"), _col(sim_slate, "Jaxon Smith-Njigba")).statistic
    assert abs(other_game) < 0.03


def test_same_seed_same_simulation(sim_slate):
    again = sim.simulate("wk2", FAST)
    assert np.array_equal(again.points, sim_slate.points)
    other = sim.simulate("wk2", SimSettings(n_sims=20_000, seed=8))
    assert not np.array_equal(other.points, sim_slate.points)


def test_tail_widths_widen_the_range(sim_slate):
    wide = sim.simulate("wk2", SimSettings(n_sims=20_000, seed=7, lower_tail=1.4, upper_tail=1.4))
    for name in ("Dak Prescott", "Malik Nabers"):
        narrow, w = _col(sim_slate, name), _col(wide, name)
        assert np.percentile(w, 95) > np.percentile(narrow, 95)
        assert np.percentile(w, 10) < np.percentile(narrow, 10)
        assert w.mean() == pytest.approx(narrow.mean(), rel=0.03)                      # same average


def test_no_hindsight_actual_scores_are_never_used(home, classic_slate):
    slate.import_files("a", classic_slate.values())
    first = sim.simulate("a", FAST)
    changed = [(*p[:8], 99.0) for p in b.CLASSIC_PLAYERS]                             # every Actual = 99
    b.sabersim_csv(classic_slate["sabersim"], changed)
    slate.import_files("b", classic_slate.values())
    assert np.array_equal(sim.simulate("b", FAST).points, first.points)
    assert "actual" not in first.players.columns and "live_proj" not in first.players.columns
    assert any("No pre-lock SaberSim export" in w for w in first.warnings)


def test_pre_lock_export_is_preferred(home, classic_slate, downloads):
    pre = downloads / "prelock.csv"
    b.sabersim_csv(pre, [(*p[:6], p[6] + 5, p[7], p[8]) for p in b.CLASSIC_PLAYERS], actuals=False)
    slate.import_files("wk2", [*classic_slate.values(), pre])
    s = sim.simulate("wk2", FAST)
    assert s.source_file == "prelock.csv" and not s.warnings
    dak = s.players.set_index("name").loc["Dak Prescott"]
    assert dak["dk_points"] == 19.1 + 5


def test_showdown_captain_points(home, downloads):
    ss = downloads / "sd.csv"
    b.sabersim_csv(ss, b.showdown_players(b.CLASSIC_PLAYERS[:10]))
    slate.import_files("tnf", [ss])
    s = sim.simulate("tnf", SimSettings(n_sims=2_000, seed=1))
    assert len(s.players) == 10                                                        # FLEX rows only
    book = grade.build_book(slate.load_parsed("tnf"))
    lineup = [1506, 1001, 1002, 1003, 1007, 1010]                                      # Nabers captain
    total = sim.lineup_points(s, lineup, book.players)
    nabers = _col(s, "Malik Nabers")
    others = sum(_col(s, n) for n in ("Dak Prescott", "CeeDee Lamb", "Jake Ferguson", "Tyrone Tracy Jr.", "Cowboys"))
    assert np.allclose(total, 1.5 * nabers + others, atol=1e-3)
