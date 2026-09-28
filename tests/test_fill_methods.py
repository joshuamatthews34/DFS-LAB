"""Milestone 6: fill methods 1 and 3, the field model and simulated ROI (SPEC 5.3, 5.5)."""

import json
import numpy as np
import pytest

import builders as b
from core import builder, builds, fieldmodel, rosters, simcontest, slate
from core.builder import BuildSettings
from core.io_utils import FileProblem
from test_builder import CONTEST, SHOWDOWN, _showdown_slate

PAST = "111222333"
FAST = dict(pool_size=300, workers=1, fill_sims=300, field_sample=1500)


def _own(players):
    """Projected ownership that sums like a real showdown: FLEX 500%, CPT 100%."""
    proj = {p[0]: p[6] for p in players}
    total = sum(proj.values())
    own = {pid: round(500 * v / total, 2) for pid, v in proj.items()}
    own.update({pid + 500: round(100 * v ** 2 / sum(x ** 2 for x in proj.values()), 2) for pid, v in proj.items()})
    return own


def _nearly_full_lineups(players, n, seed=0):
    """Random legal showdown lineups, keeping the ones that spend the most (a real field's habit)."""
    rng = np.random.default_rng(seed)
    sal = np.array([p[5] for p in players])
    team = np.array([p[3] for p in players])
    picks = np.argsort(rng.random((200_000, len(players))), axis=1)[:, :6]
    salary = sal[picks[:, 0]] * 3 // 2 + sal[picks[:, 1:]].sum(axis=1)
    ok = (salary <= 50_000) & (team[picks] != team[picks[:, :1]]).any(axis=1)
    picks, salary = picks[ok], salary[ok]
    best = picks[np.argsort(-salary, kind="stable")[:n]]
    return [[("CPT", players[r[0]][1])] + [("FLEX", players[i][1]) for i in r[1:]] for r in best]


def _standings(path, contest, lineups):
    entries = [(str(i + 1), str(7_000_000 + i), f"user{i}", f"{200 - i * 0.01:.2f}", b.lineup_string(lu))
               for i, lu in enumerate(lineups)]
    players = [(p[1], "FLEX", 10.0, p[8]) for p in SHOWDOWN[:5]]
    b.standings_zip(path, contest, b.standings_rows(entries, players))


@pytest.fixture
def past(home, downloads, tmp_path):
    """An earlier showdown slate whose standings show the field's habits."""
    d = tmp_path / "past"
    d.mkdir()
    ss = d / "past-sabersim.csv"
    b.sabersim_csv(ss, b.showdown_players(SHOWDOWN))
    st = d / f"contest-standings-{PAST}.zip"
    _standings(st, PAST, _nearly_full_lineups(SHOWDOWN, 600))
    slate.import_files("past-sd", [ss, st])
    return d


@pytest.fixture
def tnf(home, downloads):
    files = _showdown_slate(downloads)
    b.sabersim_csv(files[0], b.showdown_players(SHOWDOWN), actuals=False, own=_own(SHOWDOWN))
    pay = downloads / f"payouts-{CONTEST}.csv"
    b.payouts_csv(pay, [[1, 1, "$500"], [2, 5, "$60"], [6, 30, "$15"], [31, 200, "$8"]])
    slate.import_files("tnf", files + [pay])
    return downloads


# ---------------------------------------------------------------- scoring pieces

def test_counts_match_brute_force():
    rng = np.random.default_rng(1)
    field = np.sort(rng.integers(0, 50, size=(4, 30)), axis=1)
    q = rng.integers(-5, 55, size=(7, 4))
    h, e = simcontest._count(field, q)
    for i in range(7):
        for s in range(4):
            assert h[i, s] == (field[s] > q[i, s]).sum()
            assert e[i, s] == (field[s] == q[i, s]).sum()


def _scorer(field_points, prizes, fee=5.0, size=None):
    """A scorer where every 'lineup' is one player, so scores are easy to set. field_points: sims x F."""
    fp = np.asarray(field_points, dtype=float)
    cents = simcontest.player_cents(fp)
    F = fp.shape[1]
    terms = simcontest.ContestTerms("1", size=size or F, fee=fee, prizes=np.array(prizes, dtype=float))
    return simcontest.Scorer(cents, np.arange(F)[:, None], np.full((F, 1), 2), terms, size or F), cents


def _mine(points):
    """Your lineups' half-hundredth scores (lineups x sims)."""
    return (2 * simcontest.player_cents(np.asarray(points, dtype=float))).astype(np.int32)


