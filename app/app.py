"""DFS Lab screens (Streamlit). Start with ./run.sh."""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import (builds, calibration, compare, correlations, detect, grade, lateswap, settings,  # noqa: E402
                  sim, slate)
from core.io_utils import FileProblem  # noqa: E402

st.set_page_config(page_title="DFS Lab", page_icon="🧪", layout="wide")
st.sidebar.title("DFS Lab")
screen = st.sidebar.radio("Screen", ["Import files", "Slate reports", "Grade lineups", "Compare builds",
                                     "Late swap", "Season", "Simulator"])
st.sidebar.caption("Milestones 1-4: import and check files, grade lineups, compare builds, grade late swaps, "
                   "simulate slates.")


def _size_kb(path):
    try:
        return round(path.stat().st_size / 1024, 1)
    except OSError:
        return None


def show_report(report):
    st.header(report.headline())
    if report.ok:
        st.success("Every file read cleanly and the checks passed.")
    else:
        st.error("Problems found. Fix these before trusting any numbers.")

    c = st.columns(5)
    c[0].metric("Your entries", f"{report.entries:,}")
    c[1].metric("Standings files", report.standings_files)
    c[2].metric("FPTS mismatches", len(report.fpts_mismatches) if report.fpts_checked else "not run")
    c[3].metric("Players", report.players)
    c[4].metric("Blend", {True: "loaded", False: "NOT loaded", None: "unknown"}[report.blend_loaded])

    for p in report.problems + [f"{f.name}: {p}" for f in report.files for p in f.problems]:
        st.error(p)
    for w in report.warnings:
        st.warning(w)

    st.subheader("Contests")
    if report.contests:
        df = pd.DataFrame(report.contests)[["contest_id", "contest_name", "fmt", "entries", "skipped",
                                            "top_score", "has_payouts"]]
        df.columns = ["Contest", "Name", "Type", "Field lineups", "Skipped", "Winning score", "Payouts loaded"]
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.write("No standings files yet.")

    st.subheader("FPTS check (SaberSim Actual vs standings FPTS)")
    st.write(report.fpts_note)
    if report.fpts_mismatches:
        st.dataframe(pd.DataFrame(report.fpts_mismatches), hide_index=True, width="stretch")
    for source, names in report.unmatched_names.items():
        if names:
            st.markdown(f"**Unmatched names ({source}):** " + ", ".join(names))
    for source, ids in report.unknown_ids.items():
        if ids:
            st.markdown(f"**DFS IDs not in the SaberSim export ({source}):** " + ", ".join(map(str, ids)))

    st.subheader("Files")
    st.dataframe(pd.DataFrame([{
        "Status": f.status, "File": f.name, "Type": f.label, "Size (KB)": round(f.bytes / 1024, 1),
        "Details": f.summary, "Notes": " ".join(f.problems + f.warnings),
    } for f in report.files]), hide_index=True, width="stretch")
    st.caption(f"Checked {report.generated_at}. Saved copies are in "
               f"{slate.slate_dir(report.slate_id)}. Report text: results/import_report.txt")


