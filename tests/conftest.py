import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import builders as b  # noqa: E402

CLASSIC_STANDINGS_LINEUP = [
    ("DST", "Cowboys"), ("FLEX", "Kenneth Gainwell"), ("QB", "Dak Prescott"), ("RB", "Kenneth Walker III"),
    ("RB", "Tyrone Tracy Jr."), ("TE", "Jake Ferguson"), ("WR", "CeeDee Lamb"), ("WR", "Jaxon Smith-Njigba"),
    ("WR", "Malik Nabers"),
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh DFS Lab home (slates/ + dfs_lab.db) for each test."""
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.setenv("DFS_LAB_HOME", str(root))
    return root


@pytest.fixture
def downloads(tmp_path):
    d = tmp_path / "Downloads"
    d.mkdir()
    return d


def classic_standings_players(fpts_override=None):
    """Right block: every drafted player with DK's FPTS (= SaberSim Actual unless overridden)."""
    fpts_override = fpts_override or {}
    out = []
    for pid, name, pos, *_, act in b.CLASSIC_PLAYERS[:11]:
        dk_name = "Kenneth Gainwell" if name == "Kenny Gainwell" else name
        dk_name = dk_name + " " if pos == "DST" else dk_name
        out.append((dk_name, pos, 25.5, fpts_override.get(name, act)))
    return out


@pytest.fixture
def classic_slate(downloads):
    """A complete classic slate in a fake Downloads folder. Returns a dict of paths."""
    paths = {}
    paths["sabersim"] = downloads / "NFL_2026-09-14_DK_Main_players.csv"
    b.sabersim_csv(paths["sabersim"], b.CLASSIC_PLAYERS)
    paths["entries"] = downloads / "DKEntries.csv"
    b.dk_entries_csv(paths["entries"], "classic",
                     [("4000000001", "195648006", "NFL $3 Play-Action [20 Entry Max]", b.CLASSIC_LINEUP),
                      ("4000000002", "195648006", "NFL $3 Play-Action [20 Entry Max]",
                       [1001, 1004, 1011, 1002, 1005, 1008, 1009, 1007, 1010])],
                     b.pool_from_players(b.CLASSIC_PLAYERS))
    lineup = b.lineup_string(CLASSIC_STANDINGS_LINEUP)
    rows = b.standings_rows(
        [("1", "4000000001", "savage (1/2)", "150.24", lineup),
         ("2", "5000000001", "someone", "140.10", lineup),
         ("3", "5000000002", "blank lineup", "0", "")],
        classic_standings_players())
    paths["standings"] = downloads / "contest-standings-195648006.zip"
    b.standings_zip(paths["standings"], "195648006", rows)
    paths["payouts"] = downloads / "payouts-195648006.csv"
    b.payouts_csv(paths["payouts"], [[1, 1, "$1,000"], [2, 3, "$5"]])
    return paths
