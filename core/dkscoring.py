"""DraftKings points computed from nflverse weekly stats (SPEC 4.3).

Used only to estimate correlations. Grading always uses DraftKings' own numbers.
Golden test G6 checks the QB scoring against SaberSim's Actual.
"""

import numpy as np
import pandas as pd


def _col(df, name):
    return df[name].fillna(0) if name in df.columns else pd.Series(0.0, index=df.index)


def player_points(df):
    """QB and skill positions: DraftKings classic scoring."""
    c = lambda name: _col(df, name)  # noqa: E731
    passing = 0.04 * c("passing_yards") + 4 * c("passing_tds") - c("passing_interceptions") \
        + 3 * (c("passing_yards") >= 300)
    rushing = 0.1 * c("rushing_yards") + 6 * c("rushing_tds") + 3 * (c("rushing_yards") >= 100)
    receiving = c("receptions") + 0.1 * c("receiving_yards") + 6 * c("receiving_tds") \
        + 3 * (c("receiving_yards") >= 100)
    fumbles = -(c("sack_fumbles_lost") + c("rushing_fumbles_lost") + c("receiving_fumbles_lost"))
    two_point = 2 * (c("passing_2pt_conversions") + c("rushing_2pt_conversions") + c("receiving_2pt_conversions"))
    returns = 6 * (c("special_teams_tds") + c("fumble_recovery_tds"))
    return (passing + rushing + receiving + fumbles + two_point + returns).round(2)


def kicker_points(df):
    """Showdown kickers: FG 0-39 yds 3, 40-49 yds 4, 50+ yds 5, extra point 1."""
    c = lambda name: _col(df, name)  # noqa: E731
    return (3 * (c("fg_made_0_19") + c("fg_made_20_29") + c("fg_made_30_39")) + 4 * c("fg_made_40_49")
            + 5 * (c("fg_made_50_59") + c("fg_made_60_")) + c("pat_made")).round(2)


def points_allowed_bonus(points):
    """DraftKings DST points-allowed tiers."""
    p = np.asarray(points)
    return np.select([p == 0, p <= 6, p <= 13, p <= 20, p <= 27, p <= 34], [10, 7, 4, 1, 0, -1], -4)


def dst_points(team_stats, allowed):
    """team_stats: nflverse team-week rows. allowed: points the opponent scored, same order."""
    c = lambda name: _col(team_stats, name)  # noqa: E731
    return (c("def_sacks") + 2 * c("def_interceptions") + 2 * c("fumble_recovery_opp")
            + 6 * (c("def_tds") + c("special_teams_tds")) + 2 * c("def_safeties")
            + 2 * (c("def_punt_blocks") + c("def_fg_blocks") + c("def_pat_blocks"))
            + points_allowed_bonus(allowed)).round(2)