def show_grades(info, grades):
    st.markdown(f"**{info.graded_against()}**")
    if info.perfect:
        st.caption("Perfect lineup: " + " / ".join(info.perfect["players"])
                   + f" = {info.perfect['score']} (${info.perfect['salary']:,})")
    if not info.has_payouts:
        st.caption("No payout file for this contest, so cashed / won / ROI aren't shown. They're never estimated.")

    st.markdown("**Build summary** (one row per lineup set)")
    st.dataframe(pd.DataFrame([grade.summary_row(g, info) for g in grades]), hide_index=True, width="stretch")
    st.caption("Top X% = the share of the field scoring strictly higher is X% or less. Each lineup is ranked "
               "against the real field on its own. Shared = average players any two lineups have in common.")

    for tab, g in zip(st.tabs([g.label for g in grades]), grades):
        with tab:
            for p in g.problems:
                st.error(p)
            for w in g.warnings:
                st.warning(w)
            if g.lineups.empty:
                continue
            s = g.summary
            c = st.columns(6)
            c[0].metric("Lineups", s["lineups"])
            c[1].metric("Average", s["avg_score"])
            c[2].metric("Best", s["best_score"])
            c[3].metric("Best finish", f"#{s['best_rank']:,}", f"top {100 * s['best_share']:.2f}%", delta_color="off")
            c[4].metric("Top 1%", s["counts"]["top 1%"])
            if info.has_payouts:
                c[5].metric("ROI", "n/a" if s["roi"] is None else f"{100 * s['roi']:.1f}%")
            exp_tab, lu_tab = st.tabs(["Player exposure", "Lineups"])
            with exp_tab:
                st.dataframe(g.exposure, hide_index=True, width="stretch")
                st.caption("Leverage = your exposure minus actual ownership. Top-1% lineups = how many of the "
                           "contest's top-1% lineups had the player.")
            with lu_tab:
                st.dataframe(grade.lineup_table(g, info.has_payouts), hide_index=True, width="stretch")
                st.caption("Click a column to sort. Stack: QB+2|1 = QB with 2 of his WR/TE and 1 RB/WR/TE from "
                           "the other team; showdown shows the captain and the team split.")


def pick_slate():
    slates = slate.list_slates()
    if not slates:
        st.info("No slates imported yet.")
        return None
    return st.selectbox("Slate", slates, index=len(slates) - 1)


def name_builds(sid, sets):
    meta = builds.load_meta(sid)
    with st.expander("Name your builds (method, refill, hindsight)", expanded=not any(m["name"] for m in meta.values())):
        table = pd.DataFrame([{"key": k, "Lineup set": label, "Name": meta.get(k, builds.DEFAULT)["name"],
                               "Method": meta.get(k, builds.DEFAULT)["method"],
                               "Refill": meta.get(k, builds.DEFAULT)["refill"],
                               "Hindsight": meta.get(k, builds.DEFAULT)["hindsight"]} for k, label, _ in sets])
        edited = st.data_editor(table, hide_index=True, width="stretch", column_config={"key": None},
                                disabled=["Lineup set"], key=f"labels-{sid}")
        st.caption("Method groups results in the Season view (e.g. \"SaberSim UR3\", \"DFS Army v4\"). Refill = "
                   "rebuilt later in SaberSim; compare only with other refills. Hindsight = has settings added "
                   "after the games; left out of comparisons.")
        if st.button("Save names"):
            builds.save_meta(sid, {r["key"]: {"name": r["Name"] or "", "method": r["Method"] or "",
                                              "refill": bool(r["Refill"]), "hindsight": bool(r["Hindsight"]),
                                              "notes": meta.get(r["key"], builds.DEFAULT)["notes"]}
                                   for r in edited.to_dict("records")})
            st.success("Saved.")
            meta = builds.load_meta(sid)
    return meta


def show_comparison(c):
    st.markdown(f"**{c.info.graded_against()}**")
    for w in c.warnings:
        st.warning(w)
    st.markdown("**All the numbers, side by side**")
    st.dataframe(c.summary, hide_index=True, width="stretch")
    st.markdown("**What each build leaned into** (its exposure vs the other builds' average, and how those players scored)")
    for col, (name, t) in zip(st.columns(len(c.leans)), c.leans.items()):
        with col:
            st.caption(name)
            st.dataframe(t[["Player", "Lean", "This build %", "Others avg %", "Final"]], hide_index=True,
                         width="stretch")
    st.markdown("**Exposure differences** (biggest spread first)")
    st.dataframe(c.exposure, hide_index=True, width="stretch")
    st.markdown("**Identical lineups shared between builds**")
    st.dataframe(c.shared, width="stretch")
    st.markdown("**Statistics**")
    if not c.stats.empty:
        st.dataframe(c.stats, hide_index=True, width="stretch")
    st.warning(compare.STATS_WARNING)
    if c.recorded:
        st.caption(f"{c.recorded} named build(s) saved to the Season view.")


