"""The field your lineups play against (SPEC 5.5).

Two kinds:
  synthetic - for future contests. Field lineups are drawn from the pre-lock projected ownership
              (SaberSim My Own), then shaped so their salary and stacking habits match what real
              fields did in *other* slates' standings files (e.g. most use nearly the full $50K).
              The ownership is then re-fitted so each player's share of the field stays close to
              his projected ownership.
  real      - for backtests. A sample of the contest's real lineups from its standings file. The
              standings are read, so a build that uses it is marked "hindsight" (SPEC 7).

A field is a sample of F lineups standing for a contest of N entries: each counts as N/F entries.
"""

import pickle
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import detect, rosters, slate
from .field import find_standings, load_field
from .importers import standings as standings_imp
from .io_utils import FileProblem, sha256_file
from .names import normalize_name

SALARY_LEFT_EDGES = np.array([0, 100, 300, 600, 1000, 1500, 2500, 4000])
N_CATS = {rosters.CLASSIC: 8, rosters.SHOWDOWN: 5}
HABIT_SAMPLE = 20_000                  # field lineups read per past contest
HABIT_CACHE_VERSION = 1
BATCH = 50_000                         # proposals drawn at a time
MAX_BATCHES = 40
IPF_ROUNDS = 4                         # ownership re-fitting rounds
PASS_CATCHERS = ("WR", "TE")
SKILL = ("RB", "WR", "TE")
CLASSIC_GROUPS = (("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1), ("DST", 1))


def describe_shape(fmt, code):
    """Plain words for a habit bin, e.g. '$100-299 left, QB + 2, bring-back'."""
    sal, cat = divmod(int(code), N_CATS[fmt])
    lo = SALARY_LEFT_EDGES[sal]
    hi = SALARY_LEFT_EDGES[sal + 1] - 1 if sal + 1 < len(SALARY_LEFT_EDGES) else None
    money = f"${lo:,}-{hi:,} left" if hi is not None else f"${lo:,}+ left"
    if fmt == rosters.SHOWDOWN:
        return f"{money}, {cat + 1}-{5 - cat} split toward the captain's team"
    stack, bring = divmod(cat, 2)
    return f"{money}, QB + {stack}{'+' if stack == 3 else ''}" + (", bring-back" if bring else "")


# ---------------------------------------------------------------- players

def field_players(players, base, fmt, need_ownership=True):
    """Every roster row the field can use: one per player (classic), or CPT and FLEX rows
    (showdown). `own` is the projected ownership in % (after any late-game haircut)."""
    cols = ["dfs_id", "name", "name_key", "pos", "team", "opp", "salary", "own"]
    fp = base[cols].assign(base_id=base["dfs_id"], mult=1.0,
                           slot="FLEX" if fmt == rosters.SHOWDOWN else "")
    if fmt == rosters.SHOWDOWN:
        base_of = {(k, t): i for k, t, i in zip(base["name_key"], base["team"], base["dfs_id"])}
        rows = []
        for r in players[players["roster_slot"] == "CPT"].itertuples():
            b = base_of.get((r.name_key, r.team))
            if b is not None:
                rows.append({"dfs_id": int(r.dfs_id), "name": r.name, "name_key": r.name_key, "pos": r.pos,
                             "team": r.team, "opp": r.opp, "salary": int(r.salary),
                             "own": float(r.my_own) if pd.notna(r.my_own) else 0.0,
                             "base_id": int(b), "mult": 1.5, "slot": "CPT"})
        fp = pd.concat([pd.DataFrame(rows), fp], ignore_index=True)
    fp = fp.reset_index(drop=True)
    fp["own"] = pd.to_numeric(fp["own"], errors="coerce").fillna(0.0).clip(lower=0.0)
    fp["salary"] = fp["salary"].astype(np.int64)
    fp["base_id"] = fp["base_id"].astype(np.int64)
    if need_ownership and fp["own"].sum() <= 0:
        raise FileProblem("The SaberSim export has no projected ownership (My Own), so DFS Lab can't model "
                          "the field. Re-export it with ownership loaded.")
    return fp


# ---------------------------------------------------------------- habits from past standings

def shape_codes(fmt, salary, team, opp, is_pc, is_skill):
    """Habit bin per lineup: salary left x stack shape. Arrays are lineups x roster slots, with
    the QB (classic) or captain (showdown) in the first column."""
    left = rosters.SALARY_CAP - salary.sum(axis=1)
    sal_bin = np.clip(np.searchsorted(SALARY_LEFT_EDGES, left, side="right") - 1, 0, len(SALARY_LEFT_EDGES) - 1)
    if fmt == rosters.SHOWDOWN:
        cat = np.clip((team == team[:, :1]).sum(axis=1) - 1, 0, 4)       # players on the captain's team
    else:
        stack = (is_pc[:, 1:] & (team[:, 1:] == team[:, :1])).sum(axis=1)
        bring = (is_skill[:, 1:] & (team[:, 1:] == opp[:, :1])).any(axis=1)
        cat = np.minimum(stack, 3) * 2 + bring
    return sal_bin * N_CATS[fmt] + cat


@dataclass
class Habits:
    fmt: str
    counts: dict                       # habit bin -> field lineups
    sources: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def lineups(self):
        return int(sum(self.counts.values()))

    def shares(self):
        n = self.lineups
        return {k: v / n for k, v in self.counts.items()}

    def table(self):
        rows = sorted(self.shares().items(), key=lambda kv: -kv[1])
        return pd.DataFrame([{"Field habit": describe_shape(self.fmt, k), "Share %": round(100 * v, 1)}
                             for k, v in rows])


def learn_habits(fmt, exclude_slate, root=None):
    """Salary and stacking habits of real fields, from every *other* slate's standings files of
    this format. Needs that slate's SaberSim export to know each player's salary and team."""
    h = Habits(fmt, {})
    for sid in slate.list_slates(root):
        if sid == exclude_slate:
            continue
        dets = [d for d in (detect.detect(p) for p in slate.raw_files(sid, root))
                if d.kind == detect.STANDINGS and d.contest_id]
        players = None
        for det in dets:
            cache = (slate.slate_dir(sid, root) / "results" / "cache" /
                     f"habits-{det.contest_id}-{sha256_file(det.path)[:16]}.pkl")
            data = _read_cache(cache)
            if data is None:
                if players is None:
                    players = _slate_players(sid, root)
                if not players:
                    h.notes.append(f"{sid}: has standings but no SaberSim export, so its field habits can't be read.")
                    break
                data = _contest_shapes(sid, det.contest_id, players, root)
                cache.parent.mkdir(parents=True, exist_ok=True)
                with cache.open("wb") as f:
                    pickle.dump((HABIT_CACHE_VERSION, data), f)
            c_fmt, counts, used, skipped = data
            if c_fmt != fmt or not used:
                continue
            for k, v in counts.items():
                h.counts[k] = h.counts.get(k, 0) + v
            h.sources.append(f"{sid} contest {det.contest_id} ({used:,} lineups)")
    if not h.counts:
        raise FileProblem(
            f"A synthetic field needs the salary and stacking habits of past {fmt} fields, and no other slate has "
            f"a {fmt} standings file (plus its SaberSim export) to learn them from. Import one past {fmt} contest's "
            f"standings with its SaberSim export as its own slate, or use the real field (backtests only; the build "
            f"is marked hindsight).")
    return h


def _read_cache(path):
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            version, data = pickle.load(f)
        return data if version == HABIT_CACHE_VERSION else None
    except Exception:
        return None


def _slate_players(sid, root=None):
    """name key (classic) or (name key, CPT/FLEX) (showdown) -> (salary, pos, team, opp)."""
    skip = (detect.STANDINGS, detect.DK_ENTRIES, detect.LINEUPS, detect.PAYOUTS, detect.WARROOM)
    exports = slate.load_parsed(sid, root, skip=skip)[detect.SABERSIM]
    if not exports:
        return {}
    df = exports[-1][2].players
    if exports[-1][2].fmt == rosters.SHOWDOWN:
        keys = list(zip(df["name_key"], df["roster_slot"]))
    else:
        keys = list(df["name_key"])
    counts = Counter(keys)
    return {k: (int(s), p, t, o) for k, s, p, t, o in zip(keys, df["salary"], df["pos"], df["team"], df["opp"])
            if counts[k] == 1}


def _contest_shapes(sid, contest_id, players, root=None):
    fld = load_field(sid, contest_id, root)
    fmt = fld.fmt()
    texts = fld.entries["lineup"].to_numpy()
    if len(texts) > HABIT_SAMPLE:
        texts = texts[np.random.default_rng(0).choice(len(texts), HABIT_SAMPLE, replace=False)]
    rows, skipped = [], 0
    for text in texts:
        info = _map_lineup(text, fmt, players)
        if info is None:
            skipped += 1
        else:
            rows.append(info)
    if not rows or fmt is None:
        return fmt, {}, 0, skipped
    sal = np.array([[i[0] for i in r] for r in rows])
    pos = np.array([[i[1] for i in r] for r in rows])
    team = np.array([[i[2] for i in r] for r in rows])
    opp = np.array([[i[3] for i in r] for r in rows])
    codes = shape_codes(fmt, sal, team, opp, np.isin(pos, PASS_CATCHERS), np.isin(pos, SKILL))
    return fmt, dict(Counter(codes.tolist())), len(rows), skipped


def _map_lineup(text, fmt, lookup):
    """A standings lineup string -> the lookup's value per player, QB/captain first; None if any
    player can't be matched."""
    pairs = standings_imp.parse_lineup(text)
    if not pairs or rosters.format_for_tags([t for t, _ in pairs]) != fmt:
        return None
    first = "CPT" if fmt == rosters.SHOWDOWN else "QB"
    pairs = sorted(pairs, key=lambda p: p[0] != first)
    if fmt == rosters.SHOWDOWN:
        keys = [(normalize_name(n), "CPT" if t == "CPT" else "FLEX") for t, n in pairs]
    else:
        keys = [normalize_name(n) for _, n in pairs]
    out = [lookup.get(k) for k in keys]
    return None if any(v is None for v in out) else out


# ---------------------------------------------------------------- the field itself

@dataclass
class FieldLineups:
    rows: np.ndarray                   # F x roster size, row numbers in `players`
    players: pd.DataFrame              # field_players() table
    source: str                        # "synthetic" or "real"
    size: int = None                   # contest entries the sample stands for (None = unknown)
    notes: list = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def exposure(self):
        """Each player's share of the field in % (CPT and FLEX rows separately for showdown)."""
        counts = np.bincount(self.rows.ravel(), minlength=len(self.players))
        return 100 * counts / max(len(self.rows), 1)


def synthetic_field(fp, fmt, habits, n_lineups, seed=2026):
    rng = np.random.default_rng(seed)
    own = fp["own"].to_numpy(float)
    arrays = _arrays(fp)
    _check_enough(fp, fmt, own)
    quota = _quotas(habits.shares(), n_lineups)
    w = own.copy()
    for rnd in range(IPF_ROUNDS):
        rows, short = _draw(arrays, w, fmt, quota, rng)
        if rnd == IPF_ROUNDS - 1:
            break
        exp = 100 * np.bincount(rows.ravel(), minlength=len(fp)) / len(rows)
        w = np.where(own > 0, w * (own / np.maximum(exp, 0.05)) ** 0.8, 0.0)
    f = FieldLineups(rows, fp, "synthetic")
    exp = f.exposure()
    big = own >= 1
    miss = float(np.mean(np.abs(exp[big] - own[big]))) if big.any() else 0.0
    f.info = {"lineups": len(rows), "habits_from": habits.sources, "habit_lineups": habits.lineups,
              "ownership_miss": round(miss, 2)}
    f.notes += habits.notes
    if short:
        f.notes.append(f"{short:,} of {n_lineups:,} field lineups couldn't be drawn in the field's rarest "
                       f"salary/stack shapes, so the field has {len(rows):,}.")
    return f


def _arrays(fp):
    teams, uniques = pd.factorize(pd.concat([fp["team"], fp["opp"]], ignore_index=True))
    n = len(fp)
    return {"salary": fp["salary"].to_numpy(np.int64), "team": teams[:n], "opp": teams[n:],
            "pos": fp["pos"].to_numpy(), "slot": fp["slot"].to_numpy(), "base": fp["base_id"].to_numpy(),
            "is_pc": fp["pos"].isin(PASS_CATCHERS).to_numpy(), "is_skill": fp["pos"].isin(SKILL).to_numpy()}


def _check_enough(fp, fmt, own):
    if fmt == rosters.SHOWDOWN:
        if ((fp["slot"] == "CPT") & (own > 0)).sum() < 1 or ((fp["slot"] == "FLEX") & (own > 0)).sum() < 6:
            raise FileProblem("Too few players have projected ownership to model a showdown field.")
        return
    for pos, k in CLASSIC_GROUPS:
        if ((fp["pos"] == pos) & (own > 0)).sum() < k:
            raise FileProblem(f"Too few {pos}s have projected ownership to model the field.")
    if (fp["pos"].isin(SKILL) & (own > 0)).sum() < 7:
        raise FileProblem("Too few RB/WR/TEs have projected ownership to model the field.")


def _quotas(shares, n):
    keys = sorted(shares)
    raw = np.array([shares[k] * n for k in keys])
    got = np.floor(raw).astype(int)
    extra = n - got.sum()
    if extra > 0:
        got[np.argsort(-(raw - got), kind="stable")[:extra]] += 1
    return dict(zip(keys, got))


def _pick(w, cols, counts, rng, allow=None):
    """Up to counts[i] picks in row i among columns `cols`, each with chance proportional to w
    (without replacement), only where `allow` (rows x cols) permits. Returns rows x k, -1 = none.
    (Exponential race: the smallest Exp(1)/w wins, the same as drawing in proportion to w.)"""
    m = len(counts)
    k = min(int(counts.max()) if m else 0, len(cols))
    if k <= 0:
        return np.full((m, 0), -1)
    with np.errstate(divide="ignore"):
        keys = rng.standard_exponential(size=(m, len(cols)), dtype=np.float32) / w[cols].astype(np.float32)[None, :]
    if allow is not None:
        keys[~allow] = np.inf
    if k == 1:
        top = keys.argmin(axis=1)[:, None]
    else:
        top = np.argpartition(keys, k - 1, axis=1)[:, :k]
        order = np.argsort(np.take_along_axis(keys, top, axis=1), axis=1)
        top = np.take_along_axis(top, order, axis=1)
    tk = np.take_along_axis(keys, top, axis=1)
    ok = (np.arange(k)[None, :] < counts[:, None]) & np.isfinite(tk)
    return np.where(ok, cols[top], -1)


def _window(a, cols, spent, lo, hi):
    """rows x cols: the player leaves $lo-$hi unspent after `spent`."""
    room = (rosters.SALARY_CAP - spent)[:, None]
    sal = a["salary"][cols][None, :]
    return (sal >= room - hi[:, None]) & (sal <= room - lo[:, None])


def _propose(a, w, fmt, target, rng):
    """One random lineup per target habit bin: players drawn in proportion to w, the stack shape
    aimed at the bin's (classic), and the last pick only among players that leave the bin's
    salary unspent. Lineups that don't come out legal are dropped. Returns lineups (QB / captain
    first) and their target bins."""
    m = len(target)
    n_cats = N_CATS[fmt]
    band, cat = target // n_cats, target % n_cats
    lo = SALARY_LEFT_EDGES[band]
    hi = np.where(band + 1 < len(SALARY_LEFT_EDGES), SALARY_LEFT_EDGES[np.minimum(band + 1, len(SALARY_LEFT_EDGES) - 1)] - 1,
                  rosters.SALARY_CAP)
    ones = np.ones(m, dtype=int)
    live = w > 0
    if fmt == rosters.SHOWDOWN:
        cpt = np.flatnonzero((a["slot"] == "CPT") & live)
        flex = np.flatnonzero((a["slot"] == "FLEX") & live)
        c = _pick(w, cpt, ones, rng)[:, 0]
        free = a["base"][flex][None, :] != a["base"][c][:, None]        # the captain can't be a FLEX too
        first = _pick(w, flex, 4 * ones, rng, free)
        free &= ~(flex[None, :, None] == first[:, None, :]).any(axis=2)
        spent = a["salary"][c] + np.where(first >= 0, a["salary"][first], 0).sum(axis=1)
        last = _pick(w, flex, ones, rng, free & _window(a, flex, spent, lo, hi))
        lu = np.concatenate([c[:, None], first, last], axis=1)
        ok = (lu >= 0).all(axis=1)
        lu = np.where(lu >= 0, lu, 0)
        ok &= (a["salary"][lu].sum(axis=1) <= rosters.SALARY_CAP) & (a["team"][lu] != a["team"][lu[:, :1]]).any(axis=1)
        return lu[ok], target[ok]

    n = len(w)
    taken = np.zeros((m, n), dtype=bool)
    rows = np.arange(m)

    def mark(p):
        r, j = np.nonzero(p >= 0)
        taken[r, p[r, j]] = True

    group = {g: np.flatnonzero((a["pos"] == g) & live) for g in ("QB", "RB", "WR", "TE", "DST")}
    qb = _pick(w, group["QB"], ones, rng)[:, 0]
    good = qb >= 0
    qb = np.where(good, qb, group["QB"][0] if len(group["QB"]) else 0)
    taken[rows, qb] = good
    pc = np.flatnonzero(a["is_pc"] & live)
    mark(_pick(w, pc, cat // 2, rng, a["team"][pc][None, :] == a["team"][qb][:, None]))
    skill = np.flatnonzero(a["is_skill"] & live)
    mark(_pick(w, skill, cat % 2, rng, (a["team"][skill][None, :] == a["opp"][qb][:, None]) & ~taken[:, skill]))
    for g, req in (("RB", 2), ("WR", 3), ("TE", 1)):
        idx = group[g]
        mark(_pick(w, idx, np.maximum(req - taken[:, idx].sum(axis=1), 0), rng, ~taken[:, idx]))
    mark(_pick(w, group["DST"], ones, rng))
    spent = taken @ a["salary"]
    flex_left = np.maximum(7 - taken[:, skill].sum(axis=1), 0)
    mark(_pick(w, skill, flex_left, rng, ~taken[:, skill] & _window(a, skill, spent, lo, hi)))

    count = lambda g: taken[:, group[g]].sum(axis=1)              # noqa: E731
    ok = good & (taken.sum(axis=1) == 9) & (count("QB") == 1) & (count("DST") == 1)
    ok &= (count("RB") >= 2) & (count("RB") <= 3) & (count("WR") >= 3) & (count("WR") <= 4)
    ok &= (count("TE") >= 1) & (count("TE") <= 2) & (taken @ a["salary"] <= rosters.SALARY_CAP)
    taken, qb = taken[ok], qb[ok]
    lu = np.nonzero(taken)[1].reshape(-1, 9)
    at = np.argmax(lu == qb[:, None], axis=1)                     # QB first
    r = np.arange(len(lu))
    lu[r, at], lu[:, 0] = lu[:, 0], qb
    return lu, target[ok]


def _draw(a, w, fmt, quota, rng):
    """Field lineups filling each habit bin's quota. Each proposal aims at a bin still short,
    chosen in proportion to how short it is."""
    need = dict(quota)
    got = []
    rate = 0.5                                                 # share of proposals used, updated as we go
    for _ in range(MAX_BATCHES):
        codes = np.array([c for c, v in need.items() if v > 0])
        if not len(codes):
            break
        short = np.array([need[c] for c in codes], dtype=float)
        size = int(min(BATCH, max(2_000, 1.3 * short.sum() / max(rate, 0.02))))
        target = rng.choice(codes, size=size, p=short / short.sum())
        lu, _ = _propose(a, w, fmt, target, rng)
        got_codes = shape_codes(fmt, a["salary"][lu], a["team"][lu], a["opp"][lu], a["is_pc"][lu], a["is_skill"][lu])
        used = 0
        for c in np.unique(got_codes):
            remaining = need.get(int(c), 0)
            if remaining > 0:
                take = np.flatnonzero(got_codes == c)[:remaining]
                got.append(lu[take])
                need[int(c)] = remaining - len(take)
                used += len(take)
        rate = used / size
    rows = np.concatenate(got) if got else np.empty((0, 6 if fmt == rosters.SHOWDOWN else 9), dtype=np.int64)
    if not len(rows):
        raise FileProblem("No field lineups could be drawn from the projected ownership (check the salaries).")
    rows = rows[rng.permutation(len(rows))]
    return rows, int(sum(max(v, 0) for v in need.values()))


def real_field(slate_id, contest_id, fp, fmt, sample, seed=2026, root=None):
    """A backtest field: a sample of the contest's real lineups (standings file). Hindsight."""
    fld = load_field(slate_id, contest_id, root)
    if fld.fmt() and fld.fmt() != fmt:
        raise FileProblem(f"Contest {contest_id} is {fld.fmt()} but this build is {fmt}.")
    texts = fld.entries["lineup"].to_numpy()
    if len(texts) > sample:
        texts = texts[np.random.default_rng(seed).choice(len(texts), sample, replace=False)]
    if fmt == rosters.SHOWDOWN:
        keys = list(zip(fp["name_key"], fp["slot"]))
    else:
        keys = list(fp["name_key"])
    counts = Counter(keys)
    lookup = {k: i for i, k in enumerate(keys) if counts[k] == 1}
    rows, skipped = [], 0
    for text in texts:
        got = _map_lineup(text, fmt, lookup)
        if got is None:
            skipped += 1
        else:
            rows.append(got)
    if not rows:
        raise FileProblem(f"None of contest {contest_id}'s standings lineups match this slate's players.")
    det = find_standings(slate_id, contest_id, root)
    f = FieldLineups(np.array(rows, dtype=np.int64), fp, "real", fld.n)
    f.info = {"lineups": len(rows), "standings": det.path.name, "sha256": sha256_file(det.path)}
    f.notes.append(f"Backtest field: {len(rows):,} of contest {contest_id}'s real lineups ({fld.n:,} entries) from "
                   f"{det.path.name}. That's hindsight, so this build is marked hindsight.")
    if skipped:
        f.notes.append(f"{skipped:,} sampled field lineups were blank or had a player not in the SaberSim export "
                       f"and were left out.")
    return f
