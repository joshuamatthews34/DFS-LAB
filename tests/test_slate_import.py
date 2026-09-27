import json
import sqlite3

import builders as b
from conftest import CLASSIC_STANDINGS_LINEUP, classic_standings_players
from core import slate


def test_full_classic_import(home, classic_slate):
    report = slate.import_files("2026-wk02-main", classic_slate.values())
    assert report.headline() == "2 entries · 1 standings file · 0 FPTS mismatches"
    assert report.ok, report.to_text()
    assert report.fmt == "classic" and report.players == 12 and report.blend_loaded is True
    assert report.fpts_compared == 11
    assert report.contests[0]["contest_name"] == "NFL $3 Play-Action [20 Entry Max]"
    assert report.contests[0]["has_payouts"] is True

    folder = home / "slates" / "2026-wk02-main"
    assert sorted(p.name for p in (folder / "raw").iterdir()) == sorted(p.name for p in classic_slate.values())
    for sub in ("prelock", "builds", "results"):
        assert (folder / sub).is_dir()
    assert (folder / "results" / "import_report.txt").read_text().splitlines()[2] == report.headline()
    assert slate.load_report("2026-wk02-main").headline() == report.headline()


def test_raw_copies_are_untouched(home, classic_slate):
    slate.import_files("s1", classic_slate.values())
    for src in classic_slate.values():
        assert (home / "slates" / "s1" / "raw" / src.name).read_bytes() == src.read_bytes()


def test_database_keeps_post_game_numbers_apart(home, classic_slate):
    slate.import_files("s1", classic_slate.values())
    conn = sqlite3.connect(home / "dfs_lab.db")
    player_cols = [r[1] for r in conn.execute("PRAGMA table_info(players)")]
    assert "actual" not in player_cols and "live_proj" not in player_cols
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 12
    assert conn.execute("SELECT actual FROM player_results WHERE dfs_id = 1001").fetchone()[0] == 22.34
    assert conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 2
    assert json.loads(conn.execute("SELECT player_ids FROM entries WHERE entry_id='4000000001'").fetchone()[0]) \
        == b.CLASSIC_LINEUP
    assert conn.execute("SELECT COUNT(*) FROM payouts").fetchone()[0] == 2


def test_reimport_replaces_rows_instead_of_doubling(home, classic_slate):
    slate.import_files("s1", classic_slate.values())
    report = slate.import_files("s1", classic_slate.values())
    assert report.entries == 2
    assert any("already imported" in w for w in report.warnings)
    conn = sqlite3.connect(home / "dfs_lab.db")
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 12


def test_fpts_mismatch_is_reported(home, classic_slate, downloads):
    rows = b.standings_rows([("1", "1", "x", "150", b.lineup_string(CLASSIC_STANDINGS_LINEUP))],
                            classic_standings_players({"Malik Nabers": 25.0}))
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    report = slate.import_files("s1", classic_slate.values())
    assert report.headline().endswith("1 FPTS mismatch")
    assert report.fpts_mismatches == [{"player": "Malik Nabers", "contest_id": "195648006",
                                       "standings_fpts": 25.0, "sabersim_actual": 25.3}]


def test_unmatched_names_are_listed_never_dropped(home, classic_slate):
    players = classic_standings_players()
    players[0] = ("Dakota Prescott", "QB", 20.0, 22.34)
    rows = b.standings_rows([("1", "1", "x", "150", b.lineup_string(CLASSIC_STANDINGS_LINEUP))], players)
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    report = slate.import_files("s1", classic_slate.values())
    assert report.unmatched_names["standings"] == ["Dakota Prescott"]
    assert not report.ok


def test_zero_byte_standings_is_reported_not_crashed(home, classic_slate, downloads):
    empty = downloads / "contest-standings-193028206.zip"
    b.standings_zip(empty, "193028206", [], empty=True)
    report = slate.import_files("s1", [*classic_slate.values(), empty])
    assert report.zero_byte_files == ["contest-standings-193028206.zip"]
    assert report.standings_files == 1
    assert "try downloading" in report.to_text().lower()


def test_empty_file_is_not_copied(home, classic_slate, downloads):
    empty = downloads / "contest-standings-193028206.csv"
    empty.write_bytes(b"")
    report = slate.import_files("s1", [*classic_slate.values(), empty])
    assert report.zero_byte_files == ["contest-standings-193028206.csv"]
    assert not (home / "slates" / "s1" / "raw" / empty.name).exists()


def test_same_content_twice_is_ignored(home, classic_slate, downloads):
    copy = downloads / "contest-standings-195648006 copy.zip"
    copy.write_bytes(classic_slate["standings"].read_bytes())
    report = slate.import_files("s1", [*classic_slate.values(), copy])
    assert report.standings_files == 1
    assert any("already imported" in w for w in report.warnings)


def test_pre_game_export_only_means_no_fpts_check(home, classic_slate):
    b.sabersim_csv(classic_slate["sabersim"], b.CLASSIC_PLAYERS, actuals=False)
    report = slate.import_files("s1", classic_slate.values())
    assert report.headline().endswith("FPTS check not run")
    assert "post-game" in report.fpts_note


