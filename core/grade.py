"""Grade lineup sets against a contest's real field (SPEC milestone M2: sections 6.1, 6.2, 6.4).

Scores come from the newest post-game SaberSim export (`Actual`), which M1 checked
against DraftKings' FPTS. A captain scores 1.5x the player's FLEX `Actual`.
Each lineup is ranked against the real field on its own; "top X%" means the share
of the field scoring strictly higher is X% or less.
"""

import json
import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import detect, rosters, slate
from .field import load_field, to_cents
from .importers import standings as standings_imp
from .io_utils import FileProblem
from .names import normalize_name
from .optimal import perfect_lineup

BUCKETS = (0.001, 0.01, 0.05, 0.10, 0.20)
BUCKET_LABELS = {0.001: "top 0.1%", 0.01: "top 1%", 0.05: "top 5%", 0.10: "top 10%", 0.20: "top 20%"}
OFFICIAL_TOLERANCE = 0.011   # DraftKings rounds captain half-hundredths


# ---------------------------------------------------------------- lineup sets

@dataclass
class LineupSet:
    key: str
    label: str
    fmt: str
    lineups: list                      # DFS IDs in slot order
    entry_ids: list                    # Entry ID per lineup, or None
    contest_ids: list                  # contest per lineup, or None
    fees: list                         # entry fee in cents per lineup, or None

    def in_contest(self, contest_id):
        keep = [i for i, c in enumerate(self.contest_ids) if c == str(contest_id)]
        return LineupSet(self.key, f"{self.label}, only contest {contest_id}", self.fmt,
                         *[[col[i] for i in keep] for col in (self.lineups, self.entry_ids, self.contest_ids,
                                                              self.fees)])


def lineup_sets(parsed):
    sets = []
    entry_files = parsed[detect.DK_ENTRIES]
    if len(entry_files) > 1:
        newest = {}
        for _, _, d in entry_files:            # oldest file first, so the newest wins
            for e in d.entries:
                newest[e.entry_id] = e
        es = list(newest.values())
        sets.append(LineupSet("entries:all", "All my entries (every entries file, one per Entry ID)",
                              entry_files[-1][2].fmt, [e.player_ids for e in es], [e.entry_id for e in es],
                              [e.contest_id for e in es], [e.fee_cents for e in es]))
    for fr, _, d in entry_files:
        sets.append(LineupSet(f"entries:{fr.name}", f"{fr.name} (entries file)", d.fmt,
                              [e.player_ids for e in d.entries], [e.entry_id for e in d.entries],
                              [e.contest_id for e in d.entries], [e.fee_cents for e in d.entries]))
    for fr, _, d in parsed[detect.LINEUPS]:
        n = len(d.lineups)
        sets.append(LineupSet(f"lineups:{fr.name}", f"{fr.name} (lineup file)", d.fmt, d.lineups,
                              [None] * n, [None] * n, [None] * n))
    return sets


ENTERED_KEY = "entered:standings"
ENTERED_LABEL = "My entered lineups (final, as DraftKings scored them in the standings)"


def available_sets(slate_id, root=None):
    """(key, label, lineup count or None) for every lineup set in the slate."""
    parsed = slate.load_parsed(slate_id, root)
    out = []
    if parsed[detect.DK_ENTRIES] and list_contests(slate_id, root):
        out.append((ENTERED_KEY, ENTERED_LABEL, None))
    out += [(s.key, s.label, len(s.lineups)) for s in lineup_sets(parsed)]
    return out


