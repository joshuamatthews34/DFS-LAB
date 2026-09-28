"""DFS Lab's own lineup builder (SPEC 5.2-5.4, section 7).

1. Snapshot: the pre-lock inputs are copied into slates/<slate>/prelock/<build>/ with a hash of
   each file and the time. The build reads only these copies.
2. Candidates: thousands of optimal lineups, each for projections with random noise
   (~25% lognormal) or for one simulated slate. Lineup rules are built into the optimizer.
3. Fill: fill method 2 (SPEC 5.3), top by projection with N unique players between lineups,
   respecting min/max exposures, captain limits and the game coverage floor.
4. Checks: every lineup is checked against DraftKings' rules, and the guardrails (5.4) are reported.
5. Export: a DraftKings entries CSV to upload by hand. DFS Lab never touches DraftKings.

No hindsight (SPEC 7): Actual, Live Proj, FPTS, %Drafted and standings are never read.
"""

import contextlib
import json
import math
import multiprocessing
import os
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csr_matrix, vstack

from . import builds, detect, legal, lateswap, rosters, sim, slate
from .importers import entries as entries_imp
from .importers import sabersim as sabersim_imp
from .importers import warroom as warroom_imp
from .io_utils import FileProblem, sha256_file

POST_GAME_COLUMNS = ("actual", "live_proj")
WARROOM_RULES = {"OVER": 1.5, "WITH": 1.0, "UNDER": 0.6, "FADE_MAX": 3.0}
CAPTAIN_TIERS = {"core": (15, 25), "favorite's QB": (7, 12), "secondary": (7, 25), "other QB": (0, 5)}
LATE_KICKOFF_HOUR = 16                 # 4:05 / 4:25 ET games count as late
MIN_POOL_PROJ = 0.5
RESERVE_AT = 0.8                       # fill: protect a minimum once it needs 80% of the lineups left
TOP_UP_ROUNDS = 3                      # extra candidate rounds when the fill comes up short


@dataclass
class BuildSettings:
    name: str = "default"
    n_lineups: int = 150               # used when there is no entries file to fill
    contests: list = None              # contest IDs to fill from the entries file (None = all)
    pool_size: int = 5000
    noise: str = "lognormal"           # or "simulations"
    noise_sd: float = 0.25
    seed: int = 2026
    salary_floor: int = None           # None = showdown $48,000, classic none
    min_uniques: int = 2
    max_total_own: float = None        # max total projected ownership per lineup, %
    stack_passcatchers: int = 1        # classic: QB + at least this many of his WR/TE
    bring_back: bool = False           # classic: plus at least one opponent from his game
    qb_captain_passcatcher: bool = True    # showdown: a QB captain needs one of his WR/TE
    one_k_one_dst: bool = True         # showdown
    coverage_floor: bool = True        # classic: games with a big total get enough players
    coverage_total: float = 44.0
    coverage_per_lineup: float = 0.5
    warroom_rules: dict = field(default_factory=lambda: dict(WARROOM_RULES))
    late_haircut: float = 0.0          # 0.4 = cut late-game projected ownership by 40% (off = 0)
    exposures: dict = field(default_factory=dict)      # base DFS ID -> [min %, max %]
    captains: dict = field(default_factory=dict)       # base DFS ID -> [min %, max %]
    captain_tiers: dict = field(default_factory=dict)  # base DFS ID -> tier name
    chalk_own: float = 20.0            # chalk warning: projected ownership at least this...
    chalk_margin: float = 10.0         # ...and your exposure this many points above it
    allow_post_game_export: bool = False
    workers: int = None                # parallel solver processes (None = CPU count - 1)

    def floor(self, fmt):
        if self.salary_floor is not None:
            return self.salary_floor
        return 48_000 if fmt == rosters.SHOWDOWN else 0


@dataclass
class BuildResult:
    slate_id: str
    settings: BuildSettings
    fmt: str
    lineups: list                      # row indices into `pool`, CPT first for showdown
    pool: pd.DataFrame                 # rows the optimizer could use
    players: pd.DataFrame              # one row per player (base), with limits and exposure
    snapshot: dict
    candidates: int
    warnings: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    csv_path: str = None
    template: list = None              # Entry objects filled, in order

    def lineup_ids(self):
        return [[int(self.pool.at[r, "dfs_id"]) for r in lu] for lu in self.lineups]


# ---------------------------------------------------------------- 1. snapshot

