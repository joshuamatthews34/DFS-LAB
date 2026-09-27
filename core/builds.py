"""Build labels and the season record (SPEC 6.5, section 7).

A "build" is a lineup set with a name and a method (e.g. "SaberSim Unique Rank 3",
method "SaberSim UR3"). Flags:
  refill    - a past slate rebuilt later in SaberSim; comparable only with other refills
  hindsight - has settings added after games (e.g. hand-set minimums); left out of comparisons
Labels live in slates/<slate>/builds/builds.json.
"""

import json
from datetime import datetime

import pandas as pd

from . import db, slate

DEFAULT = {"name": "", "method": "", "refill": False, "hindsight": False, "notes": ""}


def _path(slate_id, root=None):
    return slate.slate_dir(slate_id, root) / "builds" / "builds.json"


def load_meta(slate_id, root=None):
    path = _path(slate_id, root)
    data = json.loads(path.read_text()) if path.exists() else {}
    return {k: {**DEFAULT, **v} for k, v in data.items()}


def save_meta(slate_id, meta, root=None):
    path = _path(slate_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: {f: v.get(f, DEFAULT[f]) for f in DEFAULT} for k, v in meta.items()}
    path.write_text(json.dumps(clean, indent=2))


def label_for(key, default_label, meta):
    m = meta.get(key, DEFAULT)
    name = m["name"] or default_label
    flags = [f for f in ("refill", "hindsight") if m[f]]
    return name + (f" [{', '.join(flags)}]" if flags else "")


# ---------------------------------------------------------------- season record

def record(slate_id, info, grades, meta, root=None):
    """Save each named, non-hindsight build's result on this slate/contest (replacing older ones)."""
    rows = []
    for g in grades:
        m = meta.get(g.key, DEFAULT)
        if not m["method"] or m["hindsight"] or not g.summary:
            continue
        s = g.summary
        rows.append((slate_id, info.contest_id, g.key, m["method"], m["name"] or g.label, int(m["refill"]),
                     s["lineups"], s["counts"]["top 1%"], s["counts"]["top 5%"],
                     s.get("cashed"), s.get("won"), s.get("fees"), datetime.now().isoformat(timespec="seconds")))
    conn = db.connect(slate.db_path(root))
    try:
        with conn:
            conn.executemany("INSERT OR REPLACE INTO season_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    finally:
        conn.close()
    return len(rows)


def season_rows(root=None):
    conn = db.connect(slate.db_path(root))
    try:
        return pd.read_sql_query("SELECT * FROM season_results ORDER BY slate_id, contest_id, method", conn)
    finally:
        conn.close()


def season_table(root=None):
    """One row per method across every recorded slate. Refills are kept apart from originals."""
    rows = season_rows(root)
    if rows.empty:
        return rows, 0
    rows["Method"] = rows["method"] + rows["refill"].map({1: " (refill)", 0: ""})
    out = []
    for method, r in rows.groupby("Method", sort=True):
        paid = r[r["cashed"].notna()]
        priced = paid[paid["fees"].notna()]
        fees = priced["fees"].sum()
        out.append({
            "Method": method, "Slates": r["slate_id"].nunique(), "Contests graded": len(r),
            "Lineups": int(r["lineups"].sum()),
            "Top 1 %": round(100 * r["top1"].sum() / r["lineups"].sum(), 2),
            "Top 5 %": round(100 * r["top5"].sum() / r["lineups"].sum(), 2),
            "Cash rate %": round(100 * paid["cashed"].sum() / paid["lineups"].sum(), 1) if len(paid) else None,
            "ROI %": round(100 * (priced["won"].sum() - fees) / fees, 1) if fees else None,
        })
    return pd.DataFrame(out), rows["slate_id"].nunique()


def season_note(n_slates):
    return (f"{n_slates} slate{'s' if n_slates != 1 else ''} in the season record so far. "
            f"About 10+ slates are needed before switching methods.")
