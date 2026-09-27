"""Head-to-head comparison of 2-6 builds on one slate and contest (SPEC 6.5, section 7)."""

from dataclasses import dataclass, field
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, mannwhitneyu

from . import builds, grade
from .io_utils import FileProblem

STATS_WARNING = "All lineups on one slate share one set of game results; these p-values are too generous."
LEANS_SHOWN = 8


@dataclass
class Comparison:
    info: grade.ContestInfo
    grades: list
    names: list                          # display name per build
    summary: pd.DataFrame
    exposure: pd.DataFrame               # player x build exposure, with final score and spread
    leans: dict                          # build name -> players it leaned into vs the others
    shared: pd.DataFrame                 # identical lineups between each pair of builds
    stats: pd.DataFrame
    warnings: list = field(default_factory=list)
    recorded: int = 0


def compare(slate_id, contest_id, keys, only_contest=False, include_hindsight=False, root=None, record=True):
    keys = list(dict.fromkeys(keys))
    meta = builds.load_meta(slate_id, root)
    warnings = []
    hindsight = [k for k in keys if meta.get(k, builds.DEFAULT)["hindsight"]]
    if hindsight and not include_hindsight:
        warnings.append("Left out because they're marked hindsight (settings added after the games): "
                        + ", ".join(meta[k]["name"] or k for k in hindsight))
        keys = [k for k in keys if k not in hindsight]
    elif hindsight:
        warnings.append("Hindsight builds are included and flagged. Don't use them to judge a method.")
    if not 2 <= len(keys) <= 6:
        raise FileProblem("Pick 2 to 6 builds to compare (hindsight builds don't count unless you include them).")
    refills = {k for k in keys if meta.get(k, builds.DEFAULT)["refill"]}
    if refills and len(refills) < len(keys):
        warnings.append("A refill is a new lineup pool built after the fact. It can be compared fairly with "
                        "other refills, but not with the original entries.")

    info, grades = grade.grade(slate_id, contest_id, keys, only_contest, root, save=False)
    if not info.prelock_proj:
        warnings.append(f"Projection averages come from the post-game SaberSim export ({info.proj_file}) because "
                        f"the slate has no pre-lock export, so they may include news from after lock.")
    labels = {k: lbl for k, lbl, _ in grade.available_sets(slate_id, root)}
    names = [builds.label_for(g.key, g.label if g.key not in labels else labels[g.key], meta) for g in grades]
    names = _unique(names)
    graded = [(n, g) for n, g in zip(names, grades) if not g.lineups.empty]
    for n, g in zip(names, grades):
        if g.lineups.empty:
            warnings.append(f"{n} has no gradable lineups: " + " ".join(g.problems))

    summary = pd.DataFrame([{**grade.summary_row(g, info), "Build": n,
                             "Method": meta.get(g.key, builds.DEFAULT)["method"]} for n, g in zip(names, grades)])
    comp = Comparison(info, grades, names, summary, _exposure(graded), _leans(graded), _shared(graded),
                      _stats(graded), warnings)
    if record:
        comp.recorded = builds.record(slate_id, info, grades, meta, root)
    return comp


def _unique(names):
    seen, out = {}, []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def _exposure(graded):
    frames = []
    for name, g in graded:
        e = g.exposure[["Pos", "Team", "Player", "Final", "Actual own %", "Exposure %"]]
        frames.append(e.rename(columns={"Exposure %": name}).set_index(["Pos", "Team", "Player"]))
    if not frames:
        return pd.DataFrame()
    base = pd.concat([f[["Final", "Actual own %"]] for f in frames]).groupby(level=[0, 1, 2]).first()
    table = base.join(pd.concat([f.drop(columns=["Final", "Actual own %"]) for f in frames], axis=1)).fillna(
        {name: 0.0 for name, _ in graded})
    exp_cols = [name for name, _ in graded]
    table["Spread"] = table[exp_cols].max(axis=1) - table[exp_cols].min(axis=1)
    return table.reset_index().sort_values(["Spread", "Final"], ascending=False).reset_index(drop=True)


def _leans(graded):
    """For each build, the players it used most compared with the other builds' average."""
    table = _exposure(graded)
    out = {}
    for name, _ in graded:
        others = [n for n, _ in graded if n != name]
        t = table[["Player", "Team", "Final", "Actual own %", name]].copy()
        t["Others avg %"] = table[others].mean(axis=1).round(1)
        t["Lean"] = (t[name] - t["Others avg %"]).round(1)
        t = t.rename(columns={name: "This build %"})
        out[name] = t[t["Lean"] > 0].sort_values("Lean", ascending=False).head(LEANS_SHOWN).reset_index(drop=True)
    return out


def _shared(graded):
    names = [n for n, _ in graded]
    ids = {n: set(g.lineups["identity"]) for n, g in graded}
    return pd.DataFrame([[len(ids[a] & ids[b]) for b in names] for a in names], index=names, columns=names)


def _stats(graded):
    rows = []
    for (a, ga), (b, gb) in combinations(graded, 2):
        sa, sb = ga.lineups["score"].to_numpy(), gb.lineups["score"].to_numpy()
        ta, tb = int((ga.lineups["share"] <= 0.05 + 1e-12).sum()), int((gb.lineups["share"] <= 0.05 + 1e-12).sum())
        mw = mannwhitneyu(sa, sb, alternative="two-sided").pvalue if len(sa) and len(sb) else np.nan
        fe = fisher_exact([[ta, len(sa) - ta], [tb, len(sb) - tb]]).pvalue
        rows.append({"Build A": a, "Build B": b, "Median A": float(np.median(sa)), "Median B": float(np.median(sb)),
                     "Mann-Whitney p (scores)": round(float(mw), 4),
                     "Top 5% A": f"{ta}/{len(sa)}", "Top 5% B": f"{tb}/{len(sb)}",
                     "Fisher p (top 5%)": round(float(fe), 4)})
    return pd.DataFrame(rows)


def to_text(c):
    lines = [c.info.graded_against(), ""]
    lines += [f"! {w}" for w in c.warnings]
    lines += ["", c.summary.to_string(index=False), "", "Leaned into (vs the other builds' average):"]
    for name, t in c.leans.items():
        lines.append(f"  {name}: " + (", ".join(f"{r.Player} +{r.Lean} (scored {r.Final})" for r in t.itertuples())
                                     or "nothing stands out"))
    lines += ["", "Identical lineups shared between builds:", c.shared.to_string(), "",
              "Statistics:", c.stats.to_string(index=False) if not c.stats.empty else "(none)", STATS_WARNING]
    return "\n".join(lines)
