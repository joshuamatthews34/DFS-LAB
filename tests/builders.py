"""Write small, fake-but-realistic slate files for tests.

Formats copy the quirks of real files: byte-order marks, CRLF line endings,
DK's instruction column and player pool, 'Rams  (id)' DST cells, stray
backslashes in SaberSim headers.
"""

import csv
import io
import zipfile

from core.importers.sabersim import REQUIRED

# id, name, pos, team, opp, salary, ss_proj, my_proj, actual
CLASSIC_PLAYERS = [
    (1001, "Dak Prescott", "QB", "DAL", "NYG", 6500, 19.1, 19.8, 22.34),
    (1002, "CeeDee Lamb", "WR", "DAL", "NYG", 7000, 17.0, 17.5, 18.5),
    (1003, "Jake Ferguson", "TE", "DAL", "NYG", 4000, 9.0, 9.2, 9.1),
    (1004, "Kenneth Walker III", "RB", "SEA", "ARI", 6000, 14.0, 14.4, 15.2),
    (1005, "Jaxon Smith-Njigba", "WR", "SEA", "ARI", 6000, 16.1, 16.0, 20.0),
    (1006, "Malik Nabers", "WR", "NYG", "DAL", 7000, 18.3, 18.0, 25.3),
    (1007, "Tyrone Tracy Jr.", "RB", "NYG", "DAL", 5000, 12.0, 12.6, 11.0),
    (1008, "Marvin Harrison Jr.", "WR", "ARI", "SEA", 5600, 13.2, 13.0, 7.7),
    (1009, "Trey McBride", "TE", "ARI", "SEA", 5800, 12.9, 13.1, 12.4),
    (1010, "Cowboys", "DST", "DAL", "NYG", 3000, 6.0, 6.2, 5.0),
    (1011, "Kenny Gainwell", "RB", "ARI", "SEA", 4500, 8.0, 8.4, 13.9),
    (1012, "José Pérez", "WR", "ARI", "SEA", 3000, 4.0, 4.0, 0.0),
]
CLASSIC_LINEUP = [1001, 1004, 1007, 1002, 1005, 1006, 1003, 1011, 1010]

# DK's "Game Info": DAL@NYG kicks off at 1:00, SEA@ARI at 4:25 (the late game).
GAME_INFO = {"DAL": "DAL@NYG 09/14/2026 01:00PM ET", "NYG": "DAL@NYG 09/14/2026 01:00PM ET",
             "SEA": "SEA@ARI 09/14/2026 04:25PM ET", "ARI": "SEA@ARI 09/14/2026 04:25PM ET"}


# A realistic right-skewed shape: percentile = projection x multiplier (the mean is the projection).
PERCENTILE_SHAPE = {25: 0.6, 50: 0.9, 75: 1.3, 85: 1.55, 95: 2.0, 99: 2.6}


def sabersim_csv(path, players, blend=True, actuals=True, backslash=True, drop=()):
    extra = ["dk_std", "FD ID", "FD Salary"]
    header = [c for c in REQUIRED if c not in drop] + extra
    out = [[("Saber\\ Total" if backslash and c == "Saber Total" else c) for c in header]]
    for pid, name, pos, team, opp, sal, ss, my, act in players:
        v = {
            "DFS ID": pid, "Name": name, "Pos": pos, "Team": team, "Opp": opp, "Status": "",
            "Salary": sal, "Actual": act if actuals else "", "SS Proj": ss,
            "Live Proj": act if actuals else "", "My Proj": my if blend else ss, "Value": round(ss / sal * 1000, 2),
            "My Own": 10.5, "Adj Own": 11.0, "Min Exp": 0, "Max Exp": 100, "Saber Team": 24.5,
            "Saber Total": 47.5, "dk_points": ss, "dk_std": 7.1, "FD ID": "x", "FD Salary": 1,
        }
        for p, mult in PERCENTILE_SHAPE.items():
            v[f"dk_{p}_percentile"] = round(ss * mult, 2)
        out.append([v.get(c, "") for c in header])
    _write_csv(path, out)


