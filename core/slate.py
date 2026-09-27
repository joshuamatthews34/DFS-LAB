"""Import a slate's files into DFS Lab and check them (SPEC milestone M1).

import_files() copies files into slates/<slate>/raw/ untouched, then analyze_slate()
reads everything in raw/, cross-checks it, stores it in dfs_lab.db and writes the
file report to slates/<slate>/results/import_report.{txt,json}.
"""

import csv
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import db, detect, rosters
from .importers import entries as entries_imp
from .importers import lineups as lineups_imp
from .importers import payouts as payouts_imp
from .importers import sabersim as sabersim_imp
from .importers import standings as standings_imp
from .importers import warroom as warroom_imp
from .io_utils import UNREADABLE_HINT, FileProblem, sha256_file
from .names import normalize_name
from .report import FileReport, Report

FPTS_TOLERANCE = 0.005     # DraftKings points have 2 decimals
SLATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SUBFOLDERS = ("raw", "prelock", "builds", "results")
LIST_LIMIT = 50


# ---------------------------------------------------------------- locations

def project_root():
    return Path(os.environ.get("DFS_LAB_HOME") or Path(__file__).resolve().parents[1])


def db_path(root=None):
    return Path(root or project_root()) / "dfs_lab.db"


def slate_dir(slate_id, root=None):
    return Path(root or project_root()) / "slates" / slate_id


def list_slates(root=None):
    base = Path(root or project_root()) / "slates"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if (p / "raw").is_dir())


def check_slate_id(slate_id):
    if not SLATE_ID.match(slate_id or ""):
        raise FileProblem("Slate names can use letters, numbers, dots, dashes and underscores, "
                          "e.g. 2026-wk02-main.")


# ---------------------------------------------------------------- import

def import_files(slate_id, paths, root=None):
    """Copy files into the slate's raw/ folder (untouched), then analyze the slate."""
    check_slate_id(slate_id)
    folder = slate_dir(slate_id, root)
    for sub in SUBFOLDERS:
        (folder / sub).mkdir(parents=True, exist_ok=True)
    raw = folder / "raw"
    have = {sha256_file(p): p.name for p in raw.iterdir() if p.is_file()}

    notes, messages = [], []
    for src in map(lambda p: Path(p).expanduser(), paths):
        try:
            size = src.stat().st_size
            if size == 0:
                det = detect.detect(src)
                notes.append(FileReport(src.name, detect.EMPTY, detect.LABELS[detect.EMPTY], 0,
                                        status="error", problems=[det.reason]))
                continue
            digest = sha256_file(src)
            if digest in have:
                messages.append(f"{src.name} was already imported (same content as {have[digest]}); skipped.")
                continue
            dest = _free_name(raw, src.name)
            shutil.copy2(src, dest)
            have[digest] = dest.name
        except OSError:
            notes.append(FileReport(src.name, detect.UNREADABLE, detect.LABELS[detect.UNREADABLE], 0,
                                    status="error", problems=[UNREADABLE_HINT]))
    return analyze_slate(slate_id, root, notes=notes, messages=messages)


def _free_name(folder, name):
    dest = folder / name
    n = 2
    while dest.exists():
        dest = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    return dest


# ---------------------------------------------------------------- analyze

def analyze_slate(slate_id, root=None, notes=(), messages=()):
    check_slate_id(slate_id)
    folder = slate_dir(slate_id, root)
    raw = folder / "raw"
    if not raw.is_dir():
        raise FileProblem(f"There's no slate called {slate_id} yet. Import some files first.")

    report = Report(slate_id, datetime.now().isoformat(timespec="seconds"))
    report.warnings.extend(messages)
    parsed = {k: [] for k in PARSED_KINDS}
    seen = {}
    for path in raw_files(slate_id, root):
        fr, det, data = _read_one(path, seen)
        report.files.append(fr)
        if data is not None:
            parsed[det.kind].append((fr, det, data))
    for note in notes:
        report.files.append(note)
    report.zero_byte_files = [f.name for f in report.files if f.kind == detect.EMPTY]

    _cross_check(report, parsed)

    report_json = json.dumps(report.to_dict(), default=str)
    conn = db.connect(db_path(root))
    try:
        db.replace_slate(conn, slate_id, report.fmt, report.generated_at, report_json, _tables(report, parsed))
    finally:
        conn.close()
    results = folder / "results"
    results.mkdir(exist_ok=True)
    (results / "import_report.json").write_text(json.dumps(report.to_dict(), indent=2, default=str))
    (results / "import_report.txt").write_text(report.to_text() + "\n")
    return report