if screen == "Import files":
    st.title("Import a slate's files")
    st.write("Pick the files for **one slate** (for example the Week 2 main slate). DFS Lab copies them into "
             "its own folder untouched, checks every one, and shows a report.")
    left, right = st.columns([2, 1])
    slate_id = left.text_input("Slate name", placeholder="2026-wk02-main")
    days = right.number_input("Show files from the last N days", 1, 365, 7)
    folder = st.text_input("Folder", str(Path.home() / "Downloads"))

    try:
        found = detect.scan_folder(folder, days)
    except OSError:
        st.error(f"Can't open the folder {folder}.")
        found = []

    if found:
        table = pd.DataFrame([{
            "Import": False, "File": det.path.name, "Type": det.label,
            "Modified": datetime.fromtimestamp(mtime).strftime("%b %d %H:%M"),
            "Size (KB)": _size_kb(det.path), "Note": det.reason,
        } for det, mtime in found])
        edited = st.data_editor(table, hide_index=True, width="stretch",
                                disabled=["File", "Type", "Modified", "Size (KB)", "Note"], key="files")
        chosen = [found[i][0].path for i in edited.index[edited["Import"]]]
        if st.button(f"Import {len(chosen)} file(s)", type="primary", disabled=not chosen or not slate_id):
            try:
                with st.spinner("Reading files. Big standings files take a few seconds each..."):
                    st.session_state["report"] = slate.import_files(slate_id.strip(), chosen)
            except FileProblem as e:
                st.error(str(e))
        if not slate_id:
            st.caption("Type a slate name to enable the Import button.")
    else:
        st.info("No .csv, .zip or .json files found there in that time window.")

    if "report" in st.session_state:
        st.divider()
        show_report(st.session_state["report"])

elif screen == "Grade lineups":
    st.title("Grade lineups")
    st.write("Score lineup sets against a contest's real field after the games.")
    slates = slate.list_slates()
    if not slates:
        st.info("No slates imported yet.")
    else:
        sid = st.selectbox("Slate", slates, index=len(slates) - 1)
        try:
            contests = grade.list_contests(sid)
            sets = grade.available_sets(sid)
        except FileProblem as e:
            st.error(str(e))
            contests, sets = [], []
        if not contests:
            st.info("This slate has no standings files yet. Import them on the Import files screen.")
        elif not sets:
            st.info("This slate has no entries files or lineup exports to grade.")
        else:
            contest = st.selectbox("Contest", contests, format_func=lambda c: f"{c[0]}  {c[1]}".strip())
            labels = {k: label + (f" ({n} lineups)" if n is not None else "") for k, label, n in sets}
            chosen = st.multiselect("Lineup sets", list(labels), default=[sets[0][0]], format_func=labels.get)
            only = st.checkbox("Only entries entered in this contest (for your entries)")
            if st.button("Grade", type="primary", disabled=not chosen):
                try:
                    with st.spinner("Grading. The first time a big contest is read takes a few seconds..."):
                        st.session_state["graded"] = grade.grade(sid, contest[0], chosen, only)
                except FileProblem as e:
                    st.error(str(e))
            if "graded" in st.session_state:
                st.divider()
                show_grades(*st.session_state["graded"])

elif screen == "Compare builds":
    st.title("Compare builds")
    st.write("Same slate, same field: how did 2 to 6 builds do against each other?")
    sid = pick_slate()
    if sid:
        try:
            contests, sets = grade.list_contests(sid), grade.available_sets(sid)
        except FileProblem as e:
            st.error(str(e))
            contests, sets = [], []
        if not contests or len(sets) < 2:
            st.info("You need a standings file and at least two lineup sets in this slate.")
        else:
            meta = name_builds(sid, sets)
            contest = st.selectbox("Contest", contests, format_func=lambda c: f"{c[0]}  {c[1]}".strip())
            names = {k: builds.label_for(k, label, meta) for k, label, _ in sets}
            chosen = st.multiselect("Builds (2 to 6)", list(names), format_func=names.get, max_selections=6)
            only = st.checkbox("Only entries entered in this contest (for your entries)")
            with_hindsight = st.checkbox("Include hindsight builds (flagged, not saved to the season)")
            if st.button("Compare", type="primary", disabled=len(chosen) < 2):
                try:
                    with st.spinner("Comparing..."):
                        st.session_state["comparison"] = compare.compare(sid, contest[0], chosen, only, with_hindsight)
                except FileProblem as e:
                    st.error(str(e))
            if "comparison" in st.session_state:
                st.divider()
                show_comparison(st.session_state["comparison"])

