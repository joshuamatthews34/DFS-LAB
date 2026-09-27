"""Late-swap grader (SPEC 6.6) on a case worked out by hand.

DAL@NYG kicks off at 1:00 (locked at the swap), SEA@ARI at 4:25 (swappable).
  E1 unchanged
  E2 Perez (0.0) -> Harrison (7.7)             +7.7
  E3 Smith-Njigba (20.0) -> Perez (0.0)        -20.0
  E4 Gainwell -> McBride: salary $50,300       rejected (over the cap), not counted
  E5 only before the swap, E6 only after       unpaired
"""

import pytest

import builders as b
from core import lateswap, legal, slate, grade
from core.importers import sabersim

L = b.CLASSIC_LINEUP                                   # QB RB RB WR WR WR TE FLEX DST
WITH_PEREZ = [1001, 1004, 1007, 1002, 1012, 1006, 1003, 1011, 1010]
WITH_HARRISON = [1001, 1004, 1007, 1002, 1008, 1006, 1003, 1011, 1010]
JSN_TO_PEREZ = [1001, 1004, 1007, 1002, 1012, 1006, 1003, 1011, 1010]
OVER_CAP = [1001, 1004, 1007, 1002, 1005, 1006, 1003, 1009, 1010]
C = ("195648006", "NFL $3 Play-Action")


def _entries(path, rows):
    b.dk_entries_csv(path, "classic", [(eid, *C, lu) for eid, lu in rows], b.pool_from_players(b.CLASSIC_PLAYERS),
                     reservations=0)


@pytest.fixture
def swap_slate(home, downloads):
    ss = downloads / "ss.csv"
    b.sabersim_csv(ss, b.CLASSIC_PLAYERS)
    pre, post = downloads / "DKEntries pre-swap.csv", downloads / "DKEntries post-swap.csv"
    _entries(pre, [("9000000001", L), ("9000000002", WITH_PEREZ), ("9000000003", L), ("9000000004", L), ("9000000005", L)])
    _entries(post, [("9000000001", L), ("9000000002", WITH_HARRISON), ("9000000003", JSN_TO_PEREZ), ("9000000004", OVER_CAP), ("9000000006", L)])
    slate.import_files("wk2", [ss, pre, post])
    return downloads


def test_late_swap_by_entry_id(swap_slate):
    r = lateswap.grade_swap("wk2", "entries:DKEntries pre-swap.csv", "entries:DKEntries post-swap.csv")
    assert r.headline() == "3 of 4 paired entries changed, net -12.3 points (1 better, 1 worse)"
    assert r.summary["rejected"] == 1
    assert (r.unpaired_before, r.unpaired_after) == (["9000000005"], ["9000000006"])
    assert f"{r.locked_through:%H:%M}" == "13:00"
    t = lateswap.changed_table(r).set_index("Entry ID")
    assert (t.loc["9000000002", "Gain"], t.loc["9000000002", "Swapped out"], t.loc["9000000002", "Swapped in"]) == (7.7, "José Pérez",
                                                                                            "Marvin Harrison Jr.")
    assert t.loc["9000000003", "Gain"] == -20.0
    assert t.loc["9000000004", "Status"] == "rejected" and "over the $50,000 cap" in t.loc["9000000004", "Why rejected"]
    assert not r.warnings


def test_reshuffled_ids_pair_on_early_game_players(swap_slate, downloads):
    post = downloads / "reshuffled.csv"
    _entries(post, [("8000000001", L), ("8000000002", WITH_HARRISON), ("8000000003", JSN_TO_PEREZ), ("8000000004", OVER_CAP)])
    slate.import_files("wk2", [post])
    r = lateswap.grade_swap("wk2", "entries:DKEntries pre-swap.csv", "entries:reshuffled.csv")
    assert set(r.pairs["Matched by"]) == {"early-game players"}
    assert r.summary["paired"] == 4 and r.unpaired_before == ["9000000005"]
    # All five share the same 1:00 players, so pairing falls back to file order and says so.
    assert any("paired in file order" in w for w in r.warnings)
    assert r.headline() == "3 of 4 paired entries changed, net -12.3 points (1 better, 1 worse)"


def test_changing_a_locked_player_is_flagged(swap_slate, downloads):
    post = downloads / "DKEntries post-swap.csv"
    moved = [1001, 1004, 1011, 1002, 1005, 1006, 1003, 1012, 1010]    # Tracy (1:00 game) swapped out
    _entries(post, [("9000000001", moved)])
    slate.import_files("wk2", [post])
    r = lateswap.grade_swap("wk2", "entries:DKEntries pre-swap.csv", "entries:DKEntries post-swap (2).csv")
    assert any("games that had already started" in w for w in r.warnings)


def test_lock_time_can_be_chosen(swap_slate):
    times = lateswap.kickoff_times("wk2")
    assert [f"{t:%H:%M}" for t in times] == ["13:00", "16:25"]
    r = lateswap.grade_swap("wk2", "entries:DKEntries pre-swap.csv", "entries:DKEntries post-swap.csv",
                            locked_through=times[1])
    assert any("games that had already started" in w for w in r.warnings)     # every swap was after 4:25


# ---------------------------------------------------------------- legality (SPEC 4.1, 4.2)

@pytest.fixture
def players(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.CLASSIC_PLAYERS)
    df = sabersim.parse(p).players.set_index("dfs_id", drop=False)
    df["base_id"] = df["dfs_id"]
    return df


def test_legal_classic(players):
    assert legal.problems(L, players, "classic") == []
    two_qbs = [1001, 1001, 1007, 1002, 1005, 1006, 1003, 1011, 1010]
    assert "the same player is in it twice" in legal.problems(two_qbs, players, "classic")
    no_te = [1001, 1004, 1007, 1002, 1005, 1006, 1008, 1011, 1010]
    assert "0 TE (allowed 1-2)" in legal.problems(no_te, players, "classic")
    assert any("over the $50,000 cap" in x for x in legal.problems(OVER_CAP, players, "classic"))
    assert legal.problems([999, *L[1:]], players, "classic") == ["DFS ID(s) 999 aren't on the slate"]


def test_legal_classic_needs_two_games(players):
    players = players.copy()
    players["team"] = players["team"].where(players["team"] == "DAL", "NYG")      # everyone in DAL@NYG
    players["opp"] = players["team"].map({"DAL": "NYG", "NYG": "DAL"})
    assert "players must come from at least 2 games" in legal.problems(L, players, "classic")


def test_legal_showdown(downloads):
    p = downloads / "sd.csv"
    b.sabersim_csv(p, b.showdown_players(b.CLASSIC_PLAYERS[:10]))
    df = sabersim.parse(p).players.set_index("dfs_id", drop=False)
    df["base_id"] = [i - 500 if s == "CPT" else i for i, s in zip(df["dfs_id"], df["roster_slot"])]
    assert legal.problems([1506, 1001, 1002, 1003, 1007, 1010], df, "showdown") == []
    assert "the same player is in it twice" in legal.problems([1506, 1006, 1002, 1003, 1007, 1010], df, "showdown")
    assert any("one captain" in x for x in legal.problems([1006, 1001, 1002, 1003, 1007, 1010], df, "showdown"))
    assert "both teams must be represented" in legal.problems([1501, 1002, 1003, 1010], df, "showdown")