PARSED_KINDS = (detect.SABERSIM, detect.DK_ENTRIES, detect.LINEUPS, detect.STANDINGS, detect.PAYOUTS,
                detect.WARROOM)


def raw_files(slate_id, root=None):
    """The slate's saved files, oldest first (so 'newest wins' means last in the list)."""
    raw = slate_dir(slate_id, root) / "raw"
    if not raw.is_dir():
        raise FileProblem(f"There's no slate called {slate_id} yet. Import some files first.")
    return sorted((p for p in raw.iterdir() if p.is_file() and not p.name.startswith(".")),
                  key=lambda p: (p.stat().st_mtime, p.name))


def load_parsed(slate_id, root=None, skip=(detect.STANDINGS,)):
    """Parse a slate's saved files. Returns {kind: [(FileReport, Detected, data), ...]} for clean files.

    Standings are skipped by default: they're big, and core.field reads them with a cache.
    """
    parsed = {k: [] for k in PARSED_KINDS}
    seen = {}
    for path in raw_files(slate_id, root):
        if detect.detect(path).kind in skip:
            continue
        fr, det, data = _read_one(path, seen)
        if data is not None and fr.status != "error":
            parsed[det.kind].append((fr, det, data))
    return parsed


def load_report(slate_id, root=None):
    path = slate_dir(slate_id, root) / "results" / "import_report.json"
    if not path.exists():
        return None
    return Report.from_dict(json.loads(path.read_text()))


def _read_one(path, seen):
    size = path.stat().st_size
    digest = sha256_file(path) if size else ""
    det = detect.detect(path)
    fr = FileReport(path.name, det.kind, det.label, size, digest)
    if digest and digest in seen:
        fr.status, fr.summary = "ignored", f"same content as {seen[digest]}, so it's ignored"
        return fr, det, None
    if digest:
        seen[digest] = path.name
    if det.kind in (detect.EMPTY, detect.UNREADABLE, detect.UNKNOWN):
        fr.problem(det.reason)
        return fr, det, None
    try:
        data = _parse(det)
    except FileProblem as e:
        fr.problem(str(e))
        return fr, det, None
    except OSError:
        fr.problem(UNREADABLE_HINT)
        return fr, det, None
    except (ValueError, csv.Error, UnicodeDecodeError) as e:
        fr.problem(f"The file couldn't be parsed ({e}). Download or export it again.")
        return fr, det, None
    for w in getattr(data, "warnings", []):
        fr.warn(w)
    fr.summary = _summary(det, data)
    return fr, det, data


def _parse(det):
    if det.kind == detect.SABERSIM:
        return sabersim_imp.parse(det.path)
    if det.kind == detect.DK_ENTRIES:
        return entries_imp.parse(det.path, det.fmt)
    if det.kind == detect.LINEUPS:
        return lineups_imp.parse(det.path, det.fmt)
    if det.kind == detect.STANDINGS:
        return standings_imp.parse(det.path, det.member, det.contest_id)
    if det.kind == detect.PAYOUTS:
        return payouts_imp.parse(det.path, det.contest_id)
    if det.kind == detect.WARROOM:
        return warroom_imp.parse(det.path)
    raise FileProblem("Unsupported file.")


def _summary(det, data):
    if det.kind == detect.SABERSIM:
        blend = {True: "blend loaded", False: "blend NOT loaded", None: "My Proj blank"}[data.blend_loaded]
        timing = "post-game (has Actual scores)" if data.has_actuals else "pre-game"
        return f"{data.player_count} players, {data.fmt}, {timing}, {blend}"
    if det.kind == detect.DK_ENTRIES:
        contests = len({e.contest_id for e in data.entries})
        extra = f", {data.reservations} blank reservation(s)" if data.reservations else ""
        return f"{len(data.entries)} entries ({data.fmt}) in {contests} contest(s){extra}"
    if det.kind == detect.LINEUPS:
        return f"{len(data.lineups)} lineups ({data.fmt})"
    if det.kind == detect.STANDINGS:
        return (f"contest {data.contest_id or '?'}: {data.entries:,} field lineups ({data.fmt}), "
                f"{data.skipped:,} skipped, winning score {data.top_score}")
    if det.kind == detect.PAYOUTS:
        pool = ((data["rank_to"] - data["rank_from"] + 1) * data["prize_cents"]).sum() / 100
        return f"contest {det.contest_id}: {len(data)} payout rows, ${pool:,.2f} total prizes"
    if det.kind == detect.WARROOM:
        return f"{len(data)} tagged players"
    return ""


