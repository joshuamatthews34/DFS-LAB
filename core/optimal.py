"""The perfect lineup: the best legal DraftKings lineup using actual scores (SPEC 4, 6.1).

Solved as an integer program with SciPy's HiGHS solver.
"""

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from . import rosters

CLASSIC_LIMITS = {"QB": (1, 1), "RB": (2, 3), "WR": (3, 4), "TE": (1, 2), "DST": (1, 1)}


def perfect_lineup(pool, fmt):
    """pool: DataFrame with dfs_id, name, pos, team, opp, salary, slot (CPT/FLEX/None), points.

    `points` already includes the captain's 1.5x. Returns a dict or None if no legal lineup exists.
    """
    if fmt == rosters.SHOWDOWN:
        return _showdown(pool.reset_index(drop=True))
    return _classic(pool[pool["pos"].isin(CLASSIC_LIMITS)].reset_index(drop=True))


def _solve(points, rows, lower, upper, n_extra=0):
    n = len(points) + n_extra
    c = -np.concatenate([np.asarray(points, float), np.zeros(n_extra)])
    res = milp(c, constraints=LinearConstraint(np.array(rows, float), lower, upper),
               integrality=np.ones(n), bounds=Bounds(0, 1))
    if not res.success:
        return None
    return np.rint(res.x[:len(points)]).astype(bool)


def _classic(pool):
    n = len(pool)
    game_of = [tuple(sorted((t, o))) for t, o in zip(pool["team"], pool["opp"])]
    games = sorted(set(game_of))
    g = len(games)
    rows, lo, hi = [], [], []

    def add(row, low, high):
        row = [float(v) for v in row]
        rows.append(row + [0.0] * (n + g - len(row)))
        lo.append(low)
        hi.append(high)

    add([1] * n, 9, 9)
    for pos, (a, b) in CLASSIC_LIMITS.items():
        add(pool["pos"] == pos, a, b)
    add(pool["pos"].isin(["RB", "WR", "TE"]), 7, 7)
    add(pool["salary"], 0, rosters.SALARY_CAP)
    # Players from at least two games: game flag y_g can be 1 only if someone from game g is used.
    for j, game in enumerate(games):
        add([x == game for x in game_of] + [-(k == j) for k in range(g)], 0, np.inf)
    add([0] * n + [1] * g, 2, np.inf)
    return _result(pool, _solve(pool["points"], rows, lo, hi, n_extra=g))


def _showdown(pool):
    n = len(pool)
    rows, lo, hi = [], [], []

    def add(row, low, high):
        rows.append([float(v) for v in row])
        lo.append(low)
        hi.append(high)

    add(pool["slot"] == "CPT", 1, 1)
    add(pool["slot"] == "FLEX", 5, 5)
    add(pool["salary"], 0, rosters.SALARY_CAP)
    for team in pool["team"].unique():                     # both teams represented
        add(pool["team"] == team, 1, np.inf)
    for idx in pool.groupby(["name_key", "team"]).indices.values():   # not CPT and FLEX together
        if len(idx) > 1:
            add([i in idx for i in range(n)], 0, 1)
    return _result(pool, _solve(pool["points"], rows, lo, hi))


def _result(pool, pick):
    if pick is None:
        return None
    chosen = pool[pick]
    order = {"CPT": 0, "QB": 1, "RB": 2, "WR": 3, "TE": 4, "FLEX": 5, "K": 6, "DST": 7}
    chosen = chosen.assign(_o=[order.get(s if s == "CPT" else p, 9) for s, p in zip(chosen["slot"], chosen["pos"])])
    chosen = chosen.sort_values(["_o", "points"], ascending=[True, False])
    return {
        "score": round(float(chosen["points"].sum()), 2),
        "salary": int(chosen["salary"].sum()),
        "players": [("CPT " if s == "CPT" else "") + name for s, name in zip(chosen["slot"], chosen["name"])],
        "dfs_ids": [int(i) for i in chosen["dfs_id"]],
    }
