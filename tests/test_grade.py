"""Grader (SPEC M2) on a small contest where every number can be worked out by hand.

Field of 10 (contest 195648006):
  rank 1  200.00   rank 2  150.00   rank 3  140.34 (our entry 4000000001)   rank 3  140.34 (tie)
  rank 5  130.00   rank 6  126.04   rank 7  120.00   rank 8  110.00   rank 9  100.00   rank 10  0 (blank)
Our entries: 4000000001 = 140.34 (in the field), 4000000002 = 126.04 (not in the field).
Payouts: 1st $100, 2nd $50, 3rd-5th $20, 6th-7th $10.
"""

import pytest

import builders as b
from conftest import CLASSIC_STANDINGS_LINEUP, classic_standings_players
from core import field, grade, slate
from core.io_utils import FileProblem

LINEUP = b.lineup_string(CLASSIC_STANDINGS_LINEUP)
FIELD = [("1", "5000000001", "a", "200.00"), ("2", "5000000002", "b", "150.00"),
         ("3", "4000000001", "savage", "140.34"), ("3", "5000000003", "c", "140.34"),
         ("5", "5000000004", "d", "130.00"), ("6", "5000000005", "e", "126.04"),
         ("7", "5000000006", "f", "120.00"), ("8", "5000000007", "g", "110.00"),
         ("9", "5000000008", "h", "100.00")]


@pytest.fixture
def graded_slate(home, classic_slate):
    rows = b.standings_rows([(*r, LINEUP) for r in FIELD] + [("10", "5000000009", "blank", "0", "")],
                            classic_standings_players())
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    b.payouts_csv(classic_slate["payouts"], [[1, 1, "$100"], [2, 2, "$50"], [3, 5, "$20"], [6, 7, "$10"]])
    slate.import_files("wk2", classic_slate.values())
    return classic_slate


def test_field_lines_and_percentiles(graded_slate):
    f = field.load_field("wk2", "195648006")
    assert f.n == 10 and f.top_score == 200.0
    assert list(f.higher([200, 140.34, 126.04, -1])) == [0, 2, 5, 10]     # strictly higher
    assert list(f.equal([140.34, 126.04, 1])) == [2, 1, 0]
    assert (f.line(0.01), f.line(0.10), f.line(0.20)) == (200.0, 150.0, 140.34)
    assert f.score_at_rank(7) == 120.0


def test_field_is_cached(graded_slate, home):
    field.load_field("wk2", "195648006")
    cached = list((home / "slates" / "wk2" / "results" / "cache").glob("field-195648006-*.pkl"))
    assert len(cached) == 1
    assert field.load_field("wk2", "195648006").n == 10


def test_summary_numbers(graded_slate):
    info, [g] = grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    assert not g.problems, g.problems
    s = g.summary
    assert (s["lineups"], s["avg_score"], s["median_score"], s["best_score"]) == (2, 133.19, 133.19, 140.34)
    assert (s["best_rank"], s["best_share"], s["median_share"]) == (3, 0.2, 0.35)
    assert s["counts"] == {"top 0.1%": 0, "top 1%": 0, "top 5%": 0, "top 10%": 0, "top 20%": 1}
    # 140.34 ties one field entry: shares ranks 3-4 ($20, $20). 126.04 ties one: shares ranks 6-7 ($10, $10).
    assert (s["cashed"], s["won"], s["fees"], s["roi"]) == (2, 30.0, 6.0, 4.0)
    assert (s["avg_salary_left"], s["avg_total_own"], s["avg_shared"], s["duplicates"]) == (800, 229.5, 7.0, 0)
    assert s["official_entries"] == 1


def test_graded_against_line(graded_slate):
    info, _ = grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    assert info.name == "NFL $3 Play-Action [20 Entry Max]"
    assert info.cash_line == 120.0 and info.last_paid_rank == 7 and info.fee_cents == 300
    assert info.perfect["score"] >= 140.34 and info.perfect["salary"] <= 50_000
    assert info.graded_against() == (
        f"Graded against NFL $3 Play-Action [20 Entry Max], 10 entries, winning score 200.0, top 1% 200.0, "
        f"cash line 120.0, perfect lineup {grade._fmt(info.perfect['score'])}.")


