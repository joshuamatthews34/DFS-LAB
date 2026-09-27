"""Command-line version of the import screen.

  python -m core.cli scan [--folder ~/Downloads] [--days 7]
  python -m core.cli import 2026-wk02-main FILE [FILE ...]
  python -m core.cli recheck 2026-wk02-main
  python -m core.cli report 2026-wk02-main
  python -m core.cli sets 2026-wk02-main
  python -m core.cli grade 2026-wk02-main 195648006 [--set KEY ...] [--only-contest]
  python -m core.cli label 2026-wk02-main KEY --name "SaberSim UR3" --method "SaberSim UR3" [--refill] [--hindsight]
  python -m core.cli compare 2026-wk02-main 195648006 --set KEY --set KEY [...]
  python -m core.cli lateswap 2026-wk02-main BEFORE_KEY AFTER_KEY
  python -m core.cli season

Exits with status 1 when the report lists problems.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import builds, compare, detect, grade, lateswap, slate
from .io_utils import FileProblem


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dfs-lab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="list files DFS Lab recognizes in a folder")
    s.add_argument("--folder", default=str(Path.home() / "Downloads"))
    s.add_argument("--days", type=float, default=7, help="only files changed in the last N days")
    i = sub.add_parser("import", help="import files into a slate and print the report")
    i.add_argument("slate")
    i.add_argument("files", nargs="+")
    for name in ("recheck", "report"):
        p = sub.add_parser(name, help="re-read a slate's files" if name == "recheck" else "print the last report")
        p.add_argument("slate")
    p = sub.add_parser("sets", help="list a slate's contests and lineup sets")
    p.add_argument("slate")
    g = sub.add_parser("grade", help="grade lineup sets against a contest's real field")
    g.add_argument("slate")
    g.add_argument("contest")
    g.add_argument("--set", action="append", dest="sets", help="lineup set key (repeatable; default all)")
    g.add_argument("--only-contest", action="store_true", help="only entries entered in this contest")
    lb = sub.add_parser("label", help="name a lineup set and mark it refill / hindsight")
    lb.add_argument("slate")
    lb.add_argument("key")
    lb.add_argument("--name", default="")
    lb.add_argument("--method", default="")
    lb.add_argument("--refill", action="store_true")
    lb.add_argument("--hindsight", action="store_true")
    c = sub.add_parser("compare", help="compare 2-6 builds on one contest")
    c.add_argument("slate")
    c.add_argument("contest")
    c.add_argument("--set", action="append", dest="sets", required=True)
    c.add_argument("--only-contest", action="store_true")
    c.add_argument("--include-hindsight", action="store_true")
    ls = sub.add_parser("lateswap", help="grade a late swap: before-swap set vs after-swap set")
    ls.add_argument("slate")
    ls.add_argument("before")
    ls.add_argument("after", nargs="?", default=grade.ENTERED_KEY)
    sub.add_parser("season", help="the season table: each method across slates")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "scan":
            for det, mtime in detect.scan_folder(args.folder, args.days):
                when = datetime.fromtimestamp(mtime).strftime("%b %d %H:%M")
                print(f"{when}  {det.label:<32} {det.path.name}" + (f"  ({det.reason})" if det.reason else ""))
            return 0
        if args.cmd == "sets":
            for cid, name in grade.list_contests(args.slate):
                print(f"contest {cid}  {name}")
            for key, label, n in grade.available_sets(args.slate):
                print(f"set {key}  {label}" + (f"  ({n} lineups)" if n is not None else ""))
            return 0
        if args.cmd == "grade":
            info, grades = grade.grade(args.slate, args.contest, args.sets, args.only_contest)
            print(grade.to_text(info, grades))
            return 0 if not any(g.problems for g in grades) else 1
        if args.cmd == "label":
            meta = builds.load_meta(args.slate)
            meta[args.key] = {"name": args.name, "method": args.method, "refill": args.refill,
                              "hindsight": args.hindsight, "notes": ""}
            builds.save_meta(args.slate, meta)
            print(f"Saved label for {args.key}.")
            return 0
        if args.cmd == "compare":
            c = compare.compare(args.slate, args.contest, args.sets, args.only_contest, args.include_hindsight)
            print(compare.to_text(c))
            return 0
        if args.cmd == "lateswap":
            print(lateswap.to_text(lateswap.grade_swap(args.slate, args.before, args.after)))
            return 0
        if args.cmd == "season":
            table, n = builds.season_table()
            print(table.to_string(index=False) if not table.empty else "No results recorded yet.")
            print(builds.season_note(n))
            return 0
        if args.cmd == "import":
            report = slate.import_files(args.slate, args.files)
        elif args.cmd == "recheck":
            report = slate.analyze_slate(args.slate)
        else:
            report = slate.load_report(args.slate)
            if report is None:
                print(f"No report yet for {args.slate}.")
                return 1
    except FileProblem as e:
        print(f"Stopped: {e}")
        return 1
    print(report.to_text())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
