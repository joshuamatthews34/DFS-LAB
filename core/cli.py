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
  python -m core.cli calibrate [--slate SLATE ...] [--min-proj 5] [--save]
  python -m core.cli simulate 2026-wk03-main [--sims 10000] [--seed 2026]
  python -m core.cli correlations [--refresh]
  python -m core.cli build 2026-wk03-tnf [--name default] [--contest ID ...] [--lineups 150] [--pool 5000]
        [--fill projection|roi|portfolio] [--score-contest ID] [--field synthetic|real] [--contest-size N]
        [--entry-fee 20] [--fill-sims 2000] [--field-sample 20000] [--no-sim]

Exits with status 1 when the report lists problems.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import (builder, builds, calibration, compare, correlations, detect, grade, lateswap, ownership, settings,
               sim, slate)
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
    cal = sub.add_parser("calibrate", help="SaberSim percentiles vs actual scores; fit tail widths")
    cal.add_argument("--slate", action="append", dest="slates", help="default: every slate with results")
    cal.add_argument("--min-proj", type=float, default=calibration.DEFAULT_MIN_PROJ)
    cal.add_argument("--save", action="store_true", help="use the fitted tail widths from now on")
    sm = sub.add_parser("simulate", help="simulate a slate and print each player's range")
    sm.add_argument("slate")
    sm.add_argument("--sims", type=int)
    sm.add_argument("--seed", type=int)
    co = sub.add_parser("correlations", help="show (or re-estimate) the nflverse correlations")
    co.add_argument("--refresh", action="store_true", help="download nflverse 2021-2025 and re-estimate")
    bd = sub.add_parser("build", help="build DFS Lab lineups and write a DraftKings upload file")
    bd.add_argument("slate")
    bd.add_argument("--name", default="default")
    bd.add_argument("--contest", action="append", dest="contests", help="contest ID to fill (default: all)")
    bd.add_argument("--lineups", type=int, default=150, help="when there's no entries file")
    bd.add_argument("--pool", type=int, default=5000, help="candidate lineups to optimize")
    bd.add_argument("--noise", choices=["lognormal", "simulations"], default="lognormal")
    bd.add_argument("--seed", type=int, default=2026)
    bd.add_argument("--salary-floor", type=int)
    bd.add_argument("--uniques", type=int, default=2)
    bd.add_argument("--post-game-ok", action="store_true", help="allow building from a post-game export")
    bd.add_argument("--fill", choices=list(builder.FILL_METHODS), default="projection",
                    help="projection (method 2), roi (method 1) or portfolio (method 3)")
    bd.add_argument("--score-contest", help="contest whose payouts and field score lineups (default: most entries)")
    bd.add_argument("--field", choices=["synthetic", "real"], default="synthetic",
                    help="real = the contest's real lineups (backtests only; marks the build hindsight)")
    bd.add_argument("--contest-size", type=int, help="entries in that contest (synthetic field)")
    bd.add_argument("--entry-fee", type=float, help="dollars, if the entries file doesn't say")
    bd.add_argument("--fill-sims", type=int, default=2000)
    bd.add_argument("--field-sample", type=int, default=20_000)
    bd.add_argument("--no-sim", action="store_true", help="skip the simulated results for a projection fill")
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
        if args.cmd == "calibrate":
            ids = args.slates or calibration.slates_with_results()
            df, notes = calibration.collect(ids, args.min_proj)
            for n in notes:
                print(n)
            if df.empty:
                print("No players with both SaberSim percentiles and Actual scores.")
                return 1
            lower, upper = calibration.fit(df)
            print(f"{len(df):,} players from {', '.join(ids)} (projected {args.min_proj}+ points)")
            print(calibration.table(df, lower, upper).to_string(index=False))
            print(f"Fitted tail widths: lower {lower}, upper {upper}")
            if args.save:
                settings.put("sim.lower_tail", lower)
                settings.put("sim.upper_tail", upper)
                print("Saved: the simulator uses these tail widths from now on.")
            return 0
        if args.cmd == "simulate":
            s = sim.SimSettings.saved()
            s.n_sims = args.sims or s.n_sims
            s.seed = args.seed if args.seed is not None else s.seed
            result = sim.simulate(args.slate, s)
            for w in result.warnings:
                print(f"! {w}")
            print(f"{s.n_sims:,} simulated slates, seed {s.seed}, tail widths {s.lower_tail}/{s.upper_tail}, "
                  f"from {result.source_file}")
            print(result.summary().to_string(index=False))
            return 0
        if args.cmd == "correlations":
            if args.refresh:
                folder = slate.project_root() / "cache" / "nflverse"
                print(f"Downloading nflverse 2021-2025 into {folder} ...")
                correlations.download(folder)
                correlations.save(correlations.estimate(folder))
            data = correlations.load()
            print(f"{data['source']}, seasons {data['seasons'][0]}-{data['seasons'][-1]}, "
                  f"{data['team_weeks']:,} team-weeks, estimated {data['estimated_on']}")
            print(correlations.table(data).to_string(index=False))
            return 0
        if args.cmd == "build":
            s = builder.BuildSettings(name=args.name, contests=args.contests, n_lineups=args.lineups,
                                      pool_size=args.pool, noise=args.noise, seed=args.seed,
                                      salary_floor=args.salary_floor, min_uniques=args.uniques,
                                      allow_post_game_export=args.post_game_ok, fill=args.fill,
                                      roi_contest=args.score_contest, field_source=args.field,
                                      contest_size=args.contest_size, entry_fee=args.entry_fee,
                                      fill_sims=args.fill_sims, field_sample=args.field_sample,
                                      simulated_results=not args.no_sim)
            r = builder.build(args.slate, s, progress=print)
            c = r.checks
            print(f"{c['lineups']} of {c['target']} lineups, {c['legal']} legal, {c['duplicates']} duplicates, "
                  f"avg projection {c['avg_proj']}, avg salary ${c['avg_salary']:,.0f}, "
                  f"avg projected ownership {c['avg_own']}%")
            for w in r.warnings + [f"Chalk: {x}" for x in c["chalk"]]:
                print(f"! {w}")
            print(ownership.summary_text(r, ownership.history(r.fmt)))
            print(simulated_text(r.sim))
            print(f"Upload file: {r.csv_path}")
            return 0 if c["legal"] == c["lineups"] else 1
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


def simulated_text(sim):
    if not sim:
        return "Simulated results: off."
    if "skipped" in sim:
        return f"Simulated results skipped: {sim['skipped']}"
    lines = [f"Simulated contest {sim['contest']} ({sim['field']} field, {sim['field_lineups']:,} lineups, "
             f"{sim['sims']:,} slates): chance of 1+ top-1% finish {sim['set_top1_chance']}%, "
             f"avg lineup top-1% rate {sim['avg_top1_rate']}%"]
    if "roi" in sim:
        lines.append(f"  simulated ROI {100 * sim['roi']:+.1f}% (expected winnings ${sim['expected_winnings']:,.2f} "
                     f"on ${sim['fees']:,.2f} of fees), cash rate {sim['cash_rate']}%")
    else:
        lines.append(f"  {sim.get('roi_note', '')}")
    lines.append(f"  field's average projection {sim.get('field_avg_proj')} vs your build's {sim.get('build_avg_proj')}")
    lines += [f"  {n}" for n in sim.get("notes", [])]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
