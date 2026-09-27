"""DFS Lab screens (Streamlit). Start with ./run.sh."""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import detect, slate  # noqa: E402
from core.io_utils import FileProblem  # noqa: E402

st.set_page_config(page_title="DFS Lab", page_icon="🧪", layout="wide")
st.sidebar.title("DFS Lab")
screen = st.sidebar.radio("Screen", ["Import files", "Slate reports"])
st.sidebar.caption("Milestone 1: import and check files.")


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
