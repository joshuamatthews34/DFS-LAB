"""Command-line version of the import screen.

  python -m core.cli scan [--folder ~/Downloads] [--days 7]
  python -m core.cli import 2026-wk02-main FILE [FILE ...]
  python -m core.cli recheck 2026-wk02-main
  python -m core.cli report 2026-wk02-main
  python -m core.cli sets 2026-wk02-main
  python -m core.cli grade 2026-wk02-main 195648006 [--set KEY ...] [--only-contest]

Exits with status 1 when the report lists problems.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import detect, grade, slate
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
