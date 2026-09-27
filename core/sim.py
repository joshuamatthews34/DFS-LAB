"""Player outcome simulation (SPEC 5.1).

Each player's outcomes follow a smooth curve through SaberSim's percentiles (dk_25 ... dk_99),
with tails extended so the average equals dk_points. Players in the same game move together
through a Gaussian copula using the role correlations in core/data/correlations.json.
Runs use a fixed seed, so the same settings give the same simulation.

No hindsight (SPEC 7): only pre-lock information is used. Actual and Live Proj are dropped
before anything else happens.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq
from scipy.special import ndtr

from . import correlations, detect, rosters, settings, slate
from .io_utils import FileProblem

U_GRID = np.linspace(0.0, 1.0, 2001)
KNOT_U = np.array([0.0, 0.25, 0.50, 0.75, 0.85, 0.95, 0.99, 1.0])
PCT_COLS = ["dk_25", "dk_50", "dk_75", "dk_85", "dk_95", "dk_99"]
POST_GAME_COLUMNS = ("actual", "live_proj")
FLOOR = {"DST": -4.0, "K": 0.0}
DEFAULT_FLOOR = -3.0
MIN_CORRELATED_PROJ = 1.0          # players projected below this move on their own
ROLE_DEPTH = {"QB": ["QB1"], "RB": ["RB1", "RB2"], "WR": ["WR1", "WR2", "WR3"], "TE": ["TE1"], "K": ["K"],
              "DST": ["DST"]}

_trapezoid = getattr(np, "trapezoid", None) or np.trapz


@dataclass
class SimSettings:
    n_sims: int = 10_000
    seed: int = 2026
    lower_tail: float = 1.0
    upper_tail: float = 1.0

    @classmethod
    def saved(cls, root=None):
        return cls(int(settings.get("sim.n_sims", root)), int(settings.get("sim.seed", root)),
                   float(settings.get("sim.lower_tail", root)), float(settings.get("sim.upper_tail", root)))


@dataclass
class Simulation:
    slate_id: str
    source_file: str
    fmt: str
    players: pd.DataFrame          # one row per player (FLEX rows for showdown), row j = column j of points
    points: np.ndarray             # n_sims x n_players, DraftKings points
    settings: SimSettings
    warnings: list = field(default_factory=list)

    def column_of(self):
        return {int(pid): j for j, pid in enumerate(self.players["dfs_id"])}

    def summary(self):
        p = self.points.astype(np.float64)
        t = self.players[["name", "pos", "team", "role", "salary", "dk_points", "dk_25", "dk_50", "dk_85",
                          "dk_99"]].copy()
        t["sim mean"] = p.mean(axis=0).round(2)
        for q, name in ((25, "sim 25th"), (50, "sim 50th"), (85, "sim 85th"), (99, "sim 99th")):
            t[name] = np.percentile(p, q, axis=0).round(2)
        return t.sort_values("dk_points", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- one player's distribution

def widen(values, lower=1.0, upper=1.0):
    """Stretch percentiles [p25, p50, p75, p85, p95, p99] away from the median."""
    v = np.asarray(values, float)
    med = v[1]
    out = v.copy()
    out[0] = med + lower * (v[0] - med)
    out[2:] = med + upper * (v[2:] - med)
    return out


def quantile_curve(values, mean, floor=DEFAULT_FLOOR):
    """Outcome at each point of U_GRID (0 = worst, 1 = best) and whether the mean was matched.

    values: [p25, p50, p75, p85, p95, p99]. The curve runs smoothly through them and never
    decreases. To make its average equal `mean`, first the worst case (between the floor and
    p25) moves; if that isn't enough, the upper half is stretched or squeezed around the
    median (0.5x to 2x). The median itself never moves.
    """
    v = np.maximum.accumulate(np.asarray(values, float))
    if not np.isfinite(mean):
        mean = v[1]
    if v[-1] - v[0] < 0.05:                                 # no real range (e.g. projected 0)
        return np.full(len(U_GRID), float(mean)), True
    lo_cap = min(floor, v[0])
    med = v[1]

    def curve(low, stretch):
        upper = med + stretch * (v[2:] - med)
        top = upper[-1] + 0.5 * (upper[-1] - upper[-2])
        return PchipInterpolator(KNOT_U, np.concatenate([[low], v[:2], upper, [top]]))(U_GRID)

    def avg(low, stretch):
        return _trapezoid(curve(low, stretch), U_GRID)

    if avg(lo_cap, 1.0) <= mean <= avg(v[0], 1.0):
        return curve(brentq(lambda lo: avg(lo, 1.0) - mean, lo_cap, v[0]), 1.0), True
    low = v[0] if avg(v[0], 1.0) < mean else lo_cap
    s_lo, s_hi = 0.5, 2.0
    if not avg(low, s_lo) <= mean <= avg(low, s_hi):
        return curve(low, s_hi if mean > avg(low, s_hi) else s_lo), False
    return curve(low, brentq(lambda k: avg(low, k) - mean, s_lo, s_hi)), True


# ---------------------------------------------------------------- the slate

def assign_roles(df):
    """QB1, RB1-2, WR1-3, TE1, K, DST within each team by projection; others get no role."""
    df = df.copy()
    df["role"] = None
    ranked = df[df["dk_points"] >= MIN_CORRELATED_PROJ].sort_values("dk_points", ascending=False)
    for (team, pos), g in ranked.groupby(["team", "pos"], sort=False):
        for idx, role in zip(g.index, ROLE_DEPTH.get(pos, [])):
            df.at[idx, "role"] = role
    return df


def correlation_matrix(block, table):
    k = len(block)
    m = np.eye(k)
    roles, teams = list(block["role"]), list(block["team"])
    for i in range(k):
        for j in range(i + 1, k):
            if roles[i] and roles[j]:
                rel = "same" if teams[i] == teams[j] else "opp"
                m[i, j] = m[j, i] = table.get((roles[i], roles[j], rel), 0.0)
    return nearest_correlation(m)


def nearest_correlation(m, eps=1e-4):
    """Make a correlation matrix valid (positive definite) with as little change as possible."""
    w, vecs = np.linalg.eigh(m)
    if w.min() >= eps:
        return m
    fixed = vecs @ np.diag(np.maximum(w, eps)) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    return fixed / np.outer(d, d)


def load_players(slate_id, root=None):
    """Pre-lock player table: the newest pre-game SaberSim export, or the post-game one with a warning."""
    exports = slate.load_parsed(slate_id, root)[detect.SABERSIM]
    if not exports:
        raise FileProblem(f"Slate {slate_id} has no SaberSim export to simulate from.")
    pre = [x for x in exports if not x[2].has_actuals]
    fr, _, data = (pre or exports)[-1]
    warnings = [] if pre else [
        f"No pre-lock SaberSim export in {slate_id}; using {fr.name}. Its projections and percentiles may "
        f"include news from after lock (its Actual scores are not used)."]
    df = data.players.drop(columns=[c for c in POST_GAME_COLUMNS if c in data.players.columns])
    df = df[df["roster_slot"] != "CPT"].reset_index(drop=True)
    return df, data.fmt, fr.name, warnings


def simulate(slate_id, sim_settings=None, root=None, corr=None):
    s = sim_settings or SimSettings.saved(root)
    df, fmt, source, warnings = load_players(slate_id, root)
    df = assign_roles(df)
    table = correlations.lookup(corr)

    curves, unmatched = np.empty((len(df), len(U_GRID)), dtype=np.float64), []
    for j, row in enumerate(df.itertuples()):
        values = widen([getattr(row, c) for c in PCT_COLS], s.lower_tail, s.upper_tail)
        values[0] = max(values[0], FLOOR.get(row.pos, DEFAULT_FLOOR))
        curves[j], ok = quantile_curve(values, row.dk_points, FLOOR.get(row.pos, DEFAULT_FLOOR))
        if not ok:
            unmatched.append(row.name)
    if unmatched:
        warnings.append(f"{len(unmatched)} player(s) have percentiles too far from their projection to match "
                        f"it exactly: " + ", ".join(unmatched[:8]) + ("..." if len(unmatched) > 8 else ""))

    rng = np.random.default_rng(s.seed)
    points = np.empty((s.n_sims, len(df)), dtype=np.float32)
    games = df.apply(lambda r: "@".join(sorted([str(r["team"]), str(r["opp"])])), axis=1)
    for game in sorted(games.unique()):
        idx = np.flatnonzero(games.to_numpy() == game)
        chol = np.linalg.cholesky(correlation_matrix(df.iloc[idx], table))
        z = rng.standard_normal((s.n_sims, len(idx))) @ chol.T
        u = ndtr(z)
        for c, j in enumerate(idx):
            points[:, j] = np.interp(u[:, c], U_GRID, curves[j])
    df["sim_mean"] = points.mean(axis=0)
    return Simulation(slate_id, source, fmt, df, points, s, warnings)


def lineup_points(sim, ids, players):
    """Simulated scores (n_sims) for one lineup of DFS IDs. `players` maps any DFS ID (incl. captain
    rows) to (base_id, multiplier), e.g. grade.PlayerBook.players[["base_id", "mult"]]."""
    col = sim.column_of()
    total = np.zeros(sim.points.shape[0], dtype=np.float64)
    for pid in ids:
        base, mult = players.loc[pid, ["base_id", "mult"]]
        total += mult * sim.points[:, col[int(base)]]
    return total