elif screen == "Late swap":
    st.title("Late-swap grader")
    st.write("Did your late swaps help? Pick the lineups from before the swap and after it.")
    sid = pick_slate()
    if sid:
        try:
            sets = grade.available_sets(sid)
            times = lateswap.kickoff_times(sid)
        except FileProblem as e:
            st.error(str(e))
            sets, times = [], []
        if len(sets) < 2:
            st.info("You need two lineup sets: the entries before the swap and after it.")
        else:
            labels = {k: label for k, label, _ in sets}
            keys = list(labels)
            default_before = next((i for i, k in enumerate(keys) if "pre-swap" in labels[k].lower()),
                                  next((i for i, k in enumerate(keys) if k.startswith("entries:")), 0))
            before = st.selectbox("Before the swap", keys, format_func=labels.get, index=default_before)
            after = st.selectbox("After the swap", keys, format_func=labels.get,
                                 index=keys.index(grade.ENTERED_KEY) if grade.ENTERED_KEY in keys else 0)
            locked = st.selectbox("Games already locked when you swapped", [None, *times],
                                  format_func=lambda t: "The earliest kickoff (default)" if t is None
                                  else f"Everything kicking off by {t:%a %I:%M %p}")
            if st.button("Grade the swaps", type="primary", disabled=before == after):
                try:
                    with st.spinner("Pairing and scoring..."):
                        st.session_state["swap"] = lateswap.grade_swap(sid, before, after, locked)
                except FileProblem as e:
                    st.error(str(e))
            if "swap" in st.session_state:
                r = st.session_state["swap"]
                s = r.summary
                st.divider()
                st.header(r.headline())
                c = st.columns(5)
                c[0].metric("Paired", s["paired"])
                c[1].metric("Changed", s["changed"])
                c[2].metric("Better", s["better"])
                c[3].metric("Worse", s["worse"])
                c[4].metric("Net points", f"{s['net']:+,.1f}")
                if s["rejected"]:
                    st.error(f"{s['rejected']} swap(s) made an illegal roster and were rejected (not counted).")
                for w in r.warnings:
                    st.warning(w)
                for side, ids in (("before the swap", r.unpaired_before), ("after the swap", r.unpaired_after)):
                    if ids:
                        more = f" and {len(ids) - 10} more" if len(ids) > 10 else ""
                        st.info(f"Not paired, only {side}: {', '.join(map(str, ids[:10]))}{more}.")
                st.dataframe(lateswap.changed_table(r), hide_index=True, width="stretch")

elif screen == "Season":
    st.title("Season")
    table, n = builds.season_table()
    if table.empty:
        st.info("Nothing recorded yet. Name your builds with a method on Compare builds, then compare them.")
    else:
        st.dataframe(table, hide_index=True, width="stretch")
        st.info(builds.season_note(n))
        with st.expander("Every recorded result"):
            st.dataframe(builds.season_rows(), hide_index=True, width="stretch")