def entered_set(slate_id, parsed, book, root=None):
    """Your entries' final lineups, read from every standings file in the slate.

    Late swaps are already applied, so this is exactly what DraftKings scored.
    Player names are mapped back to DFS IDs through the SaberSim export.
    """
    mine = {}
    for _, _, d in parsed[detect.DK_ENTRIES]:
        for e in d.entries:
            mine[e.entry_id] = e
    p = book.players
    slot_col = p["roster_slot"].where(p["roster_slot"].notna(), "")
    keys = list(zip(p["name_key"], slot_col))
    counts = Counter(keys)
    id_of = {k: i for k, i in zip(keys, p["dfs_id"]) if counts[k] == 1}
    ambiguous = {k[0] for k, c in counts.items() if c > 1}

    s = LineupSet(ENTERED_KEY, ENTERED_LABEL, book.fmt, [], [], [], [])
    problems = []
    for contest_id, _ in list_contests(slate_id, root):
        fld = load_field(slate_id, contest_id, root)
        rows = fld.entries[fld.entries["entry_id"].isin(mine.keys())]
        for entry_id, text in zip(rows["entry_id"], rows["lineup"]):
            pairs = standings_imp.parse_lineup(text)
            if not pairs:
                problems.append(f"Entry {entry_id} in contest {contest_id} has no lineup in the standings.")
                continue
            if book.fmt == rosters.SHOWDOWN:
                wanted = [(normalize_name(name), "CPT" if tag == "CPT" else "FLEX") for tag, name in pairs]
                wanted.sort(key=lambda k: k[1] != "CPT")
            else:
                wanted = [(normalize_name(name), "") for _, name in pairs]
            ids = [id_of.get(k) for k in wanted]
            if None in ids:
                bad = [k[0] for k, i in zip(wanted, ids) if i is None]
                why = "matches more than one SaberSim player" if set(bad) & ambiguous else "isn't in the SaberSim export"
                problems.append(f"Entry {entry_id}: {', '.join(bad)} {why}, so it wasn't graded.")
                continue
            e = mine[entry_id]
            s.lineups.append(ids)
            s.entry_ids.append(entry_id)
            s.contest_ids.append(contest_id)
            s.fees.append(e.fee_cents if e.contest_id == contest_id else None)
    return s, problems


def contest_names(parsed):
    names, fees = {}, {}
    for _, _, d in parsed[detect.DK_ENTRIES]:
        for e in d.entries:
            names.setdefault(e.contest_id, e.contest_name)
            fees.setdefault(e.contest_id, Counter())[e.fee_cents] += 1
    return names, {cid: c.most_common(1)[0][0] for cid, c in fees.items()}


def list_contests(slate_id, root=None):
    """Contest IDs that have a standings file in the slate, with names when an entries file has them."""
    parsed = slate.load_parsed(slate_id, root, skip=(detect.STANDINGS, detect.SABERSIM, detect.LINEUPS,
                                                     detect.PAYOUTS, detect.WARROOM))
    names, _ = contest_names(parsed)
    out = []
    for path in slate.raw_files(slate_id, root):
        det = detect.detect(path)
        if det.kind == detect.STANDINGS and det.contest_id and det.contest_id not in [c for c, _ in out]:
            out.append((det.contest_id, names.get(det.contest_id, "")))
    return out


# ---------------------------------------------------------------- players

@dataclass
class PlayerBook:
    """Every DFS ID on the slate with what grading needs. Indexed by dfs_id."""
    fmt: str
    players: pd.DataFrame
    post_file: str
    pre_file: str
    from_standings: list = field(default_factory=list)


def build_book(parsed, fld):
    exports = parsed[detect.SABERSIM]
    post = [x for x in exports if x[2].has_actuals]
    pre = [x for x in exports if not x[2].has_actuals]
    if not post:
        raise FileProblem("There's no post-game SaberSim export (with Actual scores) in this slate, so "
                          "lineups can't be scored. Import it first.")
    post_fr, _, post_data = post[-1]
    df = post_data.players.copy()
    # A captain row points at the same player's FLEX row ("base") and scores 1.5x its Actual.
    flex_of = {(k, t): i for k, t, i, s in zip(df.name_key, df.team, df.dfs_id, df.roster_slot) if s == "FLEX"}
    base = [flex_of.get((k, t)) if s == "CPT" else i
            for k, t, i, s in zip(df.name_key, df.team, df.dfs_id, df.roster_slot)]
    if any(b is None for b in base):
        raise FileProblem("Some captain rows in the SaberSim export have no matching FLEX row.")
    df["base_id"] = pd.Series(base, index=df.index, dtype="int64")
    df["mult"] = np.where(df["roster_slot"] == "CPT", 1.5, 1.0)
    df = df.set_index("dfs_id", drop=False)

    base_actual = df["base_id"].map(df["actual"])
    fallback = []
    if base_actual.isna().any():
        dk = fld.players[fld.players["roster_position"] != "CPT"].drop_duplicates("name_key")
        dk = dk.set_index("name_key")["fpts"]
        for pid in df.index[base_actual.isna()]:
            key = df.at[pid, "name_key"]
            if key in dk.index:
                base_actual[pid] = dk[key]
                fallback.append(df.at[pid, "name"])
    df["base_actual"] = base_actual
    df["points"] = df["base_actual"] * df["mult"]

    proj_src = pre[-1][2].players.set_index("dfs_id") if pre else df
    df["proj"] = df["base_id"].map(proj_src["my_proj"]).fillna(df["base_id"].map(df["my_proj"]))
    df["own_proj"] = df["dfs_id"].map(proj_src["my_own"]).fillna(df["my_own"])

    # Actual ownership (%Drafted). A player nobody drafted isn't listed, so 0%.
    own = fld.players
    if post_data.fmt == rosters.SHOWDOWN:
        pct = own.groupby(["name_key", "roster_position"])["pct_drafted"].sum()
        df["own_actual"] = [float(pct.get((k, s), 0.0)) for k, s in zip(df.name_key, df.roster_slot)]
    else:
        pct = own.groupby("name_key")["pct_drafted"].sum()
        df["own_actual"] = df["name_key"].map(pct).fillna(0.0)
    return PlayerBook(post_data.fmt, df, post_fr.name, pre[-1][0].name if pre else post_fr.name,
                      sorted(set(fallback)))


