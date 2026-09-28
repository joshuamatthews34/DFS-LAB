"""DFS Lab's builder (SPEC 5.2-5.4, section 7): rules, fill, guardrails, snapshot and the DK file."""

import csv
import json
from itertools import combinations

import pytest

import builders as b
from core import builder, builds, compare, grade, legal, ownership, rosters, slate
from core.builder import BuildSettings
from core.io_utils import FileProblem

FAST = dict(pool_size=400, workers=1)
SHOWDOWN = b.synthetic_players(games=(("DAL", "NYG"),), kickers=True, salary_scale=1.3)
CLASSIC = b.synthetic_players()
CONTEST = "195943225"


def _showdown_slate(downloads, n_entries=20):
    players = b.showdown_players(SHOWDOWN)
    pre = downloads / "prelock.csv"
    b.sabersim_csv(pre, players, actuals=False)
    ent = downloads / "DKEntries.csv"
    b.dk_entries_csv(ent, "showdown", [], b.pool_from_players(players, roster="showdown"), reservations=0)
    rows = list(csv.reader(ent.open()))
    for i in range(n_entries):                      # blank reserved entries in one contest
        rows[1 + i][:4] = [f"50000000{i:02d}", "NFL Showdown $100K mini-MAX", CONTEST, "$5"]
    with ent.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    return [pre, ent]


@pytest.fixture
def sd(home, downloads):
    slate.import_files("tnf", _showdown_slate(downloads))
    return downloads


@pytest.fixture
def classic(home, downloads):
    pre = downloads / "prelock.csv"
    b.sabersim_csv(pre, CLASSIC, actuals=False)
    ent = downloads / "DKEntries.csv"
    b.dk_entries_csv(ent, "classic", [], b.pool_from_players(CLASSIC), reservations=0)
    slate.import_files("main", [pre, ent])
    return downloads


def _lookup(r):
    return r.pool.set_index("dfs_id")[["base_id", "pos", "team", "opp", "salary", "slot"]].rename(
        columns={"slot": "roster_slot"})


# ---------------------------------------------------------------- showdown

def test_showdown_build_is_legal_and_fills_the_entries(sd):
    r = builder.build("tnf", BuildSettings(**FAST))
    assert r.checks["lineups"] == 20 and r.checks["legal"] == 20 and r.checks["duplicates"] == 0
    lk = _lookup(r)
    for ids in r.lineup_ids():
        assert legal.problems(ids, lk, "showdown") == []
        assert lk.loc[ids, "salary"].sum() >= 48_000                        # default showdown floor
        assert (lk.loc[ids, "pos"] == "K").sum() <= 1 and (lk.loc[ids, "pos"] == "DST").sum() <= 1
    rows = list(csv.reader(open(r.csv_path)))
    assert rows[0] == ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", "CPT", "FLEX", "FLEX", "FLEX", "FLEX",
                       "FLEX"]
    assert [row[0] for row in rows[1:]] == [f"50000000{i:02d}" for i in range(20)]
    assert all(row[2] == CONTEST and row[3] == "$5" for row in rows[1:])
    assert all(lk.at[int(row[4]), "roster_slot"] == "CPT" for row in rows[1:])


def test_uniques_between_lineups(sd):
    r = builder.build("tnf", BuildSettings(min_uniques=2, **FAST))
    items = [{(slot, base) for slot, base in zip(r.pool.loc[lu, "slot"], r.pool.loc[lu, "base_id"])}
             for lu in r.lineups]
    assert all(6 - len(a & b) >= 2 for a, b in combinations(items, 2))


def test_qb_captain_brings_a_pass_catcher(sd):
    r = builder.build("tnf", BuildSettings(**FAST))
    for lu in r.lineups:
        rows = r.pool.loc[lu]
        cpt = rows.iloc[0]
        if cpt["pos"] == "QB":
            mates = rows.iloc[1:]
            assert ((mates["team"] == cpt["team"]) & mates["pos"].isin(["WR", "TE"])).any()


def test_war_room_caps_and_record(sd, downloads):
    top = sorted(SHOWDOWN, key=lambda p: -p[6])
    under, fade = top[0][1], top[1][1]
    (downloads / "tags.json").write_text(json.dumps({under: "UNDER", fade: "FADE"}))
    slate.import_files("tnf", [downloads / "tags.json"])
    r = builder.build("tnf", BuildSettings(**FAST))
    p = r.players.set_index("name")
    assert p.loc[under, "exposure"] <= p.loc[under, "own"] * 0.6 + 1e-9    # UNDER = projected own x 0.6
    assert p.loc[fade, "exposure"] <= 3.0                                  # FADE = 0-3%
    record = builder.load_record("tnf", "default")
    assert record["war_room_rules_used"] == {"OVER": 1.5, "WITH": 1.0, "UNDER": 0.6, "FADE_MAX": 3.0}
    assert record["late_game_haircut_used"] is False


