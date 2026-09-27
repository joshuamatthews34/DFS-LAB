import zipfile

import builders as b
from core import detect


def test_detects_each_file_type(classic_slate, downloads):
    assert detect.detect(classic_slate["sabersim"]).kind == detect.SABERSIM
    d = detect.detect(classic_slate["entries"])
    assert (d.kind, d.fmt) == (detect.DK_ENTRIES, "classic")
    d = detect.detect(classic_slate["standings"])
    assert (d.kind, d.contest_id, d.member) == (detect.STANDINGS, "195648006", "contest-standings-195648006.csv")
    d = detect.detect(classic_slate["payouts"])
    assert (d.kind, d.contest_id) == (detect.PAYOUTS, "195648006")

    army = downloads / "DFS ARMY SHOWDOWN LINEUPS 9-21.csv"
    b.dfsarmy_csv(army, [[1501, 1002, 1003, 1006, 1007, 1010]],
                  {p[0]: p[1] for p in b.showdown_players(b.CLASSIC_PLAYERS)})
    d = detect.detect(army)
    assert (d.kind, d.fmt) == (detect.LINEUPS, "showdown")

    tags = downloads / "wk3_warroom_tags.json"
    tags.write_text('{"Dak Prescott": "OVER"}')
    assert detect.detect(tags).kind == detect.WARROOM


def test_unknown_header_is_rejected_not_guessed(downloads):
    p = downloads / "something.csv"
    p.write_text("Player,Team,Points\nA,B,1\n")
    d = detect.detect(p)
    assert d.kind == detect.UNKNOWN
    assert "Player, Team, Points" in d.reason


def test_zero_byte_files(downloads):
    p = downloads / "contest-standings-195648006.csv"
    p.write_bytes(b"")
    d = detect.detect(p)
    assert d.kind == detect.EMPTY and "try downloading" in d.reason.lower()

    z = downloads / "contest-standings-193028206.zip"
    b.standings_zip(z, "193028206", [], empty=True)
    assert detect.detect(z).kind == detect.EMPTY


def test_damaged_zip(downloads):
    z = downloads / "contest-standings-1.zip"
    z.write_bytes(b"PK\x03\x04 not really a zip")
    assert detect.detect(z).kind == detect.UNREADABLE


def test_zip_with_two_csvs_is_not_guessed(downloads):
    z = downloads / "two.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.csv", "x\n")
        zf.writestr("b.csv", "y\n")
    assert detect.detect(z).kind == detect.UNKNOWN


def test_scan_folder_lists_supported_files_newest_first(classic_slate, downloads):
    (downloads / "photo.png").write_bytes(b"x")
    found = detect.scan_folder(downloads)
    names = {det.path.name for det, _ in found}
    assert names == {p.name for p in classic_slate.values()}
