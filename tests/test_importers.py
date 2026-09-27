import json

import pytest

import builders as b
from core.importers import entries, lineups, payouts, sabersim, standings, warroom
from core.io_utils import FileProblem


# ---------------------------------------------------------------- SaberSim (3.1)

def test_sabersim_classic(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.CLASSIC_PLAYERS)
    d = sabersim.parse(p)
    assert d.fmt == "classic" and d.player_count == 12
    assert d.has_actuals and d.blend_loaded is True
    assert "saber_total" in d.players.columns        # stray backslash stripped from the header
    assert "FD ID" not in d.players.columns           # FanDuel/Yahoo columns ignored
    assert d.players.loc[d.players.dfs_id == 1004, "name_key"].item() == "kenneth walker"


def test_sabersim_blend_not_loaded_warns(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.CLASSIC_PLAYERS, blend=False)
    d = sabersim.parse(p)
    assert d.blend_loaded is False
    assert any("blend wasn't loaded" in w for w in d.warnings)


def test_sabersim_pre_game_has_no_actuals(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.CLASSIC_PLAYERS, actuals=False)
    assert sabersim.parse(p).has_actuals is False


def test_sabersim_missing_column_stops_with_its_name(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.CLASSIC_PLAYERS, drop=("dk_85_percentile",))
    with pytest.raises(FileProblem, match="dk_85_percentile"):
        sabersim.parse(p)


def test_sabersim_non_number_stops_with_the_row(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.CLASSIC_PLAYERS)
    p.write_text(p.read_text().replace(",6500,", ",six5,", 1))
    with pytest.raises(FileProblem, match="row 2"):
        sabersim.parse(p)


def test_sabersim_showdown_pairs_cpt_and_flex(downloads):
    p = downloads / "ss.csv"
    b.sabersim_csv(p, b.showdown_players(b.CLASSIC_PLAYERS[:4]))
    d = sabersim.parse(p)
    assert d.fmt == "showdown" and d.player_count == 4
    slots = dict(zip(d.players.dfs_id, d.players.roster_slot))
    assert slots[1001] == "FLEX" and slots[1501] == "CPT"
    assert not d.warnings


# ---------------------------------------------------------------- DK entries (3.2)

def test_entries_file(downloads):
    p = downloads / "DKEntries.csv"
    b.dk_entries_csv(p, "classic", [("4000000001", "195648006", "NFL $3 Play-Action", b.CLASSIC_LINEUP)],
                     b.pool_from_players(b.CLASSIC_PLAYERS), reservations=2, fee="$3")
    d = entries.parse(p, "classic")
    assert len(d.entries) == 1 and d.reservations == 2
    e = d.entries[0]
    assert (e.entry_id, e.contest_id, e.fee_cents, e.player_ids) == ("4000000001", "195648006", 300, b.CLASSIC_LINEUP)
    assert len(d.pool) == 12
    assert d.pool.loc[d.pool.dfs_id == 1010, "name"].item() == "Cowboys"     # trailing space trimmed


def test_entries_cells_can_be_name_plus_id(downloads):
    assert entries.cell_to_id("Matthew Stafford (44191176)") == 44191176
    assert entries.cell_to_id("Rams  (44191139)") == 44191139
    assert entries.cell_to_id(" 44191176 ") == 44191176
    assert entries.cell_to_id("") is None
    with pytest.raises(ValueError):
        entries.cell_to_id("Matthew Stafford")


def test_entries_partial_lineup_is_skipped_and_reported(downloads):
    p = downloads / "DKEntries.csv"
    lineup = list(b.CLASSIC_LINEUP)
    lineup[3] = ""
    b.dk_entries_csv(p, "classic", [("4000000001", "1", "C", lineup)], [], reservations=0)
    d = entries.parse(p, "classic")
    assert d.entries == [] and "partly filled" in d.warnings[0]


# ---------------------------------------------------------------- DFS Army (3.3)

def test_dfsarmy_bom_and_name_id_cells(downloads):
    players = b.showdown_players(b.CLASSIC_PLAYERS)
    names = {p[0]: p[1] for p in players}
    p = downloads / "army.csv"
    b.dfsarmy_csv(p, [[1501, 1002, 1003, 1006, 1007, 1010], [1506, 1001, 1002, 1003, 1010, 1007]], names)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    d = lineups.parse(p, "showdown")
    assert d.lineups[0] == [1501, 1002, 1003, 1006, 1007, 1010]
    assert d.names[1010] == "Cowboys"


# ---------------------------------------------------------------- Standings (3.4)

def test_parse_lineup_string():
    pairs = standings.parse_lineup("DST Panthers  FLEX Jake Ferguson QB Dak Prescott RB A B RB C D TE E F "
                                   "WR G H WR I J WR K L")
    assert pairs[0] == ("DST", "Panthers") and pairs[1] == ("FLEX", "Jake Ferguson")
    assert len(pairs) == 9
    assert standings.parse_lineup("CPT Bijan Robinson FLEX Drake London FLEX A B FLEX C D FLEX E F FLEX G H")[0] \
        == ("CPT", "Bijan Robinson")
    assert standings.parse_lineup("") is None
    assert standings.parse_lineup("LOCKED") is None


def test_standings_zip(classic_slate):
    d = standings.parse(classic_slate["standings"], "contest-standings-195648006.csv", "195648006")
    assert (d.fmt, d.entries, d.skipped, d.top_score) == ("classic", 2, 1, 150.24)
    row = d.players[d.players.player == "Dak Prescott"].iloc[0]
    assert (row.pct_drafted, row.fpts) == (25.5, 22.34)


# ---------------------------------------------------------------- Payouts (3.5)

def test_payouts(downloads):
    p = downloads / "payouts-195648006.csv"
    b.payouts_csv(p, [[1, 1, "$1,000"], [2, 10, "$5.50"]])
    d = payouts.parse(p, "195648006")
    assert d.prize_cents.tolist() == [100000, 550]


@pytest.mark.parametrize("rows, message", [
    ([[1, 1, "$10"], [3, 4, "$5"]], "gap"),
    ([[1, 2, "$10"], [2, 4, "$5"]], "overlap"),
    ([[2, 4, "$5"]], "start at rank 1"),
    ([[1, 1, "ten"]], "numbers"),
])
def test_payout_mistakes_stop_the_import(downloads, rows, message):
    p = downloads / "payouts-195648006.csv"
    b.payouts_csv(p, rows)
    with pytest.raises(FileProblem, match=message):
        payouts.parse(p, "195648006")


def test_payouts_need_a_contest_id_in_the_name(downloads):
    p = downloads / "payouts.csv"
    b.payouts_csv(p, [[1, 1, "$10"]])
    with pytest.raises(FileProblem, match="contest ID"):
        payouts.parse(p, None)


# ---------------------------------------------------------------- War Room (3.6)

def test_warroom_tags_and_caps(downloads):
    p = downloads / "wk3_warroom_tags.json"
    p.write_text(json.dumps({"Dak Prescott": "over", "Kenneth Walker III": {"tag": "UNDER", "max": 12}}))
    d = warroom.parse(p)
    assert d.tag.tolist() == ["OVER", "UNDER"] and d.cap_max.tolist()[1] == 12


def test_warroom_bad_tag(downloads):
    p = downloads / "tags.json"
    p.write_text(json.dumps({"Dak Prescott": "SMASH"}))
    with pytest.raises(FileProblem, match="SMASH"):
        warroom.parse(p)