# ---------------------------------------------------------------- contest

@dataclass
class ContestInfo:
    contest_id: str
    name: str
    fmt: str
    n: int
    top_score: float
    lines: dict                        # share -> score needed
    cash_line: float = None
    last_paid_rank: int = None
    fee_cents: int = None
    perfect: dict = None
    has_payouts: bool = False

    def graded_against(self):
        parts = [f"Graded against {self.name or 'contest ' + self.contest_id}", f"{self.n:,} entries",
                 f"winning score {_fmt(self.top_score)}", f"top 1% {_fmt(self.lines.get(0.01))}"]
        if self.cash_line is not None:
            parts.append(f"cash line {_fmt(self.cash_line)}")
        parts.append(f"perfect lineup {_fmt(self.perfect['score']) if self.perfect else 'not available'}")
        return ", ".join(parts) + "."


def _fmt(x):
    """152.1 -> '152.1', 146.33 -> '146.33', 150.0 -> '150.0'."""
    if x is None:
        return "n/a"
    return f"{x:,.2f}".rstrip("0") if x % 1 else f"{x:,.1f}"


def _payout_table(parsed, contest_id):
    for _, det, d in reversed(parsed[detect.PAYOUTS]):
        if det.contest_id == str(contest_id):
            last = int(d["rank_to"].max())
            prizes = np.zeros(last, dtype=np.int64)
            for lo, hi, cents in d.itertuples(index=False):
                prizes[lo - 1:hi] = cents
            return prizes
    return None


def _split_prize(prizes, rank, tied):
    """Average prize over the tied ranks rank..rank+tied-1 (DraftKings splits ties)."""
    if prizes is None:
        return None
    cum = np.concatenate([[0], np.cumsum(prizes)])
    last = len(prizes)
    a, b = min(rank - 1, last), min(rank - 1 + tied, last)
    return (cum[b] - cum[a]) / tied


# ---------------------------------------------------------------- grading

@dataclass
class Grade:
    key: str
    label: str
    lineups: pd.DataFrame
    exposure: pd.DataFrame
    summary: dict
    problems: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def grade(slate_id, contest_id, set_keys=None, only_contest=False, root=None, save=True):
    """Grade the chosen lineup sets (all if None) against one contest. Returns (ContestInfo, [Grade])."""
    contest_id = str(contest_id)
    parsed = slate.load_parsed(slate_id, root)
    fld = load_field(slate_id, contest_id, root)
    book = build_book(parsed, fld)
    fmt = fld.fmt() or book.fmt
    names, fees = contest_names(parsed)
    prizes = _payout_table(parsed, contest_id)

    pool = book.players.dropna(subset=["points"]).rename(columns={"roster_slot": "slot"})
    info = ContestInfo(contest_id, names.get(contest_id, ""), fmt, fld.n, fld.top_score,
                       {s: fld.line(s) for s in BUCKETS}, fee_cents=fees.get(contest_id),
                       perfect=perfect_lineup(pool, book.fmt), has_payouts=prizes is not None)
    if prizes is not None:
        info.last_paid_rank = int(np.nonzero(prizes)[0].max()) + 1
        info.cash_line = fld.score_at_rank(info.last_paid_rank)

    top1 = _top_share_counts(fld, 0.01)
    tags = _warroom_tags(parsed)
    field_points = dict(zip(fld.entries["entry_id"], fld.entries["points"]))

    all_sets = {s.key: s for s in lineup_sets(parsed)}
    entered_problems = []
    keys = set_keys or ([ENTERED_KEY] if parsed[detect.DK_ENTRIES] else []) + list(all_sets)
    if ENTERED_KEY in keys:
        all_sets[ENTERED_KEY], entered_problems = entered_set(slate_id, parsed, book, root)
    unknown = [k for k in keys if k not in all_sets]
    if unknown:
        raise FileProblem(f"No lineup set called {', '.join(unknown)} in slate {slate_id}.")

    grades = []
    for key in keys:
        s = all_sets[key]
        if only_contest and (key.startswith("entries:") or key == ENTERED_KEY):
            s = s.in_contest(contest_id)
        if s.fmt != book.fmt or (fmt and s.fmt != fmt):
            g = Grade(s.key, s.label, pd.DataFrame(), pd.DataFrame(), {})
            g.problems.append(f"{s.label} is {s.fmt} but contest {contest_id} is {fmt}; it can't be graded here.")
            grades.append(g)
            continue
        g = _grade_set(s, book, fld, info, prizes, field_points, top1, tags)
        if key == ENTERED_KEY:
            g.problems[:0] = entered_problems
        if book.from_standings:
            g.warnings.append("SaberSim had no Actual for these players, so DraftKings' FPTS was used: "
                              + ", ".join(book.from_standings))
        grades.append(g)
    if save:
        _save(slate_id, root, info, grades)
    return info, grades