def test_captain_tiers_and_exposure_overrides(sd):
    by_proj = sorted(SHOWDOWN, key=lambda p: -p[6])
    core = by_proj[0][0]
    other_qb = [p[0] for p in SHOWDOWN if p[2] == "QB"][-1]
    mid = by_proj[8][0]
    s = BuildSettings(captain_tiers={core: "core", other_qb: "other QB"}, exposures={mid: [40, 100]}, **FAST)
    r = builder.build("tnf", s)
    p = r.players.set_index("dfs_id")
    assert 15 <= p.at[core, "cpt_exposure"] <= 25
    assert p.at[other_qb, "cpt_exposure"] <= 5
    assert p.at[mid, "exposure"] >= 40


def test_not_enough_room_is_said_not_hidden(sd):
    r = builder.build("tnf", BuildSettings(min_uniques=6, pool_size=60, workers=1))
    assert r.checks["lineups"] < 20
    assert any("could be built" in w for w in r.warnings)


def test_impossible_settings_stop_with_a_reason(sd):
    with pytest.raises(FileProblem, match="No legal lineup"):
        builder.build("tnf", BuildSettings(salary_floor=50_001, **FAST))


# ---------------------------------------------------------------- snapshot and no hindsight (SPEC 7)

def test_snapshot_copies_and_hashes_the_inputs(sd, home):
    r = builder.build("tnf", BuildSettings(**FAST))
    snap = r.snapshot
    assert {f["role"] for f in snap["files"]} == {"sabersim", "dk_entries"}
    folder = slate.Path(snap["folder"]) if hasattr(slate, "Path") else __import__("pathlib").Path(snap["folder"])
    assert (folder / "snapshot.json").exists() and (folder / "prelock.csv").exists()
    assert all(len(f["sha256"]) == 64 for f in snap["files"])


def test_post_game_export_needs_permission_and_marks_a_refill(home, downloads):
    files = _showdown_slate(downloads)
    b.sabersim_csv(files[0], b.showdown_players(SHOWDOWN))                 # now it has Actual scores
    slate.import_files("old", files)
    with pytest.raises(FileProblem, match="pre-lock export"):
        builder.build("old", BuildSettings(**FAST))
    r = builder.build("old", BuildSettings(allow_post_game_export=True, **FAST))
    assert any("refill" in w for w in r.warnings)
    assert builds.load_meta("old")["build:default"]["refill"] is True
    assert "actual" not in r.players.columns


def test_the_grader_sees_dfs_lab_builds(sd):
    builder.build("tnf", BuildSettings(name="default", **FAST))
    keys = {k for k, _, _ in grade.available_sets("tnf")}
    assert "build:default" in keys
    meta = builds.load_meta("tnf")["build:default"]
    assert (meta["name"], meta["method"]) == ("DFS Lab default", "DFS Lab default")


# ---------------------------------------------------------------- classic

def test_classic_build_is_legal_with_stacks_and_slot_order(classic):
    r = builder.build("main", BuildSettings(n_lineups=20, **FAST))
    lk = _lookup(r)
    rows = list(csv.reader(open(r.csv_path)))
    assert rows[0] == ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]      # no entries: plain file
    assert any("no entries" in w for w in r.warnings)
    for row in rows[1:]:
        ids = [int(x) for x in row]
        assert legal.problems(ids, lk, "classic") == []
        pos = [lk.at[i, "pos"] for i in ids]
        assert pos[:7] == ["QB", "RB", "RB", "WR", "WR", "WR", "TE"] and pos[8] == "DST"
        assert pos[7] in ("RB", "WR", "TE")
        qb = lk.loc[ids[0]]
        mates = lk.loc[ids][(lk.loc[ids, "team"] == qb["team"]) & lk.loc[ids, "pos"].isin(["WR", "TE"])]
        assert len(mates) >= 1                                              # QB + at least 1 pass-catcher


def test_bring_back_and_ownership_cap(classic):
    r = builder.build("main", BuildSettings(n_lineups=15, bring_back=True, max_total_own=110, **FAST))
    lk = _lookup(r)
    for lu in r.lineups:
        rows = r.pool.loc[lu]
        qb = rows[rows["pos"] == "QB"].iloc[0]
        assert ((rows["team"] == qb["opp"]) & rows["pos"].isin(["RB", "WR", "TE"])).any()
        assert rows["own"].sum() <= 110 + 1e-9


