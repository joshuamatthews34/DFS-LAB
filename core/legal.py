"""Is a lineup legal on DraftKings? (SPEC 4.1 classic, 4.2 showdown)

Position counts rather than slot order are checked, so lineups read back from
standings files (which list players in their own order) can be checked too.
"""

from collections import Counter

from . import rosters

CLASSIC_COUNTS = {"QB": (1, 1), "RB": (2, 3), "WR": (3, 4), "TE": (1, 2), "DST": (1, 1)}


def problems(ids, players, fmt):
    """Reasons `ids` isn't a legal lineup (empty list = legal).

    players: table indexed by DFS ID with pos, team, opp, salary, roster_slot and base_id
    (base_id is the FLEX ID for a showdown captain, else the ID itself).
    """
    missing = [i for i in ids if i not in players.index]
    if missing:
        return [f"DFS ID(s) {', '.join(map(str, missing))} aren't on the slate"]
    rows = players.loc[list(ids)]
    out = []
    if rows["base_id"].nunique() != len(ids):
        out.append("the same player is in it twice")
    salary = int(rows["salary"].sum())
    if salary > rosters.SALARY_CAP:
        out.append(f"salary ${salary:,} is over the ${rosters.SALARY_CAP:,} cap")
    if fmt == rosters.SHOWDOWN:
        if len(ids) != 6:
            out.append(f"{len(ids)} players instead of 6")
        slots = list(rows["roster_slot"])
        if slots[:1] != ["CPT"] or any(s != "FLEX" for s in slots[1:]):
            out.append("it needs exactly one captain (first) and five FLEX players")
        if rows["team"].nunique() < 2:
            out.append("both teams must be represented")
        return out

    if len(ids) != 9:
        out.append(f"{len(ids)} players instead of 9")
    counts = Counter(rows["pos"])
    for pos, (lo, hi) in CLASSIC_COUNTS.items():
        if not lo <= counts.get(pos, 0) <= hi:
            out.append(f"{counts.get(pos, 0)} {pos} (allowed {lo}" + (f"-{hi})" if hi != lo else ")"))
    other = set(counts) - set(CLASSIC_COUNTS)
    if other:
        out.append("positions that can't be rostered: " + ", ".join(sorted(other)))
    games = {tuple(sorted((t, o))) for t, o in zip(rows["team"], rows["opp"])}
    if len(games) < 2:
        out.append("players must come from at least 2 games")
    return out