# ---------------------------------------------------------------- cross-checks

def _cross_check(report, parsed):
    formats = set()

    # SaberSim: newest pre-game export is the reference; newest post-game export has the scores.
    sabersims = [d for _, _, d in parsed[detect.SABERSIM]]
    pre = [d for d in sabersims if not d.has_actuals]
    post = [d for d in sabersims if d.has_actuals]
    ref = pre[-1] if pre else (post[-1] if post else None)
    report.sabersim_files = len(sabersims)
    known, slot_of, name_of = set(), {}, {}
    if ref is None:
        report.problems.append("No SaberSim player export in this slate. Import it (the post-game export "
                               "for grading, the pre-lock one for building).")
    else:
        report.players = ref.player_count
        report.blend_loaded = ref.blend_loaded
        formats.add(ref.fmt)
        for d in sabersims:
            for row in d.players.itertuples():
                known.add(row.dfs_id)
                slot_of.setdefault(row.dfs_id, row.roster_slot)
                name_of.setdefault(row.dfs_id, row.name)
        if ref.blend_loaded is False:
            report.warnings.append("SaberSim My Proj equals SS Proj on every row: your blend wasn't loaded.")
        if len({d.fmt for d in sabersims}) > 1:
            report.problems.append("The SaberSim exports mix classic and showdown.")

    # DK's own player pool (in entries files) is the authority on CPT/FLEX IDs.
    for _, _, d in parsed[detect.DK_ENTRIES]:
        if d.pool is not None:
            for row in d.pool.itertuples():
                if row.roster_position in ("CPT", "FLEX"):
                    slot_of[row.dfs_id] = row.roster_position
    _check_pool_vs_sabersim(report, parsed, ref)

    entries = _check_entries(report, parsed, known, slot_of, formats)
    _check_lineups(report, parsed, known, slot_of, name_of, formats)
    contests = _check_standings_and_payouts(report, parsed, entries, formats)
    _check_fpts(report, contests, post)
    _check_warroom(report, parsed, ref)

    if len(formats) > 1:
        report.problems.append("These files mix classic and showdown. A slate should be one or the other.")
    report.fmt = formats.pop() if len(formats) == 1 else None


def _check_pool_vs_sabersim(report, parsed, ref):
    if ref is None:
        return
    ss = ref.players.set_index("dfs_id")
    for fr, _, d in parsed[detect.DK_ENTRIES]:
        if d.pool is None:
            continue
        pool = d.pool.set_index("dfs_id")
        common = pool.index.intersection(ss.index)
        if len(common) == 0:
            fr.problem("None of DraftKings' player IDs in this entries file are in the SaberSim export: "
                       "they look like different slates.")
            continue
        diff = common[(pool.loc[common, "salary"] != ss.loc[common, "salary"]).to_numpy()]
        if len(diff):
            fr.warn(f"{len(diff)} player salar{'y differs' if len(diff) == 1 else 'ies differ'} between DraftKings "
                    f"and SaberSim, e.g. {pool.loc[diff[0], 'name']}.")


def _check_entries(report, parsed, known, slot_of, formats):
    """Unique entries by Entry ID across all entries files (a later file wins)."""
    by_id, changed = {}, 0
    for _, _, d in parsed[detect.DK_ENTRIES]:
        formats.add(d.fmt)
        report.reservations += d.reservations
        for e in d.entries:
            prev = by_id.get(e.entry_id)
            if prev is not None and prev.player_ids != e.player_ids:
                changed += 1
            by_id[e.entry_id] = e
    report.entries = len(by_id)
    report.entries_files = len(parsed[detect.DK_ENTRIES])
    if changed:
        report.warnings.append(f"{changed} Entry ID(s) appear in more than one entries file with different "
                               f"lineups (pre- and post-late-swap files?). Each entry is counted once, "
                               f"using the newest file.")
    lineups = [e.player_ids for e in by_id.values()]
    _check_ids(report, "entries", lineups, known, slot_of, "your entries")
    return by_id


def _check_lineups(report, parsed, known, slot_of, name_of, formats):
    report.lineup_files = len(parsed[detect.LINEUPS])
    for fr, _, d in parsed[detect.LINEUPS]:
        formats.add(d.fmt)
        report.lineups += len(d.lineups)
        _check_ids(report, fr.name, d.lineups, known, slot_of, fr.name)
        wrong = [f"{n} (ID {pid} is {name_of[pid]} in SaberSim)" for pid, n in d.names.items()
                 if pid in name_of and normalize_name(n) != normalize_name(name_of[pid])]
        if wrong:
            fr.warn("Names that don't match SaberSim for the same ID: " + "; ".join(wrong[:10]))