def _grade_set(s, book, fld, info, prizes, field_points, top1, tags):
    p = book.players
    problems, rows = [], []
    for i, ids in enumerate(s.lineups):
        missing = [pid for pid in ids if pid not in p.index]
        if missing:
            problems.append(f"Lineup {i + 1}: DFS ID(s) {', '.join(map(str, missing))} aren't in the SaberSim "
                            f"export, so it wasn't graded.")
            continue
        pts = p.loc[ids, "points"]
        if pts.isna().any():
            names = ", ".join(p.loc[ids][pts.isna()]["name"])
            problems.append(f"Lineup {i + 1}: no score for {names}, so it wasn't graded.")
            continue
        rows.append({"lineup": i + 1, "entry_id": s.entry_ids[i], "contest_id": s.contest_ids[i],
                     "fee": s.fees[i], "ids": ids, "score": round(float(pts.sum()), 2),
                     "salary": int(p.loc[ids, "salary"].sum()),
                     "own": float(p.loc[ids, "own_actual"].sum())})
    lu = pd.DataFrame(rows)
    g = Grade(s.key, s.label, lu, pd.DataFrame(), {}, problems)
    if lu.empty:
        g.problems.append(f"{s.label}: no lineups could be graded.")
        return g

    scores = lu["score"].to_numpy()
    higher = fld.higher(scores)
    equal = fld.equal(scores)
    # An entry counts as "official" (already in the field) only if DraftKings scored the same lineup.
    in_field = []
    for e, c, sc in zip(lu["entry_id"], lu["contest_id"], lu["score"]):
        official = c == info.contest_id and e in field_points
        if official and abs(field_points[e] - sc) > OFFICIAL_TOLERANCE:
            g.problems.append(f"Entry {e}: DraftKings scored it {field_points[e]} but DFS Lab gets {sc}. "
                              f"The entries file may be from before a late swap; graded as a separate lineup.")
            official = False
        in_field.append(official)
    in_field = np.array(in_field, dtype=bool)
    lu["rank"] = higher + 1
    lu["share"] = higher / fld.n
    lu["official"] = in_field
    tied = equal + np.where(in_field, 0, 1)
    if prizes is not None:
        lu["prize"] = [_split_prize(prizes, r, t) / 100 for r, t in zip(lu["rank"], tied)]
    lu["fee_paid"] = [(f if c == info.contest_id and pd.notna(f) else info.fee_cents)
                      for f, c in zip(lu["fee"], lu["contest_id"])]
    lu["salary_left"] = rosters.SALARY_CAP - lu["salary"]
    lu["stack"] = [_stack_tag(ids, p, book.fmt) for ids in lu.ids]
    lu["players"] = [" / ".join(("CPT " if p.at[i, "mult"] > 1 else "") + p.at[i, "name"] for i in ids)
                     for ids in lu.ids]

    g.summary = _summary(lu, p, book.fmt, prizes is not None)
    g.exposure = _exposure(lu, p, book.fmt, top1, tags)
    g.lineups = lu
    return g


