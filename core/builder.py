"""DFS Lab's own lineup builder (SPEC 5.2-5.4, section 7).

1. Snapshot: the pre-lock inputs are copied into slates/<slate>/prelock/<build>/ with a hash of
   each file and the time. The build reads only these copies.
2. Candidates: thousands of optimal lineups, each for projections with random noise
   (~25% lognormal) or for one simulated slate. Lineup rules are built into the optimizer.
3. Fill (SPEC 5.3), always respecting uniques, min/max exposures, captain limits and the game
   coverage floor. Method 2 (default): top by projection. Method 1: top by simulated ROI against
   a field model (SPEC 5.5) and the contest's payouts. Method 3: portfolio, each lineup added for
   the most new simulated slates in which the set finishes top 1%.
4. Checks: every lineup is checked against DraftKings' rules, and the guardrails (5.4) are reported.
5. Export: a DraftKings entries CSV to upload by hand. DFS Lab never touches DraftKings.

No hindsight (SPEC 7): Actual, Live Proj, FPTS, %Drafted and this slate's standings are never
read. The one exception is asked for by name: a "real field" backtest reads the contest's real
lineups, and the build is then marked hindsight. A synthetic field learns only salary and stacking
habits from *other* slates' standings.
"""

import contextlib
import heapq
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

from . import builds, detect, fieldmodel, legal, lateswap, rosters, sim, simcontest, slate
from .importers import entries as entries_imp
from .importers import payouts as payouts_imp
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
URGENT_EVAL = 200                      # value fills: candidates scored when a minimum is urgent
FILL_METHODS = {"projection": "top by projection", "roi": "top by simulated ROI",
                "portfolio": "portfolio (top-1% chance)"}


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
    fill: str = "projection"           # SPEC 5.3: "projection" (method 2), "roi" (1) or "portfolio" (3)
    roi_contest: str = None            # contest whose payouts and field score lineups (None = most entries)
    field_source: str = "synthetic"    # or "real": the contest's real lineups (backtests; marks hindsight)
    contest_size: int = None           # entries in that contest (a synthetic field needs it for ROI)
    entry_fee: float = None            # dollars, when the entries file doesn't say
    fill_sims: int = 2000              # simulated slates for fill methods 1 and 3 and simulated results
    field_sample: int = 20_000         # field lineups modeled
    simulated_results: bool = True     # report simulated ROI and top-1% odds when a field can be modeled

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
    sim: dict = None                   # simulated results (or why they were skipped)
    lineup_sim: pd.DataFrame = None    # per lineup: simulated top-1% chance and ROI
    hindsight: bool = False            # used the contest's real field

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
    for _, det, _ in parsed[detect.PAYOUTS]:                 # typed in before lock
        inputs.append(("payouts", det.path))

    stamp = datetime.now()
    folder = slate.slate_dir(slate_id, root) / "prelock" / f"{name}-{stamp:%Y%m%d-%H%M%S}"
    for k in range(2, 1000):                                 # two builds in the same second
        if not folder.exists():
            break
        folder = folder.with_name(f"{name}-{stamp:%Y%m%d-%H%M%S}-{k}")
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
    """Parse the snapshot's copies. Post-game columns are dropped immediately.
    Returns players, the SaberSim data, entries, War Room tags and {contest ID: prizes in dollars}."""
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
    payouts = {}
    for f in manifest["files"]:
        if f["role"] == "payouts":
            path = folder / f["file"]
            cid = detect.detect(path).contest_id
            payouts[cid] = prizes_from_table(payouts_imp.parse(path, cid))
    return players, ss, ent, tags, payouts


def prizes_from_table(table):
    """rank_from, rank_to, prize_cents rows -> dollars for rank 1, 2, ... (last paid rank last)."""
    prizes = np.zeros(int(table["rank_to"].max()))
    for lo, hi, cents in table.itertuples(index=False):
        prizes[lo - 1:hi] = cents / 100
    return prizes


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


# ---------------------------------------------------------------- 4. fill (SPEC 5.3)

