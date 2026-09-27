"""Calibration table and tail-width fit (SPEC 5.1)."""

import numpy as np
import pandas as pd
import pytest

import builders as b
from core import calibration, settings, slate


def _players(actuals, p=(5, 10, 15, 18, 24, 30)):
    cols = ["dk_25", "dk_50", "dk_75", "dk_85", "dk_95", "dk_99"]
    return pd.DataFrame([{**dict(zip(cols, p)), "actual": a, "dk_points": 11.5} for a in actuals])


def test_table_by_hand():
    # 20 players, same percentiles. 4 above the 85th (18): 20%. 3 below the 25th (5): 15%.
    actuals = [20, 19, 25, 31] + [3, 4, 2] + [10] * 13
    t = calibration.table(_players(actuals)).set_index("Level")
    assert t.loc["above the 85th percentile", "SaberSim %"] == 20.0
    assert t.loc["above the 85th percentile", "Expected %"] == 15
    assert t.loc["below the 25th percentile", "SaberSim %"] == 15.0
    assert t.loc["above the 99th percentile", "SaberSim %"] == 5.0          # the 31


def test_tail_widths_change_the_widened_column():
    actuals = [20, 19, 25, 31, 3, 4, 2] + [10] * 13
    t = calibration.table(_players(actuals), lower=1.0, upper=1.5).set_index("Level")
    # 85th widened: 10 + 1.5 * (18 - 10) = 22, so only 25 and 31 are above it: 10%.
    assert t.loc["above the 85th percentile", "With tail widths %"] == 10.0
    assert t.loc["above the 85th percentile", "SaberSim %"] == 20.0


def test_fit_recovers_a_wider_spread():
    rng = np.random.default_rng(3)
    # SaberSim's percentiles say sd 4 around 12, but outcomes really have sd 6: 1.5x too narrow.
    from scipy.stats import norm
    p = [12 + 4 * norm.ppf(q) for q in (0.25, 0.5, 0.75, 0.85, 0.95, 0.99)]
    df = _players(12 + 6 * rng.standard_normal(20_000), p)
    lower, upper = calibration.fit(df)
    assert lower == pytest.approx(1.5, abs=0.05) and upper == pytest.approx(1.5, abs=0.05)
    t = calibration.table(df, lower, upper).set_index("Level")
    assert abs(t.loc["above the 85th percentile", "With tail widths %"] - 15) < 1


def test_collect_from_slates(home, classic_slate, downloads):
    slate.import_files("wk1", classic_slate.values())
    df, notes = calibration.collect(["wk1"], min_proj=5)
    assert not notes and set(df["percentiles_from"]) == {"post-game"}
    assert df["dk_points"].min() >= 5 and len(df) == 11                     # Cowboys (6.0) in, Perez (4.0) out
    assert calibration.slates_with_results() == ["wk1"]

    pre = downloads / "prelock.csv"
    b.sabersim_csv(pre, b.CLASSIC_PLAYERS, actuals=False)
    slate.import_files("wk1", [pre])
    df, _ = calibration.collect(["wk1"], min_proj=5)
    assert set(df["percentiles_from"]) == {"pre-lock"}
    assert df.set_index("name").loc["Dak Prescott", "actual"] == 22.34      # Actual still from post-game


def test_slate_without_results_is_noted(home, classic_slate):
    b.sabersim_csv(classic_slate["sabersim"], b.CLASSIC_PLAYERS, actuals=False)
    slate.import_files("wk3", [classic_slate["sabersim"]])
    df, notes = calibration.collect(["wk3"])
    assert df.empty and "no post-game SaberSim export" in notes[0]


def test_settings_round_trip(home):
    assert settings.get("sim.upper_tail") == 1.0
    settings.put("sim.upper_tail", 1.37)
    assert settings.get("sim.upper_tail") == 1.37
