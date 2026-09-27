"""SaberSim player export (SPEC 3.1)."""

from dataclasses import dataclass, field

import pandas as pd

from .. import rosters
from ..io_utils import FileProblem, clean_header, open_text
from ..names import normalize_name

PERCENTILES = [f"dk_{p}_percentile" for p in (25, 50, 75, 85, 95, 99)]

REQUIRED = [
    "DFS ID", "Name", "Pos", "Team", "Opp", "Status", "Salary", "Actual", "SS Proj",
    "Live Proj", "My Proj", "Value", "My Own", "Adj Own", "Min Exp", "Max Exp",
    "Saber Team", "Saber Total", "dk_points", *PERCENTILES,
]

# Export column -> our column. `actual` and `live_proj` are post-game numbers:
# they go to the results table only and are never used for building (SPEC 7).
COLUMNS = {
    "DFS ID": "dfs_id", "Name": "name", "Pos": "pos", "Team": "team", "Opp": "opp",
    "Status": "status", "Salary": "salary", "SS Proj": "ss_proj", "My Proj": "my_proj",
    "Value": "value", "My Own": "my_own", "Adj Own": "adj_own", "Min Exp": "min_exp",
    "Max Exp": "max_exp", "Saber Team": "saber_team", "Saber Total": "saber_total",
    "dk_points": "dk_points", "dk_std": "dk_std",
    **{p: p.replace("_percentile", "") for p in PERCENTILES},
    "Actual": "actual", "Live Proj": "live_proj",
}
TEXT_COLUMNS = {"name", "pos", "team", "opp", "status"}
RESULT_COLUMNS = ["actual", "live_proj"]


@dataclass
class SaberSimData:
    players: pd.DataFrame
    fmt: str
    has_actuals: bool
    blend_loaded: object  # True / False / None (My Proj blank)
    warnings: list = field(default_factory=list)

    @property
    def player_count(self):
        if self.fmt == rosters.SHOWDOWN:
            return int((self.players["roster_slot"] == "FLEX").sum())
        return len(self.players)


def _to_number(series, column):
    text = series.astype(str).str.strip().str.replace(r"[$,%]", "", regex=True)
    values = pd.to_numeric(text.where(text != ""), errors="coerce")
    bad = values.isna() & (text != "") & (text.str.lower() != "nan")
    if bad.any():
        rows = [f"row {i + 2} ('{series[i]}')" for i in series.index[bad][:5]]
        raise FileProblem(f"SaberSim column '{column}' has values that aren't numbers: {', '.join(rows)}.")
    return values


def parse(path):
    with open_text(path) as f:
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
    df.columns = clean_header(df.columns)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise FileProblem("SaberSim export is missing column(s): " + ", ".join(missing)
                          + ". Re-export the player file from SaberSim with all columns.")
    df = df[[c for c in COLUMNS if c in df.columns]].rename(columns=COLUMNS)
    df = df[df["dfs_id"].str.strip() != ""].reset_index(drop=True)
    if df.empty:
        raise FileProblem("SaberSim export has no player rows.")

    for col in df.columns:
        if col not in TEXT_COLUMNS:
            df[col] = _to_number(df[col], col)
        else:
            df[col] = df[col].str.strip()
    if (df["dfs_id"] % 1 != 0).any():
        raise FileProblem("SaberSim 'DFS ID' has non-whole numbers.")
    df["dfs_id"] = df["dfs_id"].astype("int64")
    dupes = df["dfs_id"][df["dfs_id"].duplicated()].unique()
    if len(dupes):
        raise FileProblem(f"SaberSim export lists the same DFS ID more than once: {', '.join(map(str, dupes[:5]))}.")
    if (df["name"] == "").any():
        raise FileProblem(f"SaberSim export has {int((df['name'] == '').sum())} row(s) with no player name.")
    df["name_key"] = df["name"].map(normalize_name)

    warnings = []
    fmt = _assign_roster_slots(df, warnings)
    blend = _blend_status(df, warnings)
    actual = df["actual"].fillna(0)
    return SaberSimData(df, fmt, bool((actual != 0).any()), blend, warnings)


def _assign_roster_slots(df, warnings):
    """Showdown exports list each player twice (CPT and FLEX, different IDs, CPT salary 1.5x)."""
    groups = df.groupby(["name_key", "team"]).indices
    pairs = [idx for idx in groups.values() if len(idx) == 2]
    df["roster_slot"] = None
    if len(pairs) * 2 < len(groups):
        if pairs:
            warnings.append(f"{len(pairs)} player name(s) appear twice on the same team; check the export.")
        return rosters.CLASSIC

    odd = []
    for key, idx in groups.items():
        if len(idx) != 2:
            odd.append(f"{key[0]} ({key[1]}) has {len(idx)} row(s)")
            continue
        a, b = df.loc[idx[0]], df.loc[idx[1]]
        cpt, flex = (idx[0], idx[1]) if a["salary"] > b["salary"] else (idx[1], idx[0])
        df.loc[cpt, "roster_slot"] = "CPT"
        df.loc[flex, "roster_slot"] = "FLEX"
        if df.loc[cpt, "salary"] * 2 != df.loc[flex, "salary"] * 3:
            odd.append(f"{df.loc[cpt, 'name']}: CPT ${df.loc[cpt, 'salary']:,.0f} isn't 1.5x FLEX ${df.loc[flex, 'salary']:,.0f}")
    if odd:
        warnings.append("Showdown rows that don't pair up cleanly: " + "; ".join(odd[:5])
                        + (f" (+{len(odd) - 5} more)" if len(odd) > 5 else ""))
    return rosters.SHOWDOWN


def _blend_status(df, warnings):
    both = df[["my_proj", "ss_proj"]].dropna()
    if both.empty:
        warnings.append("My Proj is blank, so your blend (SaberSim + LineStar + DFS Army) isn't in this export.")
        return None
    if ((both["my_proj"] - both["ss_proj"]).abs() < 0.005).all():
        warnings.append("My Proj equals SS Proj on every row: the blend wasn't loaded before exporting.")
        return False
    return True