class _Fill:
    """Choose n lineups from the candidates (SPEC 5.3).

    Method 2 (no `value_factory`): best projection first. Methods 1 and 3: the lineup that adds
    the most value to the set so far (simcontest.ROIValue / Top1Value), found lazily: a lineup's
    value only shrinks as the set grows, so stale values are upper bounds.

    Every method respects the max exposures, captain limits and uniques. Minimums (player and
    captain exposure, the game coverage floor) are protected by reserving room: once the lineups
    left are only just enough to reach a minimum, only lineups that help are taken.
    """

    def __init__(self, cands, pool, base, fmt, n, s, value_factory=None):
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
        # Candidates x items (0/1), so overlaps with a newly chosen lineup take one matrix step.
        vocab = {x: j for j, x in enumerate(sorted({x for it in self.items for x in it}, key=str))}
        self.onehot = np.zeros((len(self.items), len(vocab)), dtype=np.float32)
        for i, it in enumerate(self.items):
            self.onehot[i, [vocab[x] for x in it]] = 1
        self.sizes = self.onehot.sum(axis=1)

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
        self.value = value_factory(self.cands) if value_factory else None

    def run(self):
        n = self.n
        chosen, dead = [], [False] * len(self.cands)
        p, c, have = {}, {}, {k: 0 for k in self.demand}
        self.blocked = np.zeros(len(self.cands), dtype=bool)         # too few uniques vs a chosen lineup
        heap = None
        if self.value:
            heap = [(-self.value.bound(i), -self.value.secondary(i), i) for i in range(len(self.cands))]
            heapq.heapify(heap)
        while len(chosen) < n:
            remaining = n - len(chosen)
            # Start protecting a minimum a little early, while there's still room to choose.
            urgent = {k for k, need in self.demand.items() if need - have[k] >= RESERVE_AT * remaining}
            if self.value:
                pick = self._pick_value(heap, urgent, dead, chosen, p, c)
            else:
                pick = self._pick_order(urgent, dead, chosen, p, c)
            if pick is None:
                break
            dead[pick] = True
            chosen.append(pick)
            self.blocked |= self.sizes - self.onehot @ self.onehot[pick] < self.s.min_uniques - 1e-9
            if self.value:
                self.value.add(pick)
            for b, is_c, _ in self.members[pick]:
                p[b] = p.get(b, 0) + 1
                if is_c:
                    c[b] = c.get(b, 0) + 1
            for k, v in self.contrib[pick].items():
                have[k] += v
        chosen = self._repair(chosen)
        return [list(self.cands[i]) for i in chosen]

    def _pick_order(self, urgent, dead, chosen, p, c):
        """Method 2: the best-projected lineup that fits (and helps every urgent minimum)."""
        best_partial = None
        for i, members in enumerate(self.members):
            if dead[i]:
                continue
            if not self._fits_now(i, members, p, c):
                dead[i] = True                               # caps and uniques only ever tighten
                continue
            helps = sum(1 for k in urgent if self.contrib[i].get(k))
            if helps == len(urgent):
                return i
            if best_partial is None or helps > best_partial[1]:
                best_partial = (i, helps)
        return best_partial[0] if best_partial else None

    def _pick_value(self, heap, urgent, dead, chosen, p, c):
        """Methods 1 and 3: the lineup that adds the most value (lazy greedy)."""
        v = self.value
        if urgent:
            feasible = []
            for i, members in enumerate(self.members):
                if dead[i]:
                    continue
                if not self._fits_now(i, members, p, c):
                    dead[i] = True
                    continue
                feasible.append((sum(1 for k in urgent if self.contrib[i].get(k)), i))
            if not feasible:
                return None
            most = max(h for h, _ in feasible)
            group = sorted((i for h, i in feasible if h == most), key=lambda i: (-v.bound(i), i))[:URGENT_EVAL]
            return max(group, key=lambda i: (v.exact(i), v.secondary(i), -i))
        if hasattr(v, "order"):                                  # cheap to score every candidate at once
            for i in v.order():
                if dead[i]:
                    continue
                if not self._fits_now(i, self.members[i], p, c):
                    dead[i] = True
                    continue
                return int(i)
            return None
        while heap:
            _, _, i = heapq.heappop(heap)
            if dead[i]:
                continue
            if not self._fits_now(i, self.members[i], p, c):
                dead[i] = True
                continue
            key = (-v.exact(i), -v.secondary(i), i)
            if not heap or key <= heap[0]:
                return i
            heapq.heappush(heap, key)
        return None

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

    def _fits_now(self, i, members, p, c):
        """_fits for the lineups chosen so far in run(), with uniques read from self.blocked."""
        if self.blocked[i]:
            return False
        for b, is_c, _ in members:
            if p.get(b, 0) + 1 > self.max_p.get(b, self.n):
                return False
            if is_c and c.get(b, 0) + 1 > self.max_c.get(b, self.n):
                return False
        return True

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
    if s.fill not in FILL_METHODS:
        raise FileProblem(f"Unknown fill method '{s.fill}'. Pick one of: {', '.join(FILL_METHODS)}.")
    manifest = make_snapshot(slate_id, s.name, s.allow_post_game_export, root)
    players, ss, ent, tags, payouts = read_snapshot(manifest)
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
    scoring, skipped = None, None
    if s.fill != "projection" or s.simulated_results:
        try:
            scoring = Scoring.setup(slate_id, players, base, fmt, template, ent, payouts, s, root, progress)
        except FileProblem as e:
            if s.fill != "projection":
                raise
            skipped = str(e)
    factory = scoring.value_factory(pool, s.fill) if scoring and s.fill != "projection" else None

    if progress:
        progress(f"Optimizing {s.pool_size:,} candidate lineups...")
    cands = candidates(pool, base, fmt, s, n)
    if progress:
        progress(f"Choosing {n} lineups from {len(cands):,} distinct candidates ({FILL_METHODS[s.fill]})...")
    chosen = _Fill(cands, pool, base, fmt, n, s, factory).run()
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
        chosen = _Fill(cands, pool, base, fmt, n, s, factory).run()
    result = BuildResult(slate_id, s, fmt, chosen, pool, base, manifest, len(cands), warnings, template=template)
    check(result)
    if template:
        result.template = template[:len(chosen)]
    if scoring:
        if progress:
            progress("Simulating the build against the field...")
        result.sim, result.lineup_sim = scoring.report(pool, chosen, s)
        result.hindsight = scoring.field.source == "real"
        if result.hindsight:
            result.warnings += scoring.field.notes
    else:
        result.sim = {"skipped": skipped} if skipped else None
    save(result, root)
    return result


