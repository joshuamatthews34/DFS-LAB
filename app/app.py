"""DFS Lab screens (Streamlit). Start with ./run.sh."""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import detect, grade, slate  # noqa: E402
from core.io_utils import FileProblem  # noqa: E402

st.set_page_config(page_title="DFS Lab", page_icon="🧪", layout="wide")
st.sidebar.title("DFS Lab")
screen = st.sidebar.radio("Screen", ["Import files", "Slate reports", "Grade lineups"])
st.sidebar.caption("Milestone 1: import and check files. Milestone 2: grade lineups.")


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