def _check_ids(report, source, lineups, known, slot_of, label):
    if not lineups or not known:
        return
    used = {pid for lineup in lineups for pid in lineup}
    unknown = sorted(used - known)
    if unknown:
        report.unknown_ids[source] = unknown[:LIST_LIMIT]
        if len(unknown) > len(used) / 2:
            report.problems.append(f"Most DFS IDs in {label} aren't in the SaberSim export: the files look like "
                                   f"different slates.")
        else:
            report.problems.append(f"{len(unknown)} DFS ID(s) in {label} aren't in the SaberSim export.")
    if len(lineups[0]) == len(rosters.SLOTS[rosters.SHOWDOWN]):
        bad = sum(1 for lu in lineups
                  if slot_of.get(lu[0]) not in (None, "CPT") or any(slot_of.get(p) == "CPT" for p in lu[1:]))
        if bad:
            report.problems.append(f"{bad} showdown lineup(s) in {label} use a FLEX ID in the CPT slot "
                                   f"or a CPT ID in a FLEX slot.")


def _check_standings_and_payouts(report, parsed, entries, formats):
    names = {e.contest_id: e.contest_name for e in entries.values()}
    contests = {}
    for fr, det, d in parsed[detect.STANDINGS]:
        cid = d.contest_id
        if not cid:
            fr.problem("Couldn't tell the contest ID from the file name; keep DraftKings' name "
                       "contest-standings-<contestID>.")
            continue
        if cid in contests:
            fr.problem(f"A second standings file for contest {cid} (the first is {contests[cid][0].name}); ignored.")
            continue
        formats.add(d.fmt)
        contests[cid] = (fr, d)
    report.standings_files = len(contests)

    payouts = {}
    for fr, det, d in parsed[detect.PAYOUTS]:
        if det.contest_id in payouts:
            fr.problem(f"A second payout file for contest {det.contest_id}; ignored.")
            continue
        payouts[det.contest_id] = d
        if det.contest_id not in contests:
            fr.warn(f"No standings file for contest {det.contest_id} yet.")
    report.payout_contests = sorted(payouts)

    report.contests = [{
        "contest_id": cid, "contest_name": names.get(cid, ""), "entries": d.entries, "skipped": d.skipped,
        "top_score": d.top_score, "fmt": d.fmt, "has_payouts": cid in payouts, "file": fr.name,
    } for cid, (fr, d) in contests.items()]
    return contests


def _check_fpts(report, contests, post):
    """SaberSim Actual vs DraftKings standings FPTS, player by player (SPEC M1 check)."""
    if not contests:
        report.fpts_note = "not run: no standings files."
        return
    if not post:
        report.fpts_note = "not run: no post-game SaberSim export (Actual is empty in every export)."
        return
    ss = post[-1].players
    if post[-1].fmt == rosters.SHOWDOWN:
        ss = ss[ss["roster_slot"] == "FLEX"]
    lookup = {}
    for row in ss.itertuples():
        lookup.setdefault(row.name_key, []).append((row.name, row.actual))

    compared, mismatches, unmatched, ambiguous, captain_only = {}, {}, set(), set(), set()
    for cid, (_, d) in contests.items():
        rows = d.players
        if d.fmt == rosters.SHOWDOWN:
            flex_keys = set(rows.loc[rows["roster_position"] != "CPT", "name_key"])
            captain_only |= set(rows.loc[(rows["roster_position"] == "CPT") & ~rows["name_key"].isin(flex_keys), "player"])
            rows = rows[rows["roster_position"] != "CPT"]
        for row in rows.itertuples():
            hits = lookup.get(row.name_key)
            if not hits:
                unmatched.add(row.player)
                continue
            if len(hits) > 1:
                ambiguous.add(row.player)
                continue
            if row.name_key in compared and abs(compared[row.name_key] - row.fpts) > FPTS_TOLERANCE:
                report.warnings.append(f"Standings files disagree on {row.player}'s FPTS "
                                       f"({compared[row.name_key]} vs {row.fpts}).")
            compared[row.name_key] = row.fpts
            actual = hits[0][1]
            if pd.isna(actual) or abs(actual - row.fpts) > FPTS_TOLERANCE:
                mismatches[row.name_key] = {"player": row.player, "contest_id": cid, "standings_fpts": row.fpts,
                                            "sabersim_actual": None if pd.isna(actual) else float(actual)}

    report.fpts_checked = True
    report.fpts_compared = len(compared)
    report.fpts_mismatches = list(mismatches.values())
    report.fpts_note = f"{len(compared)} players compared, {len(mismatches)} mismatch(es)."
    if unmatched:
        report.unmatched_names["standings"] = sorted(unmatched)
        report.problems.append(f"{len(unmatched)} standings player name(s) couldn't be matched to SaberSim, so "
                               f"their FPTS weren't checked. Add them to core/aliases.csv if they're the same player.")
    if ambiguous:
        report.problems.append("These standings names match more than one SaberSim player, so they weren't "
                               "checked: " + ", ".join(sorted(ambiguous)))
    if captain_only:
        report.warnings.append("Only drafted as captain, so not in the FPTS check: " + ", ".join(sorted(captain_only)))


