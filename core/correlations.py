"""How players in the same game move together (SPEC 5.1), estimated from nflverse weekly stats.

Each team-week gets roles: QB1 (most pass attempts), RB1-RB2 (most carries + targets),
WR1-WR3 and TE1 (most targets), K (most kicks) and DST. For every pair of roles, on the
same team or facing each other, the rank (Spearman) correlation of DraftKings points is
measured and converted to the Gaussian-copula scale: r = 2 sin(pi * rho / 6).

The result is committed as core/data/correlations.json, so running DFS Lab never downloads
anything. `python -m core.cli correlations --refresh` re-estimates it.
"""

import json
import math
from datetime import date
from itertools import combinations_with_replacement
from pathlib import Path

import numpy as np
import pandas as pd

from . import dkscoring

ROLES = ["QB1", "RB1", "RB2", "WR1", "WR2", "WR3", "TE1", "K", "DST"]
SEASONS = [2021, 2022, 2023, 2024, 2025]
DATA_FILE = Path(__file__).with_name("data") / "correlations.json"
URL = "https://github.com/nflverse/nflverse-data/releases/download/{kind}/{file}"


# ---------------------------------------------------------------- using the estimates

def load(path=DATA_FILE):
    return json.loads(Path(path).read_text())


def lookup(data=None):
    """{(role_a, role_b, 'same'|'opp'): r} with both orders filled in."""
    data = data or load()
    table = {}
    for p in data["pairs"]:
        table[(p["a"], p["b"], p["relation"])] = p["r"]
        table[(p["b"], p["a"], p["relation"])] = p["r"]
    return table


# ---------------------------------------------------------------- estimating them

def download(folder, seasons=SEASONS):
    """Fetch the nflverse files into `folder` (skips ones already there)."""
    import urllib.request

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    wanted = [("stats_player", f"stats_player_week_{y}.csv") for y in seasons]
    wanted += [("stats_team", f"stats_team_week_{y}.csv") for y in seasons]
    wanted += [("schedules", "games.csv")]
    for kind, name in wanted:
        target = folder / name
        if not target.exists() or target.stat().st_size == 0:
            urllib.request.urlretrieve(URL.format(kind=kind, file=name), target)
    return folder


def team_week_roles(players, teams, games):
    """One row per (game, team) with each role's DraftKings points."""
    players = players[players["season_type"] == "REG"].copy()
    players["dk"] = dkscoring.player_points(players)
    players["kdk"] = dkscoring.kicker_points(players)
    rows = []
    for (gid, team), g in players.groupby(["game_id", "team"]):
        row = {"game_id": gid, "team": team}
        qb = g[(g["position"] == "QB") & (g["attempts"].fillna(0) > 0)]
        if len(qb):
            row["QB1"] = qb.loc[qb["attempts"].idxmax(), "dk"]
        _ranked(row, g[g["position"] == "RB"], g["carries"].fillna(0) + g["targets"].fillna(0), ["RB1", "RB2"])
        _ranked(row, g[g["position"] == "WR"], g["targets"].fillna(0), ["WR1", "WR2", "WR3"])
        _ranked(row, g[g["position"] == "TE"], g["targets"].fillna(0), ["TE1"])
        k = g[g["position"] == "K"]
        if len(k):
            kicks = k["fg_att"].fillna(0) + k["pat_att"].fillna(0)
            row["K"] = k.loc[kicks.idxmax(), "kdk"]
        rows.append(row)
    roles = pd.DataFrame(rows)

    teams = teams[teams["season_type"] == "REG"].copy()
    games = games[["game_id", "home_team", "away_team", "home_score", "away_score"]].dropna()
    scores = pd.concat([
        games.rename(columns={"home_team": "team", "away_score": "allowed"})[["game_id", "team", "allowed"]],
        games.rename(columns={"away_team": "team", "home_score": "allowed"})[["game_id", "team", "allowed"]],
    ])
    teams = teams.merge(scores, on=["game_id", "team"], how="inner")
    teams["DST"] = dkscoring.dst_points(teams, teams["allowed"])
    roles = roles.merge(teams[["game_id", "team", "DST"]], on=["game_id", "team"], how="inner")

    opp = roles.rename(columns={r: f"opp_{r}" for r in ROLES} | {"team": "opp_team"})
    both = roles.merge(opp, on="game_id")
    return both[both["team"] != both["opp_team"]].reset_index(drop=True)


def _ranked(row, group, usage, names):
    order = usage.loc[group.index].sort_values(ascending=False, kind="stable").index
    for name, idx in zip(names, order):
        row[name] = group.at[idx, "dk"]


def estimate(folder, seasons=SEASONS):
    folder = Path(folder)
    players = pd.concat([pd.read_csv(folder / f"stats_player_week_{y}.csv", low_memory=False) for y in seasons])
    teams = pd.concat([pd.read_csv(folder / f"stats_team_week_{y}.csv", low_memory=False) for y in seasons])
    games = pd.read_csv(folder / "games.csv", low_memory=False)
    games = games[games["season"].isin(seasons)]
    tw = team_week_roles(players, teams, games)

    pairs = []
    for a, b in combinations_with_replacement(ROLES, 2):
        for relation in ("same", "opp"):
            if relation == "same" and a == b:
                continue
            col_b = b if relation == "same" else f"opp_{b}"
            if a not in tw.columns or col_b not in tw.columns:
                continue
            # Each game appears once per team, so opponent pairs are counted from both sides.
            d = tw[[a, col_b]].dropna()
            if len(d) < 200:
                continue
            if d[a].nunique() < 2 or d[col_b].nunique() < 2:
                continue                                    # no variation, nothing to measure
            rho = d[a].rank().corr(d[col_b].rank())
            pairs.append({"a": a, "b": b, "relation": relation, "r": round(2 * math.sin(math.pi * rho / 6), 3),
                          "rho": round(rho, 3), "n": int(len(d) if relation == "same" else len(d) // 2)})
    return {
        "source": "nflverse weekly player and team stats, regular season",
        "seasons": list(seasons),
        "team_weeks": int(len(tw)),
        "estimated_on": date.today().isoformat(),
        "method": "Spearman rank correlation of DraftKings points by role, converted with r = 2 sin(pi*rho/6)",
        "roles": {
            "QB1": "most pass attempts", "RB1/RB2": "most carries + targets", "WR1-WR3, TE1": "most targets",
            "K": "most kick attempts", "DST": "team defense and special teams",
        },
        "pairs": pairs,
    }


def save(data, path=DATA_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")


def table(data=None):
    """The estimates as a table for the screen, strongest first."""
    data = data or load()
    t = pd.DataFrame(data["pairs"])
    t["Pair"] = t["a"] + " - " + np.where(t["relation"] == "same", "own ", "opp ") + t["b"]
    t = t.reindex(t["r"].abs().sort_values(ascending=False).index)
    return t[["Pair", "r", "rho", "n"]].rename(columns={"r": "Copula r", "rho": "Rank corr", "n": "Team-weeks"}) \
        .reset_index(drop=True)