def test_lineup_viewer(graded_slate):
    info, [g] = grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    t = grade.lineup_table(g, info.has_payouts)
    assert t["Score"].tolist() == [140.34, 126.04]                      # sorted by final score
    assert t["Rank"].tolist() == [3, 6] and t["Top %"].tolist() == [20.0, 50.0]
    assert t["Prize $"].tolist() == [20.0, 10.0]
    assert t["Stack"].tolist() == ["QB+2|2", "QB+1|1"]                   # Dak + Lamb, Ferguson | Tracy, Nabers
    assert t["Players"][0].startswith("Dak Prescott / Kenneth Walker III")


def test_exposure_table(graded_slate):
    info, [g] = grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    e = g.exposure.set_index("Player")
    dak = e.loc["Dak Prescott"]
    assert (dak["Count"], dak["Exposure %"], dak["Actual own %"], dak["Leverage"]) == (2, 100.0, 25.5, 74.5)
    assert (dak["Proj"], dak["Final"], dak["Salary"]) == (19.8, 22.34, 6500)
    assert (dak["Top-1% lineups"], dak["Top-1% share %"]) == (1, 100.0)   # the one top-1% lineup had Dak
    harrison = e.loc["Marvin Harrison Jr."]
    assert (harrison["Count"], harrison["Exposure %"], harrison["Top-1% lineups"]) == (1, 50.0, 0)


def test_war_room_tag_shows_in_exposure(graded_slate, downloads):
    tags = downloads / "tags.json"
    tags.write_text('{"Dak Prescott": "OVER"}')
    slate.import_files("wk2", [tags])
    _, [g] = grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    assert g.exposure.set_index("Player").loc["Dak Prescott", "War Room"] == "OVER"


def test_no_payout_file_means_no_money_numbers(home, classic_slate):
    rows = b.standings_rows([(*r, LINEUP) for r in FIELD], classic_standings_players())
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    slate.import_files("wk2", [p for k, p in classic_slate.items() if k != "payouts"])
    info, [g] = grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    assert not info.has_payouts and "cashed" not in g.summary
    assert "cash line" not in info.graded_against()
    assert "not available (no payout file" in grade.to_text(info, [g])


def test_only_entries_in_this_contest(graded_slate, downloads):
    other = downloads / "DKEntries (1).csv"
    b.dk_entries_csv(other, "classic", [("4000000003", "999", "Other contest", b.CLASSIC_LINEUP)],
                     b.pool_from_players(b.CLASSIC_PLAYERS))
    slate.import_files("wk2", [other])
    _, [every] = grade.grade("wk2", "195648006", ["entries:all"])
    _, [entered] = grade.grade("wk2", "195648006", ["entries:all"], only_contest=True)
    assert every.summary["lineups"] == 3 and entered.summary["lineups"] == 2


def test_unknown_ids_are_reported_not_scored(graded_slate, downloads):
    bad = downloads / "DKEntries (2).csv"
    lineup = list(b.CLASSIC_LINEUP)
    lineup[0] = 999999
    b.dk_entries_csv(bad, "classic", [("4000000009", "195648006", "C", lineup)], [])
    slate.import_files("wk2", [bad])
    _, [g] = grade.grade("wk2", "195648006", ["entries:DKEntries (2).csv"])
    assert any("999999" in p for p in g.problems) and g.lineups.empty


def test_needs_a_post_game_export(home, classic_slate):
    b.sabersim_csv(classic_slate["sabersim"], b.CLASSIC_PLAYERS, actuals=False)
    slate.import_files("wk2", classic_slate.values())
    with pytest.raises(FileProblem, match="post-game SaberSim"):
        grade.grade("wk2", "195648006")