elif screen == "Simulator":
    st.title("Simulator")
    cal_tab, corr_tab, sim_tab = st.tabs(["Calibration", "Correlations", "Simulate a slate"])

    with cal_tab:
        st.write("Do actual scores land where SaberSim's percentiles say they should? If SaberSim's ranges are "
                 "too narrow, the tail widths stretch them.")
        with_results = calibration.slates_with_results()
        if not with_results:
            st.info("No slate has a post-game SaberSim export yet.")
        else:
            chosen = st.multiselect("Slates", with_results, default=with_results)
            min_proj = st.number_input("Only players projected at least", 0.0, 30.0, calibration.DEFAULT_MIN_PROJ, 0.5)
            df, notes = calibration.collect(chosen, min_proj)
            for n in notes:
                st.warning(n)
            if not df.empty:
                lower, upper = calibration.fit(df)
                saved = (settings.get("sim.lower_tail"), settings.get("sim.upper_tail"))
                st.caption(f"{len(df):,} players from {len(chosen)} slate(s). Percentiles come from each slate's "
                           f"pre-lock export when it has one.")
                st.dataframe(calibration.table(df, lower, upper), hide_index=True, width="stretch")
                c = st.columns(3)
                c[0].metric("Fitted lower tail width", lower)
                c[1].metric("Fitted upper tail width", upper)
                c[2].metric("In use now", f"{saved[0]} / {saved[1]}")
                if st.button("Use the fitted tail widths", type="primary"):
                    settings.put("sim.lower_tail", lower)
                    settings.put("sim.upper_tail", upper)
                    st.success(f"Saved. Simulations now use {lower} / {upper}.")
                with st.expander("Set tail widths by hand"):
                    lo = st.number_input("Lower tail width", 0.5, 3.0, float(saved[0]), 0.05)
                    hi = st.number_input("Upper tail width", 0.5, 3.0, float(saved[1]), 0.05)
                    if st.button("Save these"):
                        settings.put("sim.lower_tail", lo)
                        settings.put("sim.upper_tail", hi)
                        st.success("Saved.")
                st.caption("1.0 = SaberSim's percentiles as they are. 1.3 = each percentile 30% further from the "
                           "median. The average (dk_points) stays the same either way.")

    with corr_tab:
        data = correlations.load()
        st.write(f"How DraftKings scores move together, from {data['source']} "
                 f"({data['seasons'][0]}-{data['seasons'][-1]}, {data['team_weeks']:,} team-weeks). "
                 f"Roles: QB1 = most pass attempts, RB1-2 = most carries + targets, WR1-3 and TE1 = most "
                 f"targets. Players projected under {sim.MIN_CORRELATED_PROJ} point move on their own.")
        st.dataframe(correlations.table(data), hide_index=True, width="stretch")
        st.caption("Copula r is what the simulator uses; rank corr is what was measured. Refresh with "
                   "./run.sh correlations --refresh")

    with sim_tab:
        sid = pick_slate()
        if sid:
            saved = sim.SimSettings.saved()
            c = st.columns(2)
            n = c[0].number_input("Simulated slates", 1_000, 100_000, saved.n_sims, 1_000)
            seed = c[1].number_input("Random seed (same seed = same result)", 0, 10**9, saved.seed)
            st.caption(f"Tail widths in use: {saved.lower_tail} lower / {saved.upper_tail} upper.")
            if st.button("Simulate", type="primary"):
                try:
                    with st.spinner("Simulating..."):
                        st.session_state["sim"] = sim.simulate(
                            sid, sim.SimSettings(int(n), int(seed), saved.lower_tail, saved.upper_tail))
                except FileProblem as e:
                    st.error(str(e))
            if "sim" in st.session_state:
                result = st.session_state["sim"]
                for w in result.warnings:
                    st.warning(w)
                st.caption(f"{result.settings.n_sims:,} simulated slates from {result.source_file}.")
                st.dataframe(result.summary(), hide_index=True, width="stretch")

else:
    st.title("Slate reports")
    slates = slate.list_slates()
    if not slates:
        st.info("No slates imported yet.")
    else:
        chosen = st.selectbox("Slate", slates, index=len(slates) - 1)
        if st.button("Re-check this slate's files"):
            with st.spinner("Re-reading files..."):
                slate.analyze_slate(chosen)
        report = slate.load_report(chosen)
        if report:
            show_report(report)