class Scoring:
    """The simulated contest a build is scored in: one set of simulated slates, the field model
    (SPEC 5.5) and the contest's terms (payouts, entries, fee)."""

    def __init__(self, terms, field, simulation, cents, scorer, notes):
        self.terms, self.field, self.simulation, self.scorer, self.notes = terms, field, simulation, scorer, notes
        self.col, self.cents = simulation.column_of(), cents

    @classmethod
    def setup(cls, slate_id, players, base, fmt, template, ent, payouts, s, root=None, progress=None):
        say = progress or (lambda _: None)
        terms = contest_terms(template, ent, payouts, s)
        if s.fill == "roi":
            missing = []
            if terms.contest_id is None:
                missing.append("a contest to score against")
            elif terms.prizes is None:
                missing.append(f"a payout file for contest {terms.contest_id} (payouts-{terms.contest_id}.csv)")
            if terms.fee is None:
                missing.append("the entry fee")
            if s.field_source != "real" and not s.contest_size:
                missing.append("the contest size (entries)")
            if missing:
                raise FileProblem("Top by simulated ROI needs " + ", ".join(missing) + ".")
        if s.field_source == "real":
            if terms.contest_id is None:
                raise FileProblem("Pick the contest whose real field to use.")
            say(f"Reading contest {terms.contest_id}'s real field (backtest)...")
            fp = fieldmodel.field_players(players, base, fmt, need_ownership=False)
            fld = fieldmodel.real_field(slate_id, terms.contest_id, fp, fmt, s.field_sample, s.seed, root)
            terms.size = fld.size
        else:
            say("Learning the field's salary and stacking habits from past standings...")
            habits = fieldmodel.learn_habits(fmt, slate_id, root)
            fp = fieldmodel.field_players(players, base, fmt)
            terms.size = s.contest_size or None
            size = min(s.field_sample, terms.size) if terms.size else s.field_sample
            say(f"Drawing a {size:,}-lineup field from projected ownership...")
            fld = fieldmodel.synthetic_field(fp, fmt, habits, size, s.seed)
            fld.size = terms.size
        proj = base.set_index("dfs_id")["proj"]
        fproj = fp["base_id"].map(proj).fillna(0.0).to_numpy() * fp["mult"].to_numpy()
        fld.info["field_avg_proj"] = round(float(fproj[fld.rows].sum(axis=1).mean()), 2)
        say(f"Simulating {s.fill_sims:,} slates for the field and your lineups...")
        settings = sim.SimSettings.saved(root)
        settings.n_sims, settings.seed = s.fill_sims, s.seed + 7   # not the candidates' noise
        simulation = sim.simulate_frame(slate_id, base, fmt, settings)
        col = simulation.column_of()
        cents = simcontest.player_cents(simulation.points)
        fcol = np.array([col[int(b)] for b in fp["base_id"]])
        fmult = np.rint(2 * fp["mult"].to_numpy()).astype(np.int32)
        scorer = simcontest.Scorer(cents, fcol[fld.rows], fmult[fld.rows], terms, terms.size)
        return cls(terms, fld, simulation, cents, scorer, list(fld.notes))

    def lineup_scores(self, pool, lineups):
        """Half-hundredth scores (lineups x sims) for lineups of pool rows (all the same size)."""
        rows = np.array([list(lu) for lu in lineups], dtype=np.int64)
        col = np.array([self.col[int(b)] for b in pool["base_id"]])
        mult = np.rint(2 * pool["mult"].to_numpy()).astype(np.int32)
        return simcontest.score(self.cents, col[rows], mult[rows])

    def value_factory(self, pool, fill):
        kind = simcontest.ROIValue if fill == "roi" else simcontest.Top1Value
        return lambda cands: kind(self.scorer, self.lineup_scores(pool, cands))

    def report(self, pool, chosen, s):
        t, f = self.terms, self.field
        rep = {"fill": s.fill, "contest": t.contest_id, "contest_name": t.name, "field": f.source,
               "field_lineups": len(f.rows), "contest_size": t.size, "fee": t.fee, "sims": s.fill_sims,
               "notes": self.notes, **{k: v for k, v in f.info.items() if k != "sha256"}}
        if f.source == "real":
            rep["standings_sha256"] = f.info.get("sha256")
        if not chosen:
            return rep, None
        ev = self.scorer.evaluate(self.lineup_scores(pool, chosen))
        rep["build_avg_proj"] = round(float(np.mean([pool.loc[list(lu), "proj"].sum() for lu in chosen])), 2)
        rep["set_top1_chance"] = round(100 * ev["any_top1"], 1)
        rep["avg_top1_rate"] = round(100 * float(ev["top1"].mean()), 2)
        per = pd.DataFrame({"Sim top 1% %": np.round(100 * ev["top1"], 2)})
        if "ev" in ev:
            fees = t.fee * len(chosen)
            won = float(ev["ev"].sum())
            rep.update(expected_winnings=round(won, 2), fees=round(fees, 2),
                       roi=round((won - fees) / fees, 4) if fees else None,
                       cash_rate=round(100 * float(ev["cash"].mean()), 1))
            per["Sim ROI %"] = np.round(100 * (ev["ev"] / t.fee - 1), 1) if t.fee else np.nan
        elif t.prizes is None:
            rep["roi_note"] = "No simulated ROI: there's no payout file for this contest."
        elif t.fee is None:
            rep["roi_note"] = "No simulated ROI: the entry fee isn't known."
        else:
            rep["roi_note"] = "No simulated ROI: enter the contest size (entries)."
        return rep, per