def test_prizes_and_ties_split():
    sc, _ = _scorer([[90, 80, 70]], [100, 50, 10])
    assert sc.prize(np.array([0.0]), np.array([1.0]))[0] == 100
    assert sc.prize(np.array([0.0]), np.array([2.0]))[0] == 75           # ranks 1-2 shared
    assert sc.prize(np.array([2.5]), np.array([1.0]))[0] == 5            # halfway past the last paid rank
    ev = sc.evaluate(_mine([[85], [85]]))                                 # two of yours tie for 2nd
    assert list(ev["ev"]) == [30.0, 30.0]                                 # (50 + 10) / 2 each
    ev = sc.evaluate(_mine([[80]]))                                       # ties the field's 80
    assert ev["ev"][0] == 30.0


def test_a_field_sample_stands_for_the_whole_contest():
    # 4 field lineups standing for 400 entries: each counts as 100.
    sc, _ = _scorer([[100, 90, 80, 70]], [1000] + [1] * 199, size=400)
    Hf, _ = sc.against_field(_mine([[85]]))
    assert Hf[0, 0] == 200
    assert sc.top1(Hf)[0, 0] == np.False_
    Hf, _ = sc.against_field(_mine([[95]]))
    assert Hf[0, 0] == 100 and not sc.top1(Hf)[0, 0]                     # 100 of 400 above: top 25%
    Hf, _ = sc.against_field(_mine([[101]]))
    assert Hf[0, 0] == 0 and sc.top1(Hf)[0, 0]


def test_roi_value_is_the_exact_gain_of_the_set():
    rng = np.random.default_rng(3)
    field = rng.normal(100, 20, size=(200, 300)).round(2)
    sc, _ = _scorer(field, [300, 100, 60, 40, 30, 20, 10, 10, 5, 5] + [2] * 40, size=300)
    S = _mine(rng.normal(105, 25, size=(12, 200)).round(2))
    v = simcontest.ROIValue(sc, S)
    total = lambda idx: sc.evaluate(S[idx])["ev"].sum() if idx else 0.0   # noqa: E731
    chosen = []
    for i in (4, 7, 1):
        assert v.exact(i) == pytest.approx(total(chosen + [i]) - total(chosen), abs=1e-6)
        v.add(i)
        chosen.append(i)
    for i in (0, 2, 11):
        assert v.exact(i) == pytest.approx(total(chosen + [i]) - total(chosen), abs=1e-6)


def test_top1_value_counts_new_slates():
    rng = np.random.default_rng(4)
    field = rng.normal(100, 20, size=(100, 200))
    sc, _ = _scorer(field, [10], size=200)
    S = _mine(rng.normal(110, 25, size=(6, 100)).round(2))
    v = simcontest.Top1Value(sc, S)
    hits = sc.top1(sc.against_field(S)[0])
    v.add(2)
    for i in (0, 5):
        assert v.exact(i) == (hits[i] & ~hits[2]).sum()


# ---------------------------------------------------------------- field model