def _check_warroom(report, parsed, ref):
    if ref is None:
        return
    keys = set(ref.players["name_key"])
    for fr, _, d in parsed[detect.WARROOM]:
        missing = sorted(d.loc[~d["name_key"].isin(keys), "player"])
        if missing:
            report.unmatched_names[f"War Room ({fr.name})"] = missing
            report.problems.append(f"{len(missing)} War Room name(s) in {fr.name} don't match a SaberSim player, "
                                   f"so their tags can't be used.")


# ---------------------------------------------------------------- storage

def _tables(report, parsed):
    t = {"files": pd.DataFrame([{"file_name": f.name, "kind": f.kind, "bytes": f.bytes, "sha256": f.sha256,
                                 "status": f.status} for f in report.files if f.bytes])}

    def ok(kind):
        return [(fr, det, d) for fr, det, d in parsed[kind] if fr.status != "error"]

    players, results = [], []
    for fr, _, d in ok(detect.SABERSIM):
        cols = [c for c in d.players.columns if c not in sabersim_imp.RESULT_COLUMNS]
        players.append(d.players[cols].assign(source_file=fr.name))
        results.append(d.players[["dfs_id", *sabersim_imp.RESULT_COLUMNS]].assign(source_file=fr.name))
    t["players"] = pd.concat(players, ignore_index=True) if players else None
    t["player_results"] = pd.concat(results, ignore_index=True) if results else None

    pool, entries = [], []
    for fr, _, d in ok(detect.DK_ENTRIES):
        if d.pool is not None:
            pool.append(d.pool.assign(source_file=fr.name))
        entries += [{"source_file": fr.name, "entry_id": e.entry_id, "contest_id": e.contest_id,
                     "contest_name": e.contest_name, "fee_cents": e.fee_cents, "fmt": d.fmt,
                     "player_ids": json.dumps(e.player_ids)} for e in d.entries]
    t["dk_pool"] = pd.concat(pool, ignore_index=True) if pool else None
    t["entries"] = pd.DataFrame(entries)

    t["lineups"] = pd.DataFrame([{"source_file": fr.name, "idx": i, "fmt": d.fmt, "player_ids": json.dumps(lu)}
                                 for fr, _, d in ok(detect.LINEUPS) for i, lu in enumerate(d.lineups)])

    names = {c["contest_id"]: c["contest_name"] for c in report.contests}
    t["contests"] = pd.DataFrame([{"contest_id": d.contest_id, "source_file": fr.name,
                                   "contest_name": names.get(d.contest_id, ""), "fmt": d.fmt,
                                   "entries": d.entries, "skipped": d.skipped, "top_score": d.top_score}
                                  for fr, _, d in ok(detect.STANDINGS)])
    sp = [d.players.assign(contest_id=d.contest_id) for fr, _, d in ok(detect.STANDINGS)]
    t["standings_players"] = pd.concat(sp, ignore_index=True) if sp else None
    po = [d.assign(contest_id=det.contest_id) for fr, det, d in ok(detect.PAYOUTS)]
    t["payouts"] = pd.concat(po, ignore_index=True) if po else None

    ref_ids = {}
    if t["players"] is not None:
        flex = t["players"][t["players"]["roster_slot"] != "CPT"].drop_duplicates("dfs_id")
        counts = flex.groupby("name_key")["dfs_id"]
        ref_ids = {k: ids.iloc[0] for k, ids in counts if len(ids) == 1}
    wr = [d.assign(source_file=fr.name, dfs_id=d["name_key"].map(ref_ids)) for fr, _, d in ok(detect.WARROOM)]
    t["warroom_tags"] = pd.concat(wr, ignore_index=True) if wr else None
    return t