def contest_terms(template, ent, payouts, s):
    """The contest lineups are scored against: ID, name, fee and payouts (size comes later).
    Default: the contest with the most entries being filled. Name and fee come from the whole
    entries file, since you can score against a contest you aren't filling."""
    cid = str(s.roi_contest) if s.roi_contest else None
    if cid is None and template:
        cid = pd.Series([e.contest_id for e in template]).value_counts().index[0]
    if cid is None and len(payouts) == 1:
        cid = next(iter(payouts))
    name, fee = "", s.entry_fee
    if ent is not None:
        mine = [e for e in ent.all_entries if e.contest_id == cid]
        if mine:
            name = mine[0].contest_name
            fees = pd.Series([e.fee_cents for e in mine]).dropna()
            if fee is None and len(fees):
                fee = float(fees.value_counts().index[0]) / 100
    return simcontest.ContestTerms(cid, name, None, fee, payouts.get(cid) if cid else None)


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
        "fill_method": FILL_METHODS[r.settings.fill], "simulated": r.sim, "hindsight": r.hindsight,
    }
    (folder / f"{stem}.json").write_text(json.dumps(record, indent=2, default=str))
    meta = builds.load_meta(r.slate_id, root)
    key = f"build:{r.settings.name}"
    old = meta.get(key, {})
    method = old.get("method") or ""
    if not method or method.startswith("DFS Lab"):                # ours to keep up to date
        method = f"DFS Lab {FILL_METHODS[r.settings.fill]}"
    meta[key] = {**builds.DEFAULT, **old, "name": old.get("name") or f"DFS Lab {r.settings.name}",
                 "method": method,
                 "refill": bool(r.snapshot.get("post_game_export")) or old.get("refill", False),
                 "hindsight": r.hindsight}                           # set by this build's own inputs
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
