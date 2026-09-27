"""Are SaberSim's percentile ranges too narrow? (SPEC 5.1 calibration)

Compares players' actual scores with their SaberSim percentiles across past slates.
A tail width of 1.0 uses the percentiles as they are; 1.3 stretches each percentile
30% further from the median (upper tail above it, lower tail below it).
"""

import numpy as np
import pandas as pd

from . import detect, rosters, slate

# (percentile column, share of actual scores expected ABOVE it)
LEVELS = [("dk_25", 75), ("dk_50", 50), ("dk_75", 25), ("dk_85", 15), ("dk_95", 5), ("dk_99", 1)]
DEFAULT_MIN_PROJ = 5.0
WIDTHS = np.round(np.arange(0.5, 3.001, 0.01), 2)


def collect(slate_ids, min_proj=DEFAULT_MIN_PROJ, root=None):
    """Players with SaberSim percentiles and an Actual score, from each slate.

    Percentiles come from the slate's pre-lock export when there is one (joined on DFS ID),
    otherwise from the post-game export. Showdown captains are left out (same player as FLEX).
    """
    frames, notes = [], []
    for sid in slate_ids:
        exports = slate.load_parsed(sid, root)[detect.SABERSIM]
        post = [d for _, _, d in exports if d.has_actuals]
        pre = [d for _, _, d in exports if not d.has_actuals]
        if not post:
            notes.append(f"{sid}: no post-game SaberSim export, so it's left out.")
            continue
        actual = post[-1].players.set_index("dfs_id")["actual"]
        src = pre[-1].players if pre else post[-1].players
        df = src[src["roster_slot"] != "CPT"][["dfs_id", "name", "pos", "team", "dk_points",
                                                *[c for c, _ in LEVELS]]].copy()
        df["actual"] = df["dfs_id"].map(actual)
        df["slate"] = sid
        df["percentiles_from"] = "pre-lock" if pre else "post-game"
        frames.append(df)
    if not frames:
        return pd.DataFrame(), notes
    df = pd.concat(frames, ignore_index=True)
    df = df[df["actual"].notna() & (df["dk_points"] >= min_proj)]
    return df.reset_index(drop=True), notes


def widen(df, col, lower=1.0, upper=1.0):
    """A percentile column stretched away from the median by the tail widths."""
    med = df["dk_50"]
    w = lower if col in ("dk_25",) else upper
    return med + w * (df[col] - med)


def table(df, lower=1.0, upper=1.0):
    rows = []
    for col, expected in LEVELS:
        raw = 100 * (df["actual"] > df[col]).mean()
        wide = 100 * (df["actual"] > widen(df, col, lower, upper)).mean()
        rows.append({"Level": f"above the {col[3:5]}th percentile", "Expected %": expected,
                     "SaberSim %": round(raw, 1), "With tail widths %": round(wide, 1)})
    raw = 100 * (df["actual"] < df["dk_25"]).mean()
    wide = 100 * (df["actual"] < widen(df, "dk_25", lower, upper)).mean()
    rows.append({"Level": "below the 25th percentile", "Expected %": 25, "SaberSim %": round(raw, 1),
                 "With tail widths %": round(wide, 1)})
    return pd.DataFrame(rows)


def fit(df):
    """Tail widths that make the actual rates closest to the expected ones.

    Upper width: squared error over the 75th, 85th, 95th and 99th percentiles.
    Lower width: the share below the 25th percentile.
    """
    if df.empty:
        return 1.0, 1.0
    a = df["actual"].to_numpy()
    med = df["dk_50"].to_numpy()

    def upper_err(w):
        return sum(((a > med + w * (df[c].to_numpy() - med)).mean() * 100 - e) ** 2
                   for c, e in LEVELS if c in ("dk_75", "dk_85", "dk_95", "dk_99"))

    def lower_err(w):
        return ((a < med + w * (df["dk_25"].to_numpy() - med)).mean() * 100 - 25) ** 2

    upper = min(WIDTHS, key=upper_err)
    lower = min(WIDTHS, key=lower_err)
    return float(lower), float(upper)


def slates_with_results(root=None):
    out = []
    for sid in slate.list_slates(root):
        try:
            if any(d.has_actuals for _, _, d in slate.load_parsed(sid, root)[detect.SABERSIM]):
                out.append(sid)
        except Exception:
            continue
    return out