def make_snapshot(slate_id, name, allow_post_game=False, root=None):
    """Copy the pre-lock inputs into prelock/<name>/ with hashes and the time."""
    parsed = slate.load_parsed(slate_id, root)
    exports = parsed[detect.SABERSIM]
    pre = [x for x in exports if not x[2].has_actuals]
    warnings = []
    if pre:
        ss = pre[-1]
    elif exports and allow_post_game:
        ss = exports[-1]
        warnings.append(f"Built from the post-game SaberSim export ({ss[0].name}) because the slate has no "
                        f"pre-lock export. Its projections may include news from after lock; treat this build "
                        f"as a refill.")
    elif exports:
        raise FileProblem("This slate only has a post-game SaberSim export. Import the pre-lock export (the one "
                          "exported before the games), or tick 'use the post-game export' to build anyway.")
    else:
        raise FileProblem(f"Slate {slate_id} has no SaberSim export to build from.")
    inputs = [("sabersim", ss[1].path)]
    if parsed[detect.DK_ENTRIES]:
        inputs.append(("dk_entries", parsed[detect.DK_ENTRIES][-1][1].path))
    if parsed[detect.WARROOM]:
        inputs.append(("warroom", parsed[detect.WARROOM][-1][1].path))

    stamp = datetime.now()
    folder = slate.slate_dir(slate_id, root) / "prelock" / f"{name}-{stamp:%Y%m%d-%H%M%S}"
    folder.mkdir(parents=True, exist_ok=False)
    files = []
    for role, src in inputs:
        dest = folder / src.name
        shutil.copy2(src, dest)
        files.append({"role": role, "file": src.name, "sha256": sha256_file(dest), "bytes": dest.stat().st_size})
    manifest = {"slate": slate_id, "build": name, "taken_at": stamp.isoformat(timespec="seconds"),
                "folder": str(folder), "files": files, "warnings": warnings,
                "post_game_export": not pre}
    (folder / "snapshot.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def read_snapshot(manifest):
    """Parse the snapshot's copies. Post-game columns are dropped immediately."""
    folder = Path(manifest["folder"])
    got = {f["role"]: folder / f["file"] for f in manifest["files"]}
    for f in manifest["files"]:
        if sha256_file(folder / f["file"]) != f["sha256"]:
            raise FileProblem(f"Snapshot file {f['file']} changed after it was taken.")
    ss = sabersim_imp.parse(got["sabersim"])
    players = ss.players.drop(columns=[c for c in POST_GAME_COLUMNS if c in ss.players.columns])
    ent = None
    if "dk_entries" in got:
        ent = entries_imp.parse(got["dk_entries"], detect.detect(got["dk_entries"]).fmt)
    tags = warroom_imp.parse(got["warroom"]) if "warroom" in got else None
    return players, ss, ent, tags


# ---------------------------------------------------------------- 2. players and limits

def prepare(players, ss, ent, tags, s):
    """One row per player with projection, ownership, kickoff, War Room tag and exposure limits."""
    fmt = ss.fmt
    warnings = []
    proj_col = "my_proj" if ss.blend_loaded else "ss_proj"
    if not ss.blend_loaded:
        warnings.append("My Proj isn't loaded (it equals SS Proj or is blank), so SaberSim's projection is used.")
    base = players[players["roster_slot"] != "CPT"].copy()
    base["proj"] = base[proj_col].fillna(base["ss_proj"]).fillna(0.0)
    base["own"] = base["my_own"].fillna(0.0)

    kick = {}
    if ent is not None and ent.pool is not None:
        kick = lateswap.kickoffs({detect.DK_ENTRIES: [(None, None, ent)]})
    base["kickoff"] = base["dfs_id"].map(kick)
    base["late"] = base["kickoff"].map(lambda t: bool(t is not None and not pd.isna(t)
                                                      and t.hour >= LATE_KICKOFF_HOUR))
    if s.late_haircut:
        if not kick:
            warnings.append("Late-game ownership haircut is on, but there's no kickoff information (from a "
                            "DraftKings entries file), so it wasn't applied.")
        else:
            base.loc[base["late"], "own"] *= (1 - s.late_haircut)

    tag_of = dict(zip(tags["name_key"], tags["tag"])) if tags is not None else {}
    caps = {k: (lo, hi) for k, lo, hi in zip(tags["name_key"], tags["cap_min"], tags["cap_max"])} if tags is not None else {}
    base["tag"] = base["name_key"].map(tag_of).fillna("")
    if tags is not None:
        unmatched = sorted(set(tags["name_key"]) - set(base["name_key"]))
        if unmatched:
            warnings.append("War Room names that don't match a player (their tags aren't used): "
                            + ", ".join(tags.loc[tags["name_key"].isin(unmatched), "player"]))

    rules = s.warroom_rules
    mins, maxs = [], []
    for row in base.itertuples():
        lo, hi = 0.0, 100.0
        if row.tag == "FADE":
            hi = rules["FADE_MAX"]
        elif row.tag in ("OVER", "WITH", "UNDER"):
            hi = min(100.0, row.own * rules[row.tag])
        cap_lo, cap_hi = caps.get(row.name_key, (None, None))
        if cap_lo is not None and not pd.isna(cap_lo):
            lo = float(cap_lo)
        if cap_hi is not None and not pd.isna(cap_hi):
            hi = float(cap_hi)
        if str(row.dfs_id) in s.exposures or row.dfs_id in s.exposures:
            lo, hi = s.exposures.get(str(row.dfs_id), s.exposures.get(row.dfs_id))
        mins.append(float(lo))
        maxs.append(float(hi))
    base["min_exp"], base["max_exp"] = mins, maxs

    base["cpt_min"], base["cpt_max"] = 0.0, 100.0
    if fmt == rosters.SHOWDOWN:
        for i, row in base.iterrows():
            key = str(row["dfs_id"])
            tier = s.captain_tiers.get(key, s.captain_tiers.get(row["dfs_id"]))
            if tier:
                base.at[i, "cpt_min"], base.at[i, "cpt_max"] = CAPTAIN_TIERS[tier]
            if key in s.captains or row["dfs_id"] in s.captains:
                base.at[i, "cpt_min"], base.at[i, "cpt_max"] = s.captains.get(key, s.captains.get(row["dfs_id"]))
    return base.reset_index(drop=True), fmt, warnings


def pool_rows(base, players, fmt):
    """The rows the optimizer picks from: players (classic), or captain and FLEX rows (showdown)."""
    keep = base[(base["proj"] >= MIN_POOL_PROJ) | (base["min_exp"] > 0) | (base["cpt_min"] > 0)]
    keep = keep[(keep["max_exp"] > 0)]
    cols = ["dfs_id", "name", "name_key", "pos", "team", "opp", "salary", "proj", "own", "late", "saber_total"]
    flex = keep[cols].assign(slot="FLEX" if fmt == rosters.SHOWDOWN else None, base_id=keep["dfs_id"], mult=1.0)
    if fmt != rosters.SHOWDOWN:
        return flex.reset_index(drop=True)
    cpt_rows = players[players["roster_slot"] == "CPT"].set_index(["name_key", "team"])
    rows = []
    for r in keep[keep["cpt_max"] > 0].itertuples():
        if (r.name_key, r.team) not in cpt_rows.index:
            continue
        c = cpt_rows.loc[(r.name_key, r.team)]
        rows.append({"dfs_id": int(c["dfs_id"]), "name": r.name, "name_key": r.name_key, "pos": r.pos,
                     "team": r.team, "opp": r.opp, "salary": int(c["salary"]), "proj": 1.5 * r.proj,
                     "own": float(c["my_own"]) if pd.notna(c["my_own"]) else 0.0, "late": r.late,
                     "saber_total": r.saber_total, "slot": "CPT", "base_id": r.dfs_id, "mult": 1.5})
    return pd.concat([pd.DataFrame(rows), flex], ignore_index=True)


# ---------------------------------------------------------------- 3. candidates

def model(pool, fmt, s):
    """Constraint matrix for one legal lineup. Returns (A, lower, upper, n_extra)."""
    n = len(pool)
    rows, lo, hi = [], [], []
    games, n_extra = [], 0

    def add(coefs, low, high, width=None):
        coefs = [float(c) for c in coefs]
        rows.append(coefs + [0.0] * ((width or n) - len(coefs)))
        lo.append(low)
        hi.append(high)

    team, pos = pool["team"].to_numpy(), pool["pos"].to_numpy()
    if fmt == rosters.SHOWDOWN:
        slot = pool["slot"].to_numpy()
        add(slot == "CPT", 1, 1)
        add(slot == "FLEX", 5, 5)
        add(pool["salary"], s.floor(fmt), rosters.SALARY_CAP)
        for t in sorted(set(team)):
            add(team == t, 1, np.inf)
        for idx in pool.groupby("base_id").indices.values():
            if len(idx) > 1:
                add(np.isin(np.arange(n), idx), 0, 1)
        if s.one_k_one_dst:
            add(pos == "K", 0, 1)
            add(pos == "DST", 0, 1)
        if s.qb_captain_passcatcher:
            for i in np.flatnonzero((slot == "CPT") & (pos == "QB")):
                c = ((slot == "FLEX") & (team == team[i]) & np.isin(pos, ["WR", "TE"])).astype(float)
                c[i] = -1
                add(c, 0, np.inf)
    else:
        game_of = [tuple(sorted((t, o))) for t, o in zip(pool["team"], pool["opp"])]
        games = sorted(set(game_of))
        n_extra = len(games)
        width = n + n_extra
        add([1] * n, 9, 9, width)
        for p, (a, b) in legal.CLASSIC_COUNTS.items():
            add(pos == p, a, b, width)
        add(np.isin(pos, ["RB", "WR", "TE"]), 7, 7, width)
        add(pool["salary"], s.floor(fmt), rosters.SALARY_CAP, width)
        for j, g in enumerate(games):
            add([x == g for x in game_of] + [-(k == j) for k in range(n_extra)], 0, np.inf, width)
        add([0] * n + [1] * n_extra, 2, np.inf, width)
        opp = pool["opp"].to_numpy()
        for i in np.flatnonzero(pos == "QB"):
            if s.stack_passcatchers:
                c = ((team == team[i]) & np.isin(pos, ["WR", "TE"])).astype(float)
                c[i] = -s.stack_passcatchers
                add(c, 0, np.inf, width)
            if s.bring_back:
                c = ((team == opp[i]) & np.isin(pos, ["RB", "WR", "TE"])).astype(float)
                c[i] = -1
                add(c, 0, np.inf, width)
    if s.max_total_own:
        add(pool["own"], 0, s.max_total_own, n + n_extra)
    width = n + n_extra
    rows = [r + [0.0] * (width - len(r)) for r in rows]
    return csr_matrix(np.array(rows)), np.array(lo, float), np.array(hi, float), n_extra


@contextlib.contextmanager
def _workers_skip_the_app():
    """Spawned workers normally re-run the program's main script first. Under Streamlit that's the
    whole app, so hide it: workers only need this module, which they import by name."""
    main = sys.modules.get("__main__")
    saved = {k: getattr(main, k) for k in ("__file__", "__spec__") if main is not None and hasattr(main, k)}
    try:
        for k in saved:
            if k == "__spec__":
                main.__spec__ = None
            else:
                delattr(main, k)
        yield
    finally:
        for k, v in saved.items():
            setattr(main, k, v)


def _solve_chunk(args):
    A, lo, hi, n_extra, objectives = args
    n = objectives.shape[1]
    cons = LinearConstraint(A, lo, hi)
    integrality = np.ones(n + n_extra)
    out = []
    for obj in objectives:
        res = milp(-np.concatenate([obj, np.zeros(n_extra)]), constraints=cons, integrality=integrality,
                   bounds=Bounds(0, 1))
        out.append(tuple(np.flatnonzero(res.x[:n] > 0.5)) if res.success else None)
    return out


AVOID = -1000.0                        # objective for a row left out of a candidate


def objectives(pool, base, fmt, s, count=None, seed=None, blocked=()):
    """One noisy projection vector per candidate.

    Players with a max exposure below 100% are left out of candidates at random in proportion
    (a 20% cap leaves them out of about 80%), so the pool already fits the caps. Rows in
    `blocked` are left out of every candidate.
    """
    count = count or s.pool_size
    rng = np.random.default_rng(s.seed if seed is None else seed)
    if s.noise == "simulations":
        settings = sim.SimSettings.saved()
        settings.n_sims, settings.seed = count, (s.seed if seed is None else seed)
        result = sim.simulate_frame("build", base, fmt, settings)
        col = result.column_of()
        draws = np.stack([result.points[:, col[int(b)]] for b in pool["base_id"]], axis=1).astype(float)
        objs = draws * pool["mult"].to_numpy()
    else:
        sd = s.noise_sd
        objs = pool["proj"].to_numpy() * np.exp(rng.normal(-sd * sd / 2, sd, size=(count, len(pool))))
    limits = base.set_index("dfs_id")
    keep = np.ones(len(pool))
    for j, (b, slot) in enumerate(zip(pool["base_id"], pool["slot"])):
        cap = limits.at[b, "cpt_max"] if slot == "CPT" else limits.at[b, "max_exp"]
        keep[j] = min(1.0, cap / 100)
    left_out = rng.random(objs.shape) > keep
    objs[left_out] = AVOID
    if len(blocked):
        objs[:, list(blocked)] = AVOID
    return objs


def candidates(pool, base, fmt, s, n, count=None, seed=None, blocked=(), with_targeted=True):
    A, lo, hi, n_extra = model(pool, fmt, s)
    objs = objectives(pool, base, fmt, s, count, seed, blocked)
    workers = s.workers or max(1, (os.cpu_count() or 2) - 1)
    jobs = [(A, lo, hi, n_extra, c) for c in np.array_split(objs, max(1, min(workers * 4, len(objs))))]
    if with_targeted:
        jobs += targeted(pool, base, fmt, s, n)
    results = None
    if workers > 1:
        try:
            # "spawn" is how macOS starts processes; using it everywhere keeps tests honest.
            with _workers_skip_the_app():
                with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
                    results = list(ex.map(_solve_chunk, jobs))
        except (OSError, BrokenProcessPool, RuntimeError):
            results = None                                   # fall back to one process below
    if results is None:
        results = [_solve_chunk(job) for job in jobs]
    seen, out = set(), []
    for chunk in results:
        for lu in chunk:
            if lu is None:
                continue
            key = _identity(lu, pool, fmt)
            if key not in seen:
                seen.add(key)
                out.append(_ordered(lu, pool, fmt))
    if not out:
        raise FileProblem("No legal lineup fits these settings. Loosen the salary floor, stacking rules, "
                          "ownership cap or exposures.")
    return out


def _identity(lu, pool, fmt):
    if fmt == rosters.SHOWDOWN:
        return tuple(sorted((pool.at[r, "slot"], int(pool.at[r, "base_id"])) for r in lu))
    return tuple(sorted(int(pool.at[r, "base_id"]) for r in lu))


def _ordered(lu, pool, fmt):
    if fmt == rosters.SHOWDOWN:
        return sorted(lu, key=lambda r: (pool.at[r, "slot"] != "CPT", -pool.at[r, "salary"]))
    return list(lu)


# ---------------------------------------------------------------- 4. fill (SPEC 5.3 method 2)

class _Fill:
    """Top by projection with N uniques (SPEC 5.3 method 2).

    Lineups are taken best projection first while they respect the max exposures, captain
    limits and uniques. Minimums (player and captain exposure, the game coverage floor) are
    protected by reserving room: once the lineups left are only just enough to reach a minimum,
    only lineups that help are taken.
    """

    def __init__(self, cands, pool, base, fmt, n, s):
        self.fmt, self.n, self.s = fmt, n, s
        proj = pool["proj"].to_numpy()
        order = sorted(range(len(cands)), key=lambda i: -proj[list(cands[i])].sum())
        self.cands = [tuple(cands[i]) for i in order]
        base_of = pool["base_id"].to_numpy()
        is_cpt = (pool["slot"] == "CPT").to_numpy()
        game_of = [tuple(sorted((t, o))) for t, o in zip(pool["team"], pool["opp"])]
        self.members = [[(int(base_of[r]), bool(is_cpt[r]), game_of[r]) for r in lu] for lu in self.cands]
        if fmt == rosters.SHOWDOWN:
            self.items = [frozenset((c, b) for b, c, _ in m) for m in self.members]
        else:
            self.items = [frozenset(b for b, _, _ in m) for m in self.members]

        limits = base.set_index("dfs_id")
        cap = lambda pct: math.floor(pct / 100 * n + 1e-9)   # noqa: E731
        need = lambda pct: math.ceil(pct / 100 * n - 1e-9)   # noqa: E731
        self.max_p = {b: cap(limits.at[b, "max_exp"]) for b in limits.index}
        self.max_c = {b: cap(limits.at[b, "cpt_max"]) for b in limits.index}
        self.demand = {("p", b): need(limits.at[b, "min_exp"]) for b in limits.index if limits.at[b, "min_exp"] > 0}
        self.demand.update({("c", b): need(limits.at[b, "cpt_min"]) for b in limits.index
                            if limits.at[b, "cpt_min"] > 0})
        self.demand.update({("g", g): v for g, v in coverage_demands(base, fmt, n, s).items()})
        self.contrib = []
        for m in self.members:
            c = {}
            for b, is_c, g in m:
                for key in (("p", b), ("c", b) if is_c else None, ("g", g)):
                    if key in self.demand:
                        c[key] = c.get(key, 0) + 1
            self.contrib.append(c)

    def run(self):
        n = self.n
        chosen, dead = [], [False] * len(self.cands)
        p, c, have = {}, {}, {k: 0 for k in self.demand}
        while len(chosen) < n:
            remaining = n - len(chosen)
            # Start protecting a minimum a little early, while there's still room to choose.
            urgent = {k for k, need in self.demand.items() if need - have[k] >= RESERVE_AT * remaining}
            best_partial, pick = None, None
            for i, members in enumerate(self.members):
                if dead[i]:
                    continue
                if not self._fits(i, members, chosen, p, c):
                    dead[i] = True                           # caps and uniques only ever tighten
                    continue
                helps = sum(1 for k in urgent if self.contrib[i].get(k))
                if helps == len(urgent):
                    pick = i
                    break
                if best_partial is None or helps > best_partial[1]:
                    best_partial = (i, helps)
            if pick is None and best_partial is not None:
                pick = best_partial[0]
            if pick is None:
                break
            dead[pick] = True
            chosen.append(pick)
            for b, is_c, _ in self.members[pick]:
                p[b] = p.get(b, 0) + 1
                if is_c:
                    c[b] = c.get(b, 0) + 1
            for k, v in self.contrib[pick].items():
                have[k] += v
        chosen = self._repair(chosen)
        return [list(self.cands[i]) for i in chosen]

    def _counts(self, chosen):
        p, c, have = {}, {}, {k: 0 for k in self.demand}
        for j in chosen:
            for b, is_c, _ in self.members[j]:
                p[b] = p.get(b, 0) + 1
                if is_c:
                    c[b] = c.get(b, 0) + 1
            for k, v in self.contrib[j].items():
                have[k] += v
        return p, c, have

    def _repair(self, chosen, rounds=60, victims=30):
        """Swap weak lineups for ones that close a remaining minimum without opening another."""
        for _ in range(rounds):
            p, c, have = self._counts(chosen)
            short = [k for k, need in self.demand.items() if have[k] < need]
            if not short:
                break
            k = short[0]
            swapped = False
            for v in sorted(chosen, reverse=True)[:victims]:        # the lowest-projected first
                others = [j for j in chosen if j != v]
                po, co, ho = self._counts(others)
                taken = set(chosen)
                for i in range(len(self.cands)):
                    if i in taken or not self.contrib[i].get(k) or not self._fits(i, self.members[i], others, po, co):
                        continue
                    after = {q: ho[q] + self.contrib[i].get(q, 0) for q in self.demand}
                    if all(after[q] >= need or after[q] >= have[q] for q, need in self.demand.items()) \
                            and after[k] > have[k]:
                        chosen, swapped = others + [i], True
                        break
                if swapped:
                    break
            if not swapped:
                break
        return chosen

    def _fits(self, i, members, chosen, p, c):
        for b, is_c, _ in members:
            if p.get(b, 0) + 1 > self.max_p.get(b, self.n):
                return False
            if is_c and c.get(b, 0) + 1 > self.max_c.get(b, self.n):
                return False
        mine, size, u = self.items[i], len(members), self.s.min_uniques
        return all(size - len(mine & self.items[j]) >= u for j in chosen)


def _at_cap(chosen, pool, base, n):
    """Pool rows whose player (or captain) has reached its max exposure in `chosen`."""
    limits = base.set_index("dfs_id")
    p, c = {}, {}
    for lu in chosen:
        for r in lu:
            b = int(pool.at[r, "base_id"])
            p[b] = p.get(b, 0) + 1
            if pool.at[r, "slot"] == "CPT":
                c[b] = c.get(b, 0) + 1
    out = []
    for j, (b, slot) in enumerate(zip(pool["base_id"], pool["slot"])):
        if p.get(b, 0) >= math.floor(limits.at[b, "max_exp"] / 100 * n + 1e-9):
            out.append(j)
        elif slot == "CPT" and c.get(b, 0) >= math.floor(limits.at[b, "cpt_max"] / 100 * n + 1e-9):
            out.append(j)
    return out


def coverage_demands(base, fmt, n, s):
    """Game coverage floor (SPEC 5.4): players needed from each game with a big total."""
    if fmt != rosters.CLASSIC or not s.coverage_floor:
        return {}
    totals = base.groupby(base.apply(lambda r: tuple(sorted((r["team"], r["opp"]))), axis=1))["saber_total"].max()
    return {g: math.ceil(s.coverage_per_lineup * n - 1e-9) for g, t in totals.items()
            if pd.notna(t) and t >= s.coverage_total}


def targeted(pool, base, fmt, s, n):
    """Extra candidates for every minimum, so the fill has lineups that can meet it."""
    A, lo, hi, n_extra = model(pool, fmt, s)
    jobs = []
    base_of = pool["base_id"].to_numpy()
    is_cpt = (pool["slot"] == "CPT").to_numpy()
    game_of = [tuple(sorted((t, o))) for t, o in zip(pool["team"], pool["opp"])]
    limits = base.set_index("dfs_id")
    wanted = [(("p", b), math.ceil(limits.at[b, "min_exp"] / 100 * n)) for b in limits.index
              if limits.at[b, "min_exp"] > 0]
    wanted += [(("c", b), math.ceil(limits.at[b, "cpt_min"] / 100 * n)) for b in limits.index
               if limits.at[b, "cpt_min"] > 0]
    wanted += [(("g", g), math.ceil(v / 2)) for g, v in coverage_demands(base, fmt, n, s).items()]
    rng = np.random.default_rng(s.seed + 1)
    for (kind, key), need in wanted:
        if kind == "g":
            row, low = np.array([g == key for g in game_of], float), 2
        else:
            row = ((base_of == key) & (is_cpt if kind == "c" else True)).astype(float)
            low = 1
        if not row.any():
            continue
        k = int(min(3 * need, 150))
        row = np.concatenate([row, np.zeros(n_extra)])
        noise = np.exp(rng.normal(-s.noise_sd ** 2 / 2, s.noise_sd, size=(k, len(pool))))
        jobs.append((vstack([A, csr_matrix(row)]).tocsr(), np.append(lo, low), np.append(hi, np.inf), n_extra,
                     pool["proj"].to_numpy() * noise))
    return jobs


# ---------------------------------------------------------------- 5. checks and export

def build(slate_id, s=None, root=None, progress=None):
    s = s or BuildSettings()
    manifest = make_snapshot(slate_id, s.name, s.allow_post_game_export, root)
    players, ss, ent, tags = read_snapshot(manifest)
    base, fmt, warnings = prepare(players, ss, ent, tags, s)
    warnings = manifest["warnings"] + warnings

    template = None
    if ent is not None and ent.fmt != fmt:
        raise FileProblem(f"The entries file is {ent.fmt} but the SaberSim export is {fmt}.")
    if ent is not None and not ent.all_entries:
        warnings.append(f"The entries file has no entries, so a plain lineup file with {s.n_lineups} lineups is "
                        f"written instead (upload it as new lineups).")
    elif ent is not None:
        template = [e for e in ent.all_entries if not s.contests or e.contest_id in {str(c) for c in s.contests}]
        if not template:
            raise FileProblem("None of the entries file's entries are in the chosen contest(s).")
    n = len(template) if template else s.n_lineups

    pool = pool_rows(base, players, fmt)
    if progress:
        progress(f"Optimizing {s.pool_size:,} candidate lineups...")
    cands = candidates(pool, base, fmt, s, n)
    if progress:
        progress(f"Choosing {n} lineups from {len(cands):,} distinct candidates...")
    chosen = _Fill(cands, pool, base, fmt, n, s).run()
    for round_no in range(1, TOP_UP_ROUNDS + 1):
        if len(chosen) >= n:
            break
        # Short: add candidates without the players (and captains) already at their caps.
        blocked = _at_cap(chosen, pool, base, n)
        if progress:
            progress(f"Only {len(chosen)} of {n} fit; adding candidates without {len(blocked)} capped rows...")
        extra = candidates(pool, base, fmt, s, n, count=max(200, s.pool_size // 2), seed=s.seed + 100 * round_no,
                           blocked=blocked, with_targeted=False)
        known = {_identity(lu, pool, fmt) for lu in cands}
        cands += [lu for lu in extra if _identity(lu, pool, fmt) not in known]
        chosen = _Fill(cands, pool, base, fmt, n, s).run()
    result = BuildResult(slate_id, s, fmt, chosen, pool, base, manifest, len(cands), warnings, template=template)
    check(result)
    if template:
        result.template = template[:len(chosen)]
    save(result, root)
    return result


def check(r):
    """Legality, exposures, coverage, chalk and ownership (SPEC 4, 5.4)."""
    s, n, pool = r.settings, len(r.lineups), r.pool
    lookup = pool.set_index("dfs_id")[["base_id", "pos", "team", "opp", "salary", "slot"]].rename(
        columns={"slot": "roster_slot"})
    illegal = []
    for i, ids in enumerate(r.lineup_ids()):
        why = legal.problems(ids, lookup, r.fmt)
        if why:
            illegal.append(f"lineup {i + 1}: {'; '.join(why)}")
    identities = [_identity(lu, pool, r.fmt) for lu in r.lineups]
    target = len(r.template) if r.template else s.n_lineups
    r.checks = {
        "lineups": n, "target": target, "legal": n - len(illegal), "illegal": illegal,
        "duplicates": n - len(set(identities)),
        "avg_proj": round(float(np.mean([pool.loc[list(lu), "proj"].sum() for lu in r.lineups])), 2) if n else 0,
        "avg_salary": round(float(np.mean([pool.loc[list(lu), "salary"].sum() for lu in r.lineups])), 0) if n else 0,
        "avg_own": round(float(np.mean([pool.loc[list(lu), "own"].sum() for lu in r.lineups])), 1) if n else 0,
    }
    if n < target:
        r.warnings.append(f"Only {n} of {target} lineups could be built with these settings (uniques, exposure "
                          f"caps or a small candidate pool). Loosen them or raise the pool size.")

    counts, cpts = {}, {}
    for lu in r.lineups:
        for row in lu:
            b = int(pool.at[row, "base_id"])
            counts[b] = counts.get(b, 0) + 1
            if pool.at[row, "slot"] == "CPT":
                cpts[b] = cpts.get(b, 0) + 1
    p = r.players.copy()
    p["count"] = p["dfs_id"].map(counts).fillna(0).astype(int)
    p["exposure"] = (100 * p["count"] / max(n, 1)).round(1)
    if r.fmt == rosters.SHOWDOWN:
        p["cpt_count"] = p["dfs_id"].map(cpts).fillna(0).astype(int)
        p["cpt_exposure"] = (100 * p["cpt_count"] / max(n, 1)).round(1)
    r.players = p

    short = p[(p["exposure"] + 1e-9 < p["min_exp"]) | (p["exposure"] > p["max_exp"] + 100 / max(n, 1))]
    for row in short.itertuples():
        r.warnings.append(f"{row.name}: exposure {row.exposure}% is outside the {row.min_exp:g}-{row.max_exp:g}% "
                          f"limit (not enough candidate lineups fit every rule).")
    if r.fmt == rosters.SHOWDOWN:
        off = p[(p["cpt_exposure"] + 1e-9 < p["cpt_min"])]
        for row in off.itertuples():
            r.warnings.append(f"{row.name}: captain {row.cpt_exposure}% is below the {row.cpt_min:g}% minimum.")

    chalk = p[(p["own"] >= s.chalk_own) & (p["exposure"] >= p["own"] + s.chalk_margin)]
    r.checks["chalk"] = [f"{row.name}: {row.exposure}% vs {row.own:.0f}% projected field ownership"
                         for row in chalk.itertuples()]

    coverage = []
    if r.fmt == rosters.CLASSIC:
        games = p.assign(game=p.apply(lambda x: "@".join(sorted((x["team"], x["opp"]))), axis=1))
        for g, grp in games.groupby("game"):
            per = grp["count"].sum() / max(n, 1)
            total = grp["saber_total"].max()
            coverage.append({"Game": g, "Total": total, "Players per lineup": round(float(per), 2),
                             "Floor": s.coverage_per_lineup if s.coverage_floor and pd.notna(total)
                             and total >= s.coverage_total else None})
            if s.coverage_floor and pd.notna(total) and total >= s.coverage_total and per + 1e-9 < s.coverage_per_lineup:
                r.warnings.append(f"Game coverage: {g} (total {total}) has {per:.2f} players per lineup, under "
                                  f"the {s.coverage_per_lineup} floor.")
    r.checks["coverage"] = coverage


def slot_order(ids, lookup, fmt):
    """DraftKings column order. Classic FLEX gets the latest-kickoff RB/WR/TE that can move there."""
    if fmt == rosters.SHOWDOWN:
        return ids
    by_pos = {p: [] for p in ("QB", "RB", "WR", "TE", "DST")}
    for i in ids:
        by_pos[lookup.at[i, "pos"]].append(i)
    need = {"RB": 2, "WR": 3, "TE": 1}
    surplus = [p for p, k in need.items() if len(by_pos[p]) > k]
    flex_pos = surplus[0]
    late_first = sorted(by_pos[flex_pos], key=lambda i: (lookup.at[i, "late"], -lookup.at[i, "salary"]),
                        reverse=True)
    flex = late_first[0]
    by_pos[flex_pos].remove(flex)
    return by_pos["QB"] + by_pos["RB"] + by_pos["WR"] + by_pos["TE"] + [flex] + by_pos["DST"]


def to_csv(r, path):
    lookup = r.pool.set_index("dfs_id")
    rows = [slot_order(ids, lookup, r.fmt) for ids in r.lineup_ids()]
    slots = rosters.SLOTS[r.fmt]
    if r.template:
        header = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", *slots]
        body = [[e.entry_id, e.contest_name, e.contest_id, _fee(e.fee_cents), *ids] for e, ids in zip(r.template, rows)]
    else:
        header, body = slots, rows
    pd.DataFrame(body, columns=header).to_csv(path, index=False)
    return path


def _fee(cents):
    if cents is None:
        return ""
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def save(r, root=None):
    folder = slate.slate_dir(r.slate_id, root) / "builds"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"dfslab-{r.settings.name}"
    r.csv_path = str(to_csv(r, folder / f"{stem}.csv"))
    record = {
        "name": r.settings.name, "slate": r.slate_id, "format": r.fmt, "built_at": datetime.now().isoformat(timespec="seconds"),
        "settings": asdict(r.settings), "war_room_rules_used": r.settings.warroom_rules,
        "late_game_haircut_used": bool(r.settings.late_haircut), "snapshot": r.snapshot,
        "candidates": r.candidates, "checks": r.checks, "warnings": r.warnings, "csv": r.csv_path,
        "contests": sorted({e.contest_id for e in r.template}) if r.template else [],
    }
    (folder / f"{stem}.json").write_text(json.dumps(record, indent=2, default=str))
    meta = builds.load_meta(r.slate_id, root)
    key = f"build:{r.settings.name}"
    old = meta.get(key, {})
    meta[key] = {**builds.DEFAULT, **old, "name": old.get("name") or f"DFS Lab {r.settings.name}",
                 "method": old.get("method") or f"DFS Lab {r.settings.name}",
                 "refill": bool(r.snapshot.get("post_game_export")) or old.get("refill", False)}
    builds.save_meta(r.slate_id, meta, root)


def list_builds(slate_id, root=None):
    folder = slate.slate_dir(slate_id, root) / "builds"
    return sorted(p.stem.removeprefix("dfslab-") for p in folder.glob("dfslab-*.json")) if folder.exists() else []


def load_record(slate_id, name, root=None):
    return json.loads((slate.slate_dir(slate_id, root) / "builds" / f"dfslab-{name}.json").read_text())


def exposure_table(r):
    p = r.players
    cols = ["pos", "team", "name", "salary", "proj", "own", "tag", "min_exp", "max_exp", "count", "exposure"]
    if r.fmt == rosters.SHOWDOWN:
        cols += ["cpt_min", "cpt_max", "cpt_count", "cpt_exposure"]
    t = p[p["count"] > 0][cols].sort_values(["count", "proj"], ascending=False)
    return t.rename(columns={"pos": "Pos", "team": "Team", "name": "Player", "salary": "Salary", "proj": "Proj",
                             "own": "Proj own %", "tag": "War Room", "min_exp": "Min %", "max_exp": "Max %",
                             "count": "Count", "exposure": "Exposure %", "cpt_min": "CPT min %",
                             "cpt_max": "CPT max %", "cpt_count": "CPT count", "cpt_exposure": "CPT %"})