def test_results_are_saved(graded_slate, home):
    grade.grade("wk2", "195648006", ["entries:DKEntries.csv"])
    out = home / "slates" / "wk2" / "results" / "grades" / "195648006"
    assert (out / "grade_report.txt").read_text().startswith("Graded against NFL $3 Play-Action")
    assert (out / "entries_DKEntries.csv.lineups.csv").exists()
    assert (out / "entries_DKEntries.csv.exposure.csv").exists()


# ---------------------------------------------------------------- showdown

@pytest.fixture
def showdown_slate(home, downloads):
    players = b.showdown_players(b.CLASSIC_PLAYERS[:10])
    names = {p[0]: p[1] for p in players}
    ss = downloads / "ss.csv"
    b.sabersim_csv(ss, players)
    ent = downloads / "DKEntries.csv"
    # Nabers CPT (25.3 x 1.5 = 37.95) + Dak 22.34 + Lamb 18.5 + Ferguson 9.1 + Tracy 11.0 + Cowboys 5.0 = 103.89
    b.dk_entries_csv(ent, "showdown", [("7", "195943225", "NFL Showdown $100K mini-MAX",
                                        [1506, 1001, 1002, 1003, 1007, 1010])],
                     b.pool_from_players(players, roster="showdown"))
    army = downloads / "army.csv"
    b.dfsarmy_csv(army, [[1506, 1001, 1002, 1003, 1007, 1010], [1501, 1002, 1003, 1006, 1007, 1010]], names)
    lineup = "CPT Malik Nabers FLEX Dak Prescott FLEX CeeDee Lamb FLEX Jake Ferguson FLEX Tyrone Tracy Jr. FLEX Cowboys "
    right = [("Malik Nabers", "CPT", 30.0, 37.95), ("Malik Nabers", "FLEX", 20.0, 25.3),
             ("Dak Prescott", "FLEX", 60.0, 22.34), ("CeeDee Lamb", "FLEX", 50.0, 18.5),
             ("Jake Ferguson", "FLEX", 20.0, 9.1), ("Tyrone Tracy Jr.", "FLEX", 10.0, 11.0),
             ("Cowboys ", "FLEX", 12.0, 5.0)]
    st = downloads / "contest-standings-195943225.zip"
    b.standings_zip(st, "195943225", b.standings_rows(
        [("1", "8", "x", "120.00", lineup), ("2", "7", "savage", "103.89", lineup),
         ("3", "9", "y", "90.00", lineup)], right))
    slate.import_files("tnf", [ss, ent, army, st])


def test_showdown_captain_scores_one_and_a_half_times_flex(showdown_slate):
    info, [g] = grade.grade("tnf", "195943225", ["entries:DKEntries.csv"])
    assert not g.problems, g.problems
    assert g.summary["best_score"] == 103.89 and g.summary["best_rank"] == 2
    t = grade.lineup_table(g, info.has_payouts)
    assert t["Players"][0].startswith("CPT Malik Nabers / Dak Prescott")
    assert t["Stack"][0] == "WR CPT 2-4"                                 # NYG: Nabers, Tracy; DAL: 4
    assert t["Total own %"][0] == 30.0 + 60 + 50 + 20 + 10 + 12          # CPT row uses captain ownership


def test_showdown_exposure_splits_captain_and_flex(showdown_slate):
    _, [g] = grade.grade("tnf", "195943225", ["lineups:army.csv"])
    e = g.exposure.set_index("Player")
    assert (e.loc["Malik Nabers", "CPT"], e.loc["Malik Nabers", "FLEX"]) == (1, 1)
    assert e.loc["Malik Nabers", "Actual own %"] == 50.0                 # 30% CPT + 20% FLEX
    assert (e.loc["Dak Prescott", "CPT"], e.loc["Dak Prescott", "FLEX"]) == (1, 1)
    assert g.summary["avg_shared"] == 6.0 and g.summary["duplicates"] == 0


