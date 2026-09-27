"""Late-swap grader (SPEC 6.6).

Pairs each lineup before the swap with the same entry after it: by Entry ID, or, when the
IDs were reshuffled, by the players in games that had already started (they can't change).
Every changed pair is scored with actual points; a swap that produces an illegal roster
is rejected and left out of the totals.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import detect, grade, legal, slate

_KICKOFF = re.compile(r"(\d{2}/\d{2}/\d{4} \d{2}:\d{2}[AP]M)")
SAME = 0.005


@dataclass
class SwapResult:
    before: str
    after: str
    pairs: pd.DataFrame
    unpaired_before: list
    unpaired_after: list
    locked_through: datetime = None
    warnings: list = field(default_factory=list)

    @property
    def summary(self):
        p = self.pairs
        if p.empty:
            return {"paired": 0, "changed": 0, "better": 0, "worse": 0, "no_change_in_points": 0,
                    "rejected": 0, "net": 0.0}
        changed = p[p["changed"]]
        ok = changed[changed["legal"]]
        return {"paired": len(p), "changed": len(changed), "better": int((ok["delta"] > SAME).sum()),
                "worse": int((ok["delta"] < -SAME).sum()), "no_change_in_points": int((ok["delta"].abs() <= SAME).sum()),
                "rejected": int((~changed["legal"]).sum()), "net": round(float(ok["delta"].sum()), 2)}

    def headline(self):
        s = self.summary
        return (f"{s['changed']} of {s['paired']} paired entries changed, net {s['net']:+,.1f} points "
                f"({s['better']} better, {s['worse']} worse)")


def kickoffs(parsed):
    """DFS ID -> kickoff time, from DraftKings' player pool in the entries files."""
    out = {}
    for _, _, d in parsed[detect.DK_ENTRIES]:
        if d.pool is None:
            continue
        for pid, info in zip(d.pool["dfs_id"], d.pool["game_info"]):
            m = _KICKOFF.search(str(info))
            if m:
                out[int(pid)] = datetime.strptime(m.group(1), "%m/%d/%Y %I:%M%p")
    return out


def kickoff_times(slate_id, root=None):
    return sorted(set(kickoffs(slate.load_parsed(slate_id, root)).values()))


