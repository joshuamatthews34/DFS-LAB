"""DraftKings scoring from nflverse stats (SPEC 4.3) and the correlation estimates (SPEC 5.1)."""

import numpy as np
import pandas as pd
import pytest

from core import correlations, dkscoring


# ---------------------------------------------------------------- scoring

def _row(**stats):
    return pd.DataFrame([stats])


def test_qb_line():
    # 312 pass yds (12.48 + 3 bonus), 2 pass TD (8), 1 INT (-1), 21 rush yds (2.1), 1 fumble lost (-1), 1 2pt (2)
    df = _row(passing_yards=312, passing_tds=2, passing_interceptions=1, rushing_yards=21,
              rushing_fumbles_lost=1, passing_2pt_conversions=1)
    assert dkscoring.player_points(df)[0] == 25.58


def test_receiver_line_with_bonus_and_return_td():
    # 7 rec (7), 104 yds (10.4 + 3 bonus), 1 rec TD (6), 1 kick return TD (6)
    df = _row(receptions=7, receiving_yards=104, receiving_tds=1, special_teams_tds=1)
    assert dkscoring.player_points(df)[0] == 32.4


def test_bonus_thresholds_are_inclusive():
    assert dkscoring.player_points(_row(rushing_yards=100))[0] == 13.0
    assert dkscoring.player_points(_row(rushing_yards=99))[0] == 9.9
    assert dkscoring.player_points(_row(passing_yards=300))[0] == 15.0


def test_kicker():
    # FGs of 25, 44 and 52 yds (3 + 4 + 5) and 3 extra points
    df = _row(fg_made_20_29=1, fg_made_40_49=1, fg_made_50_59=1, pat_made=3)
    assert dkscoring.kicker_points(df)[0] == 15


def test_dst_including_fumble_return_and_points_allowed():
    # 3 sacks, 1 INT, 1 fumble recovery, 1 defensive TD, 1 safety, 1 blocked punt, 13 points allowed (+4)
    df = _row(def_sacks=3, def_interceptions=1, fumble_recovery_opp=1, def_tds=1, def_safeties=1, def_punt_blocks=1)
    assert dkscoring.dst_points(df, [13])[0] == 3 + 2 + 2 + 6 + 2 + 2 + 4


@pytest.mark.parametrize("allowed, bonus", [(0, 10), (6, 7), (7, 4), (20, 1), (27, 0), (34, -1), (35, -4)])
def test_points_allowed_tiers(allowed, bonus):
    assert dkscoring.points_allowed_bonus([allowed])[0] == bonus


# ---------------------------------------------------------------- estimating correlations

def _synthetic_seasons(folder, games=300, seed=0):
    """Fake nflverse files where WR1 lives off his QB's passing and RB1 doesn't."""
    rng = np.random.default_rng(seed)
    players, teams, sched = [], [], []
    for g in range(games):
        gid = f"2024_{g:03d}"
        home_score, away_score = rng.integers(3, 40, 2)
        sched.append({"game_id": gid, "season": 2024, "home_team": "H", "away_team": "A",
                      "home_score": home_score, "away_score": away_score})
        for team, opp in (("H", "A"), ("A", "H")):
            yds = max(80, rng.normal(250, 70))
            base = {"season": 2024, "week": 1, "season_type": "REG", "game_id": gid, "team": team,
                    "opponent_team": opp}
            players += [
                {**base, "position": "QB", "attempts": 35, "passing_yards": yds},
                {**base, "position": "QB", "attempts": 2, "passing_yards": 10},
                {**base, "position": "WR", "targets": 10, "receptions": 6,
                 "receiving_yards": 0.4 * yds + rng.normal(0, 10)},
                {**base, "position": "WR", "targets": 6, "receptions": 4, "receiving_yards": rng.normal(50, 20)},
                {**base, "position": "RB", "carries": 18, "targets": 3, "rushing_yards": rng.normal(80, 30)},
                {**base, "position": "TE", "targets": 5, "receptions": 3, "receiving_yards": rng.normal(35, 15)},
                {**base, "position": "K", "fg_att": 2, "pat_att": 2, "fg_made_30_39": 1, "pat_made": 2},
            ]
            teams.append({**base, "def_sacks": rng.integers(0, 5)})
    pd.DataFrame(players).to_csv(folder / "stats_player_week_2024.csv", index=False)
    pd.DataFrame(teams).to_csv(folder / "stats_team_week_2024.csv", index=False)
    pd.DataFrame(sched).to_csv(folder / "games.csv", index=False)


def test_estimate_on_known_structure(tmp_path):
    _synthetic_seasons(tmp_path)
    data = correlations.estimate(tmp_path, seasons=[2024])
    t = correlations.lookup(data)
    assert t[("QB1", "WR1", "same")] > 0.8          # WR1's yards are 40% of his QB's
    assert abs(t[("QB1", "WR2", "same")]) < 0.15    # WR2 is independent here
    assert abs(t[("QB1", "RB1", "same")]) < 0.15
    assert data["team_weeks"] == 600


def test_roles_follow_usage(tmp_path):
    _synthetic_seasons(tmp_path, games=3)
    players = pd.read_csv(tmp_path / "stats_player_week_2024.csv")
    tw = correlations.team_week_roles(players, pd.read_csv(tmp_path / "stats_team_week_2024.csv"),
                                      pd.read_csv(tmp_path / "games.csv"))
    starter = players[(players["position"] == "QB") & (players["attempts"] == 35)].iloc[0]
    row = tw[(tw["game_id"] == starter["game_id"]) & (tw["team"] == starter["team"])].iloc[0]
    assert row["QB1"] == pytest.approx(0.04 * starter["passing_yards"], abs=0.01)   # the 35-attempt QB


def test_committed_estimates():
    data = correlations.load()
    assert data["seasons"] == [2021, 2022, 2023, 2024, 2025] and data["team_weeks"] > 2500
    t = correlations.lookup(data)
    assert t[("QB1", "WR1", "same")] > 0.35                   # the classic stack
    assert t[("QB1", "TE1", "same")] > 0.2
    assert t[("QB1", "RB1", "same")] > 0
    assert t[("QB1", "WR1", "opp")] > 0                       # bring-backs
    assert t[("RB1", "DST", "same")] > 0
    assert t[("QB1", "DST", "same")] < 0                      # QB and own DST: slightly negative
    assert t[("QB1", "DST", "opp")] < -0.3                    # QB against the defense he faces
    assert correlations.table(data).iloc[0]["Pair"] == "QB1 - own WR1"