def test_perfect_showdown_lineup_is_legal(showdown_slate):
    info, _ = grade.grade("tnf", "195943225", ["entries:DKEntries.csv"])
    p = info.perfect
    assert p["players"][0].startswith("CPT ") and len(p["players"]) == 6 and p["salary"] <= 50_000


def test_entry_that_disagrees_with_draftkings_is_flagged(showdown_slate, downloads):
    ent = downloads / "DKEntries.csv"
    players = b.showdown_players(b.CLASSIC_PLAYERS[:10])
    b.dk_entries_csv(ent, "showdown", [("7", "195943225", "C", [1501, 1006, 1002, 1003, 1007, 1010])],
                     b.pool_from_players(players, roster="showdown"))
    slate.import_files("tnf", [ent])
    _, [g] = grade.grade("tnf", "195943225", ["entries:DKEntries (2).csv"])
    assert any("DraftKings scored it 103.89" in p for p in g.problems)


def test_classic_lineups_cant_be_graded_against_showdown(showdown_slate, classic_slate):
    slate.import_files("tnf", [classic_slate["entries"]])
    _, grades = grade.grade("tnf", "195943225")
    assert any("can't be graded here" in p for g in grades for p in g.problems)


# ---------------------------------------------------------------- entered lineups (from standings)

def test_entered_lineups_come_from_the_standings(graded_slate):
    keys = [k for k, _, _ in grade.available_sets("wk2")]
    assert keys[0] == grade.ENTERED_KEY
    info, [g] = grade.grade("wk2", "195648006", [grade.ENTERED_KEY])
    assert not g.problems, g.problems
    # Only 4000000001 is in the standings; 4000000002 was never entered.
    assert g.lineups["entry_id"].tolist() == ["4000000001"]
    assert (g.summary["best_rank"], g.summary["best_score"], g.summary["official_entries"]) == (3, 140.34, 1)


def test_entered_lineups_pick_up_late_swaps(graded_slate, home, classic_slate):
    # DraftKings has Harrison where the entries file has Nabers: the standings version is graded.
    swapped = [("DST", "Cowboys"), ("FLEX", "Kenneth Gainwell"), ("QB", "Dak Prescott"),
               ("RB", "Kenneth Walker III"), ("RB", "Tyrone Tracy Jr."), ("TE", "Jake Ferguson"),
               ("WR", "CeeDee Lamb"), ("WR", "Jaxon Smith-Njigba"), ("WR", "Marvin Harrison Jr.")]
    rows = b.standings_rows([("1", "5000000001", "a", "200.00", LINEUP),
                             ("2", "4000000001", "savage", "122.74", b.lineup_string(swapped))],
                            classic_standings_players())
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    slate.import_files("wk3", classic_slate.values())
    _, [g] = grade.grade("wk3", "195648006", [grade.ENTERED_KEY])
    assert not g.problems and g.summary["best_score"] == 122.74
    _, [stale] = grade.grade("wk3", "195648006", ["entries:DKEntries.csv"], only_contest=True)
    assert any("DraftKings scored it 122.74" in p for p in stale.problems)


def test_entered_lineup_with_unknown_name_is_reported(graded_slate, home, classic_slate):
    odd = [("DST", "Cowboys"), ("FLEX", "Somebody Else"), *CLASSIC_STANDINGS_LINEUP[2:]]
    rows = b.standings_rows([("1", "4000000001", "savage", "150", b.lineup_string(odd))],
                            classic_standings_players())
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    slate.import_files("wk3", classic_slate.values())
    _, [g] = grade.grade("wk3", "195648006", [grade.ENTERED_KEY])
    assert any("somebody else isn't in the SaberSim export" in p for p in g.problems)


def test_entered_showdown_lineup_maps_captain(showdown_slate):
    _, [g] = grade.grade("tnf", "195943225", [grade.ENTERED_KEY])
    assert not g.problems, g.problems
    assert g.lineups["ids"][0] == [1506, 1001, 1002, 1003, 1007, 1010]
    assert g.summary["best_score"] == 103.89