def showdown_players(players):
    """Classic-style player tuples -> SaberSim showdown rows (FLEX + CPT at 1.5x, new IDs)."""
    rows = []
    for pid, name, pos, team, opp, sal, ss, my, act in players:
        rows.append((pid, name, pos, team, opp, sal, ss, my, act))
        rows.append((pid + 500, name, pos, team, opp, sal * 3 // 2, ss * 1.5, my * 1.5, act * 1.5))
    return rows


def dk_entries_csv(path, fmt, entries, pool, reservations=1, fee="$3"):
    """entries: list of (entry_id, contest_id, contest_name, [ids]). pool: list of pool dicts."""
    slots = {"classic": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"],
             "showdown": ["CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"]}[fmt]
    width = 4 + len(slots)
    rows = [["Entry ID", "Contest Name", "Contest ID", "Entry Fee", *slots, "", "Instructions"]]
    left = [[eid, name, cid, fee, *ids] for eid, cid, name, ids in entries]
    left += [["9999999" + str(i), "Reserved", "555", fee, *[""] * len(slots)] for i in range(reservations)]
    right = [["1. Column A lists all of your contest entries for this draftgroup"], [""],
             ["Position", "Name + ID", "Name", "ID", "Roster Position", "Salary", "Game Info", "TeamAbbrev",
              "AvgPointsPerGame"]]
    right += [[p["pos"], f"{p['name']} ({p['id']})", p["name"], p["id"], p["roster"], p["salary"],
               GAME_INFO.get(p["team"], GAME_INFO["DAL"]), p["team"], 10] for p in pool]
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else [""] * width
        r = right[i] if i < len(right) else []
        rows.append(l + [""] + r)
    _write_csv(path, rows, crlf=True)


def pool_from_players(players, roster="classic"):
    out = []
    for pid, name, pos, team, opp, sal, *_ in players:
        out.append({"id": pid, "name": name + (" " if pos == "DST" else ""), "pos": pos, "team": team,
                    "salary": sal, "roster": pos if roster == "classic" else ("CPT" if pid % 1000 >= 500 else "FLEX")})
    return out


def dfsarmy_csv(path, lineups, names):
    rows = [["CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"]]
    for lu in lineups:
        rows.append([f"{names[pid]}{'  ' if names[pid] in ('Cowboys',) else ' '}({pid})" for pid in lu])
    _write_csv(path, rows, bom=True)


def lineup_string(pairs):
    return " ".join(f"{tag} {name}{' ' if tag == 'DST' or name == 'Cowboys' else ''}" for tag, name in pairs).rstrip()


def standings_rows(entries, players):
    """entries: list of (rank, entry_id, name, points, lineup_str). players: list of (name, pos, pct, fpts)."""
    rows = [["Rank", "EntryId", "EntryName", "TimeRemaining", "Points", "Lineup", "", "Player",
             "Roster Position", "%Drafted", "FPTS"]]
    for i in range(max(len(entries), len(players))):
        if i < len(entries):
            rank, entry_id, name, points, lineup = entries[i]
            left = [rank, entry_id, name, "0", points, lineup]
        else:
            left = [""] * 6
        right = [players[i][0], players[i][1], f"{players[i][2]}%", players[i][3]] if i < len(players) else [""] * 4
        rows.append(left + [""] + right)
    return rows


def standings_zip(path, contest_id, rows, empty=False):
    data = b"" if empty else _csv_bytes(rows)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"contest-standings-{contest_id}.csv", data)


def payouts_csv(path, rows):
    _write_csv(path, [["rank_from", "rank_to", "prize"], *rows])


def _csv_bytes(rows, bom=False, crlf=False):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n" if crlf else "\n").writerows(rows)
    return (("﻿" if bom else "") + buf.getvalue()).encode("utf-8")


def _write_csv(path, rows, bom=False, crlf=False):
    path.write_bytes(_csv_bytes(rows, bom=bom, crlf=crlf))


def lineups_csv(path, fmt, lineups, names):
    """A lineup export (header = the roster slots, cells 'Name (id)'), e.g. DFS Army or a SaberSim fill."""
    slots = {"classic": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"],
             "showdown": ["CPT", "FLEX", "FLEX", "FLEX", "FLEX", "FLEX"]}[fmt]
    _write_csv(path, [slots, *[[f"{names[pid]} ({pid})" for pid in lu] for lu in lineups]])


NAMES = {p[0]: p[1] for p in CLASSIC_PLAYERS}


def synthetic_players(games=(("DAL", "NYG"), ("SEA", "ARI")), seed=0, kickers=False, salary_scale=1.0,
                      start_id=2001):
    """A fuller fake slate: per team 2 QB, 3 RB, 5 WR, 2 TE, a DST (and a K). Deterministic."""
    import random
    rng = random.Random(seed)
    layout = [("QB", 2, (5000, 7600), (9, 22)), ("RB", 3, (4000, 8600), (4, 17)), ("WR", 5, (3000, 8900), (3, 18)),
              ("TE", 2, (2500, 6100), (2, 11)), ("DST", 1, (2000, 3600), (4, 8))]
    if kickers:
        layout.append(("K", 1, (3500, 4600), (5, 9)))
    out, pid = [], start_id
    for home, away in games:
        for team, opp in ((home, away), (away, home)):
            for pos, count, (slo, shi), (plo, phi) in layout:
                for i in range(count):
                    salary = int(rng.randrange(slo, shi, 100) * salary_scale) // 100 * 100
                    proj = round(rng.uniform(plo, phi) / (1 + 0.6 * i), 1)
                    name = team if pos == "DST" else f"{team} {pos}{i + 1}"
                    out.append((pid, name, pos, team, opp, salary, proj, proj, round(proj * rng.uniform(0.3, 1.8), 2)))
                    pid += 1
    return out