def test_blend_not_loaded_is_flagged(home, classic_slate):
    b.sabersim_csv(classic_slate["sabersim"], b.CLASSIC_PLAYERS, blend=False)
    report = slate.import_files("s1", classic_slate.values())
    assert report.blend_loaded is False
    assert "NOT loaded" in report.to_text()


def test_entries_from_another_slate_are_caught(home, classic_slate):
    b.dk_entries_csv(classic_slate["entries"], "classic",
                     [("4000000001", "1", "C", [9001, 9002, 9003, 9004, 9005, 9006, 9007, 9008, 9009])], [])
    report = slate.import_files("s1", classic_slate.values())
    assert any("different slates" in p for p in report.problems)
    assert report.unknown_ids["entries"][:2] == [9001, 9002]


def test_missing_sabersim_is_a_problem(home, classic_slate):
    report = slate.import_files("s1", [classic_slate["entries"], classic_slate["standings"]])
    assert any("No SaberSim player export" in p for p in report.problems)


def test_same_entry_in_two_files_counts_once(home, classic_slate, downloads):
    swapped = downloads / "DKEntries (1).csv"
    lineup = list(b.CLASSIC_LINEUP)
    lineup[7] = 1009
    b.dk_entries_csv(swapped, "classic", [("4000000001", "195648006", "NFL", lineup)],
                     b.pool_from_players(b.CLASSIC_PLAYERS))
    report = slate.import_files("s1", [*classic_slate.values(), swapped])
    assert report.entries == 2
    assert any("more than one entries file" in w for w in report.warnings)


def test_bad_slate_name(home, classic_slate):
    import pytest
    from core.io_utils import FileProblem
    with pytest.raises(FileProblem):
        slate.import_files("../escape", classic_slate.values())


# ---------------------------------------------------------------- showdown

def _showdown_slate(downloads):
    players = b.showdown_players(b.CLASSIC_PLAYERS[:10])
    names = {p[0]: p[1] for p in players}
    ss = downloads / "NFL_2026-09-18_DK_Showdown_DAL-NYG.csv"
    b.sabersim_csv(ss, players)
    ent = downloads / "DKEntries.csv"
    b.dk_entries_csv(ent, "showdown", [("7", "195943225", "NFL Showdown $100K mini-MAX",
                                        [1506, 1001, 1002, 1003, 1007, 1010])],
                     b.pool_from_players(players, roster="showdown"))
    army = downloads / "DFS ARMY SHOWDOWN LINEUPS.csv"
    b.dfsarmy_csv(army, [[1501, 1002, 1003, 1006, 1007, 1010]], names)
    lineup = "CPT Malik Nabers FLEX Dak Prescott FLEX CeeDee Lamb FLEX Jake Ferguson FLEX Tyrone Tracy Jr. FLEX Cowboys "
    right = [("Malik Nabers", "CPT", 30.1, 37.95), ("Dak Prescott", "FLEX", 60.0, 22.34),
             ("CeeDee Lamb", "FLEX", 50.0, 18.5), ("Jake Ferguson", "FLEX", 20.0, 9.1),
             ("Tyrone Tracy Jr.", "FLEX", 10.0, 11.0), ("Cowboys ", "FLEX", 12.0, 5.0)]
    st = downloads / "contest-standings-195943225.zip"
    b.standings_zip(st, "195943225", b.standings_rows([("1", "7", "savage", "152.1", lineup)], right))
    return [ss, ent, army, st]


def test_showdown_import(home, downloads):
    report = slate.import_files("2026-wk03-tnf", _showdown_slate(downloads))
    assert report.ok, report.to_text()
    assert report.fmt == "showdown" and report.players == 10 and report.lineups == 1
    assert report.headline() == "1 entry · 1 standings file · 0 FPTS mismatches"
    assert report.fpts_compared == 5
    assert any("Only drafted as captain" in w and "Malik Nabers" in w for w in report.warnings)


def test_showdown_flex_id_in_captain_slot_is_caught(home, downloads):
    files = _showdown_slate(downloads)
    players = b.showdown_players(b.CLASSIC_PLAYERS[:10])
    b.dk_entries_csv(files[1], "showdown", [("7", "195943225", "C", [1006, 1001, 1002, 1003, 1007, 1010])],
                     b.pool_from_players(players, roster="showdown"))
    report = slate.import_files("s1", files)
    assert any("FLEX ID in the CPT slot" in p for p in report.problems)


def test_warroom_tags_are_matched_and_stored(home, classic_slate, downloads):
    tags = downloads / "wk2_warroom_tags.json"
    tags.write_text(json.dumps({"Dak Prescott": "OVER", "Kenneth Walker": {"tag": "UNDER", "max": 12},
                                "Nobody Real": "FADE"}))
    report = slate.import_files("s1", [*classic_slate.values(), tags])
    assert report.unmatched_names == {"War Room (wk2_warroom_tags.json)": ["Nobody Real"]}
    assert any("War Room name" in p for p in report.problems)
    conn = sqlite3.connect(home / "dfs_lab.db")
    rows = dict(conn.execute("SELECT player, dfs_id FROM warroom_tags").fetchall())
    assert rows == {"Dak Prescott": 1001, "Kenneth Walker": 1004, "Nobody Real": None}
