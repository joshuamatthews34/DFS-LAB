"""Ownership check (SPEC 5.4): how much total ownership did past top-1% lineups carry?

For every contest in every slate with a standings file, the top-1% lineups' total actual
ownership (%Drafted) is added up, along with how many sub-5% players they used. A new build's
projected ownership can then be compared with that range. Past results only; the build itself
never reads them.
"""

import pandas as pd

from . import field, grade, rosters, slate
from .importers import standings as standings_imp
from .names import normalize_name

LOW_OWN = 5.0


def contest_top1(slate_id, contest_id, root=None):
    fld = field.load_field(slate_id, contest_id, root)
    fmt = fld.fmt()
    pl = fld.players
    if fmt == rosters.SHOWDOWN:
        pct = pl.groupby(["name_key", "roster_position"])["pct_drafted"].sum().to_dict()
    else:
        pct = pl.groupby("name_key")["pct_drafted"].sum().to_dict()
    totals, lows = [], []
    for text in fld.top_lineups(0.01):
        pairs = standings_imp.parse_lineup(text)
        if not pairs:
            continue
        owns = []
        for tag, name in pairs:
            key = normalize_name(name)
            owns.append(pct.get((key, "CPT" if tag == "CPT" else "FLEX"), 0.0) if fmt == rosters.SHOWDOWN
                        else pct.get(key, 0.0))
        totals.append(sum(owns))
        lows.append(sum(o < LOW_OWN for o in owns))
    if not totals:
        return None
    return {"Slate": slate_id, "Contest": contest_id, "Format": fmt, "Top-1% lineups": len(totals),
            "Avg total own %": round(sum(totals) / len(totals), 1),
            "Avg sub-5% players": round(sum(lows) / len(lows), 2)}


def history(fmt=None, root=None):
    """One row per past contest with a standings file."""
    rows = []
    for sid in slate.list_slates(root):
        try:
            contests = grade.list_contests(sid, root)
        except Exception:
            continue
        for cid, _ in contests:
            try:
                row = contest_top1(sid, cid, root)
            except Exception:
                continue
            if row and (fmt is None or row["Format"] == fmt):
                rows.append(row)
    return pd.DataFrame(rows)


def build_line(build_result):
    """The build's own numbers, projected (the only ownership known before lock)."""
    pool = build_result.pool
    totals = [pool.loc[list(lu), "own"].sum() for lu in build_result.lineups]
    lows = [(pool.loc[list(lu), "own"] < LOW_OWN).sum() for lu in build_result.lineups]
    return {"Avg total own %": round(float(sum(totals) / len(totals)), 1) if totals else None,
            "Avg sub-5% players": round(float(sum(lows) / len(lows)), 2) if lows else None}


def summary_text(build_result, hist):
    mine = build_line(build_result)
    if hist.empty:
        return (f"This build averages {mine['Avg total own %']}% total projected ownership. No past contests "
                f"of this format with standings to compare with yet.")
    lo, hi = hist["Avg total own %"].min(), hist["Avg total own %"].max()
    avg = hist["Avg total own %"].mean()
    return (f"This build averages {mine['Avg total own %']}% total projected ownership and "
            f"{mine['Avg sub-5% players']} sub-5% players per lineup. Past top-1% lineups averaged {avg:.1f}% "
            f"(range {lo:.1f}-{hi:.1f}% over {len(hist)} contest(s)) with {hist['Avg sub-5% players'].mean():.2f} "
            f"sub-5% players.")