def _summary(lu, p, fmt, has_payouts):
    n = len(lu)
    best = lu.loc[lu["score"].idxmax()]
    out = {
        "lineups": n,
        "avg_score": round(float(lu["score"].mean()), 2),
        "median_score": round(float(lu["score"].median()), 2),
        "best_score": float(best["score"]),
        "best_rank": int(lu["rank"].min()),
        "best_share": float(lu["share"].min()),
        "median_share": float(lu["share"].median()),
        "counts": {BUCKET_LABELS[b]: int((lu["share"] <= b + 1e-12).sum()) for b in BUCKETS},
        "avg_salary_left": round(float(lu["salary_left"].mean()), 0),
        "avg_total_own": round(float(lu["own"].mean()), 1),
        "avg_shared": _avg_shared(lu.ids, p, fmt),
        "duplicates": n - len({_identity(ids, p, fmt) for ids in lu.ids}),
        "official_entries": int(lu["official"].sum()),
    }
    if has_payouts:
        won = float(lu["prize"].sum())
        out["cashed"] = int((lu["prize"] > 0).sum())
        out["won"] = round(won, 2)
        if lu["fee_paid"].notna().all():
            fees = float(lu["fee_paid"].sum()) / 100
            out["fees"] = round(fees, 2)
            out["roi"] = round((won - fees) / fees, 4) if fees else None
        else:
            out["fees"] = out["roi"] = None
    return out


def _identity(ids, p, fmt):
    if fmt == rosters.SHOWDOWN:
        return (int(p.at[ids[0], "base_id"]), frozenset(int(p.at[i, "base_id"]) for i in ids[1:]))
    return frozenset(ids)


def _avg_shared(lineups, p, fmt):
    """Average number of players any two lineups have in common."""
    if len(lineups) < 2:
        return None
    bases = [[int(p.at[i, "base_id"]) for i in ids] for ids in lineups]
    cols = {b: j for j, b in enumerate(sorted({b for row in bases for b in row}))}
    m = np.zeros((len(bases), len(cols)), dtype=np.float32)
    for r, row in enumerate(bases):
        m[r, [cols[b] for b in row]] = 1
    inter = m @ m.T
    k = len(bases)
    return round(float((inter.sum() - np.trace(inter)) / (k * (k - 1))), 2)


def _stack_tag(ids, p, fmt):
    rows = p.loc[ids]
    if fmt == rosters.SHOWDOWN:
        cpt = rows.iloc[0]
        same = int((rows["team"] == cpt["team"]).sum())
        return f"{cpt['pos']} CPT {same}-{len(rows) - same}"
    qbs = rows[rows["pos"] == "QB"]
    if qbs.empty:
        return "no QB"
    qb = qbs.iloc[0]
    own = int(((rows["team"] == qb["team"]) & rows["pos"].isin(["WR", "TE"])).sum())
    back = int(((rows["team"] == qb["opp"]) & rows["pos"].isin(["RB", "WR", "TE"])).sum())
    return f"QB+{own}|{back}"


def _top_share_counts(fld, share):
    """How many of the field's top-`share` lineups had each player (by name key)."""
    counts = Counter()
    top = fld.top_lineups(share)
    for text in top:
        pairs = standings_imp.parse_lineup(text)
        if pairs:
            counts.update({normalize_name(name) for _, name in pairs})
    return {"n": len(top), "counts": counts}


def _warroom_tags(parsed):
    tags = {}
    for _, _, d in parsed[detect.WARROOM]:           # newest file wins
        tags.update(dict(zip(d["name_key"], d["tag"])))
    return tags


def _exposure(lu, p, fmt, top1, tags):
    n = len(lu)
    counts, cpt = Counter(), Counter()
    for ids in lu.ids:
        for i in ids:
            base = int(p.at[i, "base_id"])
            counts[base] += 1
            if p.at[i, "mult"] > 1:
                cpt[base] += 1
    rows = []
    for base, c in counts.items():
        b = p.loc[base]
        rows_of_player = p[p["base_id"] == base]
        exp = 100 * c / n
        own = float(rows_of_player["own_actual"].sum())
        row = {"Pos": b["pos"], "Team": b["team"], "Player": b["name"], "Salary": int(b["salary"]),
               "Proj": b["proj"], "Final": b["base_actual"], "Count": c, "Exposure %": round(exp, 1)}
        if fmt == rosters.SHOWDOWN:
            row["CPT"] = cpt[base]
            row["FLEX"] = c - cpt[base]
        row.update({"Proj own %": round(float(rows_of_player["own_proj"].sum()), 1),
                    "Actual own %": round(own, 1), "Leverage": round(exp - own, 1),
                    "War Room": tags.get(b["name_key"], ""),
                    "Top-1% lineups": top1["counts"].get(b["name_key"], 0),
                    "Top-1% share %": round(100 * top1["counts"].get(b["name_key"], 0) / top1["n"], 1)
                    if top1["n"] else None})
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["Count", "Final"], ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------- output