def test_flex_goes_to_the_late_game(classic):
    r = builder.build("main", BuildSettings(n_lineups=15, **FAST))
    lk = r.pool.set_index("dfs_id")
    for row in list(csv.reader(open(r.csv_path)))[1:]:
        ids = [int(x) for x in row]
        flex = ids[7]
        same_pos = [i for i in ids[:7] if lk.at[i, "pos"] == lk.at[flex, "pos"]]
        if any(lk.at[i, "late"] for i in same_pos):
            assert lk.at[flex, "late"]                                     # FLEX holds a 4:25 player if it can


def test_game_coverage_floor(classic):
    s = BuildSettings(n_lineups=20, coverage_total=0, coverage_per_lineup=2.0, **FAST)
    r = builder.build("main", s)
    per = {c["Game"]: c["Players per lineup"] for c in r.checks["coverage"]}
    assert all(v >= 2.0 for v in per.values()), per


def test_late_game_ownership_haircut(classic):
    r = builder.build("main", BuildSettings(n_lineups=10, late_haircut=0.4, **FAST))
    p = r.players.set_index("name")
    raw = {pl[1]: pl for pl in CLASSIC}
    assert p.loc["SEA QB1", "own"] == pytest.approx(10.5 * 0.6)            # SEA@ARI kicks off 4:25
    assert p.loc["DAL QB1", "own"] == pytest.approx(10.5)
    assert builder.load_record("main", "default")["late_game_haircut_used"] is True


def test_chalk_warning(classic):
    r = builder.build("main", BuildSettings(n_lineups=10, chalk_own=10, chalk_margin=10, **FAST))
    assert r.checks["chalk"] and "projected field ownership" in r.checks["chalk"][0]


def test_simulation_noise(classic):
    r = builder.build("main", BuildSettings(n_lineups=10, noise="simulations", pool_size=200, workers=1))
    assert r.checks["legal"] == 10


def test_no_entries_file_writes_a_plain_lineup_file(home, downloads):
    pre = downloads / "prelock.csv"
    b.sabersim_csv(pre, CLASSIC, actuals=False)
    slate.import_files("nofile", [pre])
    r = builder.build("nofile", BuildSettings(n_lineups=8, **FAST))
    rows = list(csv.reader(open(r.csv_path)))
    assert rows[0] == rosters.SLOTS["classic"] and len(rows) == 9


# ---------------------------------------------------------------- ownership check and snapshot flag

def test_ownership_history_and_summary(home, classic_slate):
    from test_grade import FIELD, LINEUP
    from conftest import classic_standings_players
    rows = b.standings_rows([(*r, LINEUP) for r in FIELD], classic_standings_players())
    b.standings_zip(classic_slate["standings"], "195648006", rows)
    slate.import_files("wk2", classic_slate.values())
    hist = ownership.history("classic")
    row = hist.iloc[0]
    assert (row["Contest"], row["Top-1% lineups"], row["Avg total own %"]) == ("195648006", 1, 229.5)


def test_compare_flags_a_build_whose_inputs_changed(classic, downloads):
    builder.build("main", BuildSettings(n_lineups=10, **FAST))
    post = downloads / "post.csv"
    b.sabersim_csv(post, [(*p[:6], p[6], p[7] + 3, p[8]) for p in CLASSIC])  # new projections, with results
    later = downloads / "prelock later.csv"
    b.sabersim_csv(later, [(*p[:6], p[6], p[7] + 3, p[8]) for p in CLASSIC], actuals=False)
    pick = {pos: [p[1] for p in CLASSIC if p[2] == pos and p[3] == "DAL"] for pos in ("QB", "RB", "WR", "TE", "DST")}
    lineup = [("QB", pick["QB"][0]), ("RB", pick["RB"][0]), ("RB", pick["RB"][1]), ("WR", pick["WR"][0]),
              ("WR", pick["WR"][1]), ("WR", pick["WR"][2]), ("TE", pick["TE"][0]), ("FLEX", pick["WR"][3]),
              ("DST", pick["DST"][0])]
    rows = b.standings_rows([("1", "1", "x", "150", b.lineup_string(lineup))], [])
    b.standings_zip(downloads / "contest-standings-777777.zip", "777777", rows)
    slate.import_files("main", [post, later, downloads / "contest-standings-777777.zip"])
    builder.build("main", BuildSettings(name="b2", n_lineups=5, **FAST))
    c = compare.compare("main", "777777", ["build:default", "build:b2"], record=False)
    assert any("changed after the build" in w and "DFS Lab build: default" in w for w in c.warnings)
    assert not any("DFS Lab build: b2" in w for w in c.warnings)