def test_habits_come_from_other_slates_only(past, tnf):
    h = fieldmodel.learn_habits(rosters.SHOWDOWN, "tnf")
    assert h.lineups == 600 and h.sources == ["past-sd contest 111222333 (600 lineups)"]
    left = [k // fieldmodel.N_CATS[rosters.SHOWDOWN] for k in h.counts]
    assert min(left) == 0                                                  # nearly full salary is common
    with pytest.raises(FileProblem, match="standings"):
        fieldmodel.learn_habits(rosters.SHOWDOWN, "past-sd")               # tnf has no standings
    with pytest.raises(FileProblem, match="standings"):
        fieldmodel.learn_habits(rosters.CLASSIC, "tnf")                    # no classic standings anywhere


def test_synthetic_field_follows_ownership_and_habits(past, tnf):
    players, ss, ent, tags, _ = builder.read_snapshot(builder.make_snapshot("tnf", "t"))
    base, fmt, _ = builder.prepare(players, ss, ent, tags, BuildSettings())
    fp = fieldmodel.field_players(players, base, fmt)
    h = fieldmodel.learn_habits(fmt, "tnf")
    f = fieldmodel.synthetic_field(fp, fmt, h, 3000, seed=5)
    assert len(f.rows) == 3000 and not f.notes

    # Every field lineup is legal.
    sal, team, base_id, slot = (fp[c].to_numpy() for c in ("salary", "team", "base_id", "slot"))
    assert (sal[f.rows].sum(axis=1) <= 50_000).all()
    assert (slot[f.rows[:, 0]] == "CPT").all() and (slot[f.rows[:, 1:]] == "FLEX").all()
    assert all(len(set(r)) == 6 for r in base_id[f.rows])
    assert all(len(set(r)) == 2 for r in team[f.rows])

    # Its salary/stack shapes match the past field's, bin by bin.
    a = fieldmodel._arrays(fp)
    codes = fieldmodel.shape_codes(fmt, a["salary"][f.rows], a["team"][f.rows], a["opp"][f.rows],
                                   a["is_pc"][f.rows], a["is_skill"][f.rows])
    got = {c: n / len(codes) for c, n in zip(*np.unique(codes, return_counts=True))}
    want = h.shares()
    assert sum(abs(got.get(k, 0) - want.get(k, 0)) for k in set(got) | set(want)) < 0.02

    # Ownership stays close to projected ownership.
    exp, own = f.exposure(), fp["own"].to_numpy()
    assert np.corrcoef(exp, own)[0, 1] > 0.9
    assert f.info["ownership_miss"] < 6


# ---------------------------------------------------------------- builds

def _legal(r):
    lk = r.pool.set_index("dfs_id")[["base_id", "pos", "team", "opp", "salary", "slot"]].rename(
        columns={"slot": "roster_slot"})
    from core import legal
    return all(not legal.problems(ids, lk, r.fmt) for ids in r.lineup_ids())


def test_roi_and_portfolio_fills_beat_projection_at_their_own_goal(past, tnf):
    common = dict(contest_size=1000, **FAST)
    proj = builder.build("tnf", BuildSettings(name="proj", **common))
    roi = builder.build("tnf", BuildSettings(name="roi", fill="roi", **common))
    port = builder.build("tnf", BuildSettings(name="port", fill="portfolio", **common))
    for r in (proj, roi, port):
        assert r.checks["lineups"] == 20 and r.checks["duplicates"] == 0 and _legal(r)
        assert r.sim["field"] == "synthetic" and r.sim["contest"] == CONTEST and r.sim["fee"] == 5.0
        assert r.sim["contest_size"] == 1000 and r.sim["field_lineups"] == 1000
        assert not r.hindsight
    # Same candidates and simulated slates, so each method wins at what it optimizes.
    assert roi.sim["expected_winnings"] >= proj.sim["expected_winnings"]
    assert port.sim["set_top1_chance"] >= proj.sim["set_top1_chance"]
    assert list(roi.lineup_sim.columns) == ["Sim top 1% %", "Sim ROI %"]

    rec = builder.load_record("tnf", "roi")
    assert rec["fill_method"] == "top by simulated ROI" and rec["simulated"]["roi"] == roi.sim["roi"]
    meta = builds.load_meta("tnf")
    assert meta["build:port"]["method"] == "DFS Lab portfolio (top-1% chance)"
    assert meta["build:roi"]["hindsight"] is False


def test_payouts_are_part_of_the_snapshot(tnf):
    m = builder.make_snapshot("tnf", "x")
    assert [f["file"] for f in m["files"] if f["role"] == "payouts"] == [f"payouts-{CONTEST}.csv"]
    *_, payouts = builder.read_snapshot(m)
    assert list(payouts[CONTEST][:6]) == [500, 60, 60, 60, 60, 15] and len(payouts[CONTEST]) == 200


def test_roi_fill_says_what_it_needs(past, tnf):
    with pytest.raises(FileProblem, match="contest size"):
        builder.build("tnf", BuildSettings(fill="roi", **FAST))
    with pytest.raises(FileProblem, match="payout file for contest 999"):
        builder.build("tnf", BuildSettings(fill="roi", roi_contest="999", contest_size=100, **FAST))


def test_without_past_standings(tnf):
    with pytest.raises(FileProblem, match="standings"):
        builder.build("tnf", BuildSettings(fill="portfolio", **FAST))
    r = builder.build("tnf", BuildSettings(**FAST))                        # method 2 still builds
    assert r.checks["lineups"] == 20 and "standings" in r.sim["skipped"]


def test_a_real_field_backtest_is_marked_hindsight(tnf, downloads):
    st = downloads / f"contest-standings-{CONTEST}.zip"
    _standings(st, CONTEST, _nearly_full_lineups(SHOWDOWN, 400, seed=9))
    slate.import_files("tnf", [st])
    r = builder.build("tnf", BuildSettings(name="bt", fill="portfolio", field_source="real", **FAST))
    assert r.hindsight and r.sim["field"] == "real" and r.sim["field_lineups"] == 400
    assert r.sim["contest_size"] == 400 and "roi" in r.sim                 # the real field knows its size
    assert any("hindsight" in w for w in r.warnings)
    assert builds.load_meta("tnf")["build:bt"]["hindsight"] is True
    assert json.loads((slate.slate_dir("tnf") / "builds" / "dfslab-bt.json").read_text())["hindsight"] is True


def test_classic_field_stacks_like_the_past_field(home, downloads, tmp_path):
    players = b.synthetic_players(seed=2)
    by = {g: [p for p in players if p[2] == g] for g in ("QB", "RB", "WR", "TE", "DST")}
    rng = np.random.default_rng(0)
    past = []
    while len(past) < 400:                  # every past lineup: QB + 2 of his WR/TE, $0-99 left or $100-299
        qb = by["QB"][rng.integers(len(by["QB"]))]
        mates = [p for p in by["WR"] + by["TE"] if p[3] == qb[3]]
        two = [mates[i] for i in rng.choice(len(mates), 2, replace=False)]
        rest = {"RB": 3, "WR": 3 - sum(p[2] == "WR" for p in two), "TE": 1 - sum(p[2] == "TE" for p in two)}
        if min(rest.values()) < 0:
            continue
        pick = list(two)
        for g, k in rest.items():
            pool = [p for p in by[g] if p[3] not in (qb[3], qb[4]) and p not in pick]
            pick += [pool[i] for i in rng.choice(len(pool), k, replace=False)]
        dst = by["DST"][rng.integers(len(by["DST"]))]
        lu = [qb] + pick + [dst]
        if sum(p[5] for p in lu) >= 49_700 and sum(p[5] for p in lu) <= 50_000:
            rbs = [p for p in lu if p[2] == "RB"]
            past.append([("FLEX" if p is rbs[2] else p[2], p[1]) for p in lu])       # the third RB is the FLEX
    d = tmp_path / "pastc"
    d.mkdir()
    b.sabersim_csv(d / "ss.csv", players)
    entries = [(str(i + 1), str(9_000_000 + i), "u", "150", b.lineup_string(lu)) for i, lu in enumerate(past)]
    b.standings_zip(d / "contest-standings-190000901.zip", "190000901",
                    b.standings_rows(entries, [(players[0][1], "QB", 10.0, players[0][8])]))
    slate.import_files("past-main", [d / "ss.csv", d / "contest-standings-190000901.zip"])

    h = fieldmodel.learn_habits(rosters.CLASSIC, "main")
    assert h.lineups == 400
    assert set(h.table()["Field habit"].str.split(", ").str[1]) == {"QB + 2"}
    own = {p[0]: 30.0 if p[2] in ("QB", "TE", "DST") else 20.0 for p in players}
    b.sabersim_csv(downloads / "pre.csv", players, actuals=False, own=own)
    slate.import_files("main", [downloads / "pre.csv"])
    players_, ss, ent, tags, _ = builder.read_snapshot(builder.make_snapshot("main", "t"))
    base, fmt, _ = builder.prepare(players_, ss, ent, tags, BuildSettings())
    fp = fieldmodel.field_players(players_, base, fmt)
    f = fieldmodel.synthetic_field(fp, fmt, h, 2000, seed=1)
    assert len(f.rows) == 2000 and not f.notes
    a = fieldmodel._arrays(fp)
    r = f.rows
    codes = fieldmodel.shape_codes(fmt, a["salary"][r], a["team"][r], a["opp"][r], a["is_pc"][r], a["is_skill"][r])
    assert set(np.unique(codes)) <= set(h.counts)                          # QB + 2, nearly full salary
    pos = fp["pos"].to_numpy()[r]
    assert (pos[:, 0] == "QB").all() and ((pos == "DST").sum(axis=1) == 1).all()
    assert ((pos == "RB").sum(axis=1) >= 2).all() and ((pos == "WR").sum(axis=1) >= 3).all()
    assert (np.isin(pos, ["RB", "WR", "TE"]).sum(axis=1) == 7).all()
    assert all(len(set(x)) == 9 for x in r)


def test_cli_build_with_a_fill_method(past, tnf, capsys):
    from core import cli
    code = cli.main(["build", "tnf", "--name", "cli", "--fill", "roi", "--contest-size", "1000", "--pool", "300",
                     "--fill-sims", "300", "--field-sample", "1000"])
    out = capsys.readouterr().out
    assert code == 0
    assert "simulated ROI" in out and "chance of 1+ top-1% finish" in out and "Upload file:" in out
    code = cli.main(["build", "tnf", "--fill", "roi", "--pool", "300"])
    assert code == 1 and "contest size" in capsys.readouterr().out


def test_scoring_against_a_contest_you_are_not_filling(past, tnf, downloads):
    # A second contest in the entries file, with its own fee; fill only the first, score the second.
    import csv
    ent = downloads / "DKEntries.csv"
    rows = list(csv.reader(ent.open()))
    rows[20][:4] = ["5000000099", "NFL Showdown $20 Single Entry", "199000001", "$20"]
    with ent.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    b.payouts_csv(downloads / "payouts-199000001.csv", [[1, 1, "$1,000"], [2, 10, "$40"]])
    slate.import_files("tnf", [ent, downloads / "payouts-199000001.csv"])
    r = builder.build("tnf", BuildSettings(fill="roi", contests=[CONTEST], roi_contest="199000001",
                                           contest_size=500, **FAST))
    assert r.sim["contest"] == "199000001" and r.sim["fee"] == 20.0
    assert r.sim["contest_name"] == "NFL Showdown $20 Single Entry" and r.checks["lineups"] == 19