def grade_swap(slate_id, before_key, after_key, locked_through=None, root=None):
    parsed = slate.load_parsed(slate_id, root)
    book = grade.build_book(parsed)
    (before, after), problems = grade.resolve_sets(slate_id, [before_key, after_key], parsed, book, root)
    p, fmt = book.players, book.fmt
    kick = kickoffs(parsed)
    if locked_through is None and kick:
        used = {i for s in (before, after) for lu in s.lineups for i in lu if i in kick}
        locked_through = min(kick[i] for i in used) if used else None

    def early(ids):
        """Players whose games had started by the swap (they can't be swapped)."""
        return frozenset(int(p.at[i, "base_id"]) for i in ids
                         if i in p.index and i in kick and locked_through and kick[i] <= locked_through)

    result = SwapResult(before.label, after.label, pd.DataFrame(), [], [], locked_through)
    for key in (before_key, after_key):
        result.warnings += problems.get(key, [])

    pairs, used_after = [], set()
    after_by_entry = {e: j for j, e in enumerate(after.entry_ids) if e}
    leftovers = []
    for i, e in enumerate(before.entry_ids):
        j = after_by_entry.get(e) if e else None
        if j is not None and j not in used_after:
            pairs.append((i, j, "Entry ID"))
            used_after.add(j)
        else:
            leftovers.append(i)

    # Reshuffled IDs (no Entry ID matches at all): match on players in games that had already started.
    # When most IDs match, the leftovers are entries that only exist on one side, so they stay unpaired.
    reshuffled = not pairs
    if leftovers and reshuffled and kick:
        pool = defaultdict(list)
        for j in range(len(after.lineups)):
            if j not in used_after:
                pool[early(after.lineups[j])].append(j)
        crowded, still = 0, []
        for i in leftovers:
            key = early(before.lineups[i])
            if key and pool.get(key):
                crowded += len(pool[key]) > 1
                j = pool[key].pop(0)
                pairs.append((i, j, "early-game players"))
                used_after.add(j)
            else:
                still.append(i)
        leftovers = still
        if crowded:
            result.warnings.append(f"{crowded} lineup(s) shared their early-game players with others, so they "
                                   f"were paired in file order.")
    elif leftovers and reshuffled:
        result.warnings.append("No Entry IDs match, and there's no kickoff information (from a DraftKings "
                               "entries file) to match the lineups by early-game players.")

    rows, moved_early = [], 0
    for i, j, how in pairs:
        a, b = before.lineups[i], after.lineups[j]
        entry = before.entry_ids[i] or after.entry_ids[j]
        contest = before.contest_ids[i] or after.contest_ids[j]
        if not all(x in p.index for x in (*a, *b)):
            rows.append({"Entry ID": entry, "Contest": contest, "Matched by": how, "changed": True, "legal": False,
                         "Why rejected": "a DFS ID isn't in the SaberSim export", "Before": _score(a, p),
                         "After": _score(b, p), "delta": 0.0, "Swapped out": "", "Swapped in": ""})
            continue
        if kick and early(a) != early(b):
            moved_early += 1
        changed = grade._identity(a, p, fmt) != grade._identity(b, p, fmt)
        reasons = legal.problems(b, p, fmt) if changed else []
        sa, sb = _score(a, p), _score(b, p)
        base_a = {int(p.at[x, "base_id"]) for x in a}
        base_b = {int(p.at[x, "base_id"]) for x in b}
        rows.append({
            "Entry ID": entry, "Contest": contest, "Matched by": how, "changed": changed, "legal": not reasons, "Why rejected": "; ".join(reasons),
            "Before": sa, "After": sb, "delta": round(sb - sa, 2) if changed else 0.0,
            "Swapped out": ", ".join(p.at[x, "name"] for x in sorted(base_a - base_b)),
            "Swapped in": ", ".join(p.at[x, "name"] for x in sorted(base_b - base_a)),
        })
    if moved_early:
        result.warnings.append(f"{moved_early} paired entr{'y' if moved_early == 1 else 'ies'} changed players "
                               f"in games that had already started by {locked_through:%a %I:%M %p}. Check the "
                               f"lock time, or whether these really are the same entries.")
    result.pairs = pd.DataFrame(rows)
    result.unpaired_before = [before.entry_ids[i] or f"lineup {i + 1}" for i in leftovers]
    result.unpaired_after = [after.entry_ids[j] or f"lineup {j + 1}" for j in range(len(after.lineups))
                             if j not in used_after]
    return result


def _score(ids, p):
    missing = [i for i in ids if i not in p.index]
    if missing:
        return float("nan")
    return round(float(p.loc[list(ids), "points"].sum()), 2)


def changed_table(result):
    """Changed pairs, biggest gains first, for display."""
    p = result.pairs
    if p.empty:
        return p
    t = p[p["changed"]].copy()
    t["Gain"] = t["delta"]
    t["Status"] = t["legal"].map({True: "", False: "rejected"})
    cols = ["Entry ID", "Contest", "Matched by", "Before", "After", "Gain", "Swapped out", "Swapped in", "Status",
            "Why rejected"]
    return t[cols].sort_values("Gain", ascending=False).reset_index(drop=True)


def to_text(result):
    s = result.summary
    lines = [f"Late swap: {result.before}  ->  {result.after}", result.headline()]
    if result.locked_through:
        lines.append(f"Games locked at the swap: through {result.locked_through:%a %b %d %I:%M %p}")
    if s["rejected"]:
        lines.append(f"{s['rejected']} swap(s) rejected for an illegal roster (not counted).")
    if result.unpaired_before or result.unpaired_after:
        lines.append(f"Unpaired: {len(result.unpaired_before)} before, {len(result.unpaired_after)} after.")
    lines += [f"! {w}" for w in result.warnings]
    t = changed_table(result)
    if not t.empty:
        lines += ["", t.to_string(index=False)]
    return "\n".join(lines)