def lineup_table(g, has_payouts):
    """The lineup viewer table (SPEC 6.4)."""
    if g.lineups.empty:
        return pd.DataFrame()
    lu = g.lineups
    t = pd.DataFrame({
        "#": lu["lineup"], "Entry ID": lu["entry_id"], "Score": lu["score"], "Rank": lu["rank"],
        "Top %": (100 * lu["share"]).round(2), "Stack": lu["stack"], "Salary left": lu["salary_left"],
        "Total own %": lu["own"].round(1), "Players": lu["players"],
    })
    if has_payouts:
        t.insert(5, "Prize $", lu["prize"].round(2))
    return t.sort_values("Score", ascending=False).reset_index(drop=True)


def summary_row(g, info):
    s = g.summary
    if not s:
        return {"Build": g.label}
    row = {"Build": g.label, "Lineups": s["lineups"], "Avg": s["avg_score"], "Median": s["median_score"],
           "Best": s["best_score"], "Best rank": s["best_rank"], "Best top %": round(100 * s["best_share"], 2),
           "Median top %": round(100 * s["median_share"], 1),
           **{k.replace("top ", "Top "): v for k, v in s["counts"].items()}}
    if info.has_payouts:
        row.update({"Cashed": s["cashed"], "Won $": s["won"], "Fees $": s["fees"],
                    "ROI %": None if s["roi"] is None else round(100 * s["roi"], 1)})
    row.update({"Avg salary left": s["avg_salary_left"], "Avg total own %": s["avg_total_own"],
                "Avg shared": s["avg_shared"], "Duplicates": s["duplicates"]})
    return row


def to_text(info, grades):
    lines = [info.graded_against(), ""]
    if info.perfect:
        lines.append("Perfect lineup: " + " / ".join(info.perfect["players"])
                     + f" = {info.perfect['score']} (${info.perfect['salary']:,})")
    for g in grades:
        lines += ["", f"== {g.label}"]
        s = g.summary
        if s:
            lines.append(f"{s['lineups']} lineup{'s' if s['lineups'] != 1 else ''}: avg {s['avg_score']}, "
                         f"median {s['median_score']}, "
                         f"best {s['best_score']} (rank {s['best_rank']:,}, top {100 * s['best_share']:.2f}%), "
                         f"median finish top {100 * s['median_share']:.1f}%")
            lines.append("Counts: " + ", ".join(f"{v} in {k}" for k, v in s["counts"].items()))
            if info.has_payouts:
                roi = "not available (entry fee unknown)" if s["roi"] is None else f"{100 * s['roi']:.1f}%"
                fees = "n/a" if s["fees"] is None else f"${s['fees']:,.2f}"
                lines.append(f"Cashed {s['cashed']}, won ${s['won']:,.2f}, fees {fees}, ROI {roi}")
            else:
                lines.append("Cashed / won / ROI: not available (no payout file for this contest)")
            lines.append(f"Avg salary left ${s['avg_salary_left']:,.0f}, avg total ownership {s['avg_total_own']}%, "
                         f"avg players shared {'n/a' if s['avg_shared'] is None else s['avg_shared']}, "
                         f"duplicates {s['duplicates']}")
        lines += [f"  ! {x}" for x in g.problems] + [f"  * {x}" for x in g.warnings]
    return "\n".join(lines)


def _slug(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")[:80]


def _save(slate_id, root, info, grades):
    out = slate.slate_dir(slate_id, root) / "results" / "grades" / info.contest_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "grade_report.txt").write_text(to_text(info, grades) + "\n")
    summary = {"contest": {k: v for k, v in info.__dict__.items() if k != "lines"} |
               {"lines": {BUCKET_LABELS[k]: v for k, v in info.lines.items()},
                "graded_against": info.graded_against()},
               "builds": [{"key": g.key, "label": g.label, "summary": g.summary, "problems": g.problems,
                           "warnings": g.warnings} for g in grades]}
    (out / "grade_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    for g in grades:
        if not g.lineups.empty:
            lineup_table(g, info.has_payouts).to_csv(out / f"{_slug(g.key)}.lineups.csv", index=False)
            g.exposure.to_csv(out / f"{_slug(g.key)}.exposure.csv", index=False)
