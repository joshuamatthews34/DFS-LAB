"""Command-line version of the import screen.

  python -m core.cli scan [--folder ~/Downloads] [--days 7]
  python -m core.cli import 2026-wk02-main FILE [FILE ...]
  python -m core.cli recheck 2026-wk02-main
  python -m core.cli report 2026-wk02-main

Exits with status 1 when the report lists problems.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import detect, slate
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
    args = ap.parse_args(argv)

    try:
        if args.cmd == "scan":
            for det, mtime in detect.scan_folder(args.folder, args.days):
                when = datetime.fromtimestamp(mtime).strftime("%b %d %H:%M")
                print(f"{when}  {det.label:<32} {det.path.name}" + (f"  ({det.reason})" if det.reason else ""))
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
