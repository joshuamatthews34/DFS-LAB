"""DFS Lab screens (Streamlit). Start with ./run.sh."""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import (builder, builds, calibration, compare, correlations, detect, grade, lateswap,  # noqa: E402
                  ownership, rosters, settings, sim, slate)
from core.io_utils import FileProblem  # noqa: E402

st.set_page_config(page_title="DFS Lab", page_icon="🧪", layout="wide")
st.sidebar.title("DFS Lab")
screen = st.sidebar.radio("Screen", ["Import files", "Slate reports", "Grade lineups", "Compare builds",
                                     "Late swap", "Season", "Simulator", "Build lineups"])
st.sidebar.caption("Milestones 1-5: import and check files, grade lineups, compare builds, grade late swaps, "
                   "simulate slates, build lineups.")


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


def build_screen(sid):
    parsed = slate.load_parsed(sid)
    exports = parsed[detect.SABERSIM]
    pre = [x for x in exports if not x[2].has_actuals]
    if not exports:
        st.info("Import this slate's pre-lock SaberSim export first.")
        return
    allow_post = False
    if pre:
        st.caption(f"Projections from the pre-lock export {pre[-1][0].name}. It's copied into a pre-lock snapshot "
                   f"when you build.")
    else:
        st.warning("This slate only has a post-game SaberSim export. Building from it risks hindsight; the build "
                   "is marked as a refill.")
        allow_post = st.checkbox("Use the post-game export's projections anyway")
    fmt = (pre or exports)[-1][2].fmt

    s = builder.BuildSettings()
    c = st.columns([2, 1])
    s.name = c[0].text_input("Build name", "default", help="Saved as builds/dfslab-<name>.csv")
    ent = parsed[detect.DK_ENTRIES][-1][2] if parsed[detect.DK_ENTRIES] else None
    if ent is not None and ent.all_entries:
        counts = pd.Series([e.contest_id for e in ent.all_entries]).value_counts()
        names = {e.contest_id: e.contest_name for e in ent.all_entries}
        s.contests = c[1].multiselect("Contests to fill", list(counts.index), default=list(counts.index),
                                      format_func=lambda x: f"{names[x]} ({counts[x]} entries)")
    else:
        s.n_lineups = int(c[1].number_input("Lineups", 1, 500, 150))
        st.caption("No entries file with entries in this slate, so DFS Lab writes a plain lineup file.")

    with st.expander("Lineup rules"):
        c = st.columns(3)
        s.salary_floor = int(c[0].number_input("Salary floor", 0, 50_000, s.floor(fmt), 100))
        s.min_uniques = int(c[1].number_input("Unique players between lineups", 1, 9, 2))
        cap = c[2].number_input("Max total projected ownership (0 = off)", 0.0, 900.0, 0.0, 5.0)
        s.max_total_own = cap or None
        if fmt == rosters.SHOWDOWN:
            s.qb_captain_passcatcher = st.checkbox("A QB captain needs one of his WR/TEs", True)
            s.one_k_one_dst = st.checkbox("At most one K and one DST", True)
        else:
            c = st.columns(3)
            s.stack_passcatchers = int(c[0].number_input("QB + at least this many of his WR/TEs", 0, 4, 1))
            s.bring_back = c[1].checkbox("Bring-back (an opponent from the QB's game)")
            s.coverage_floor = c[2].checkbox("Game coverage floor", True)
            if s.coverage_floor:
                c = st.columns(2)
                s.coverage_total = c[0].number_input("Games with a total of at least", 30.0, 70.0, 44.0, 0.5)
                s.coverage_per_lineup = c[1].number_input("get at least this many players per lineup", 0.0, 3.0,
                                                          0.5, 0.1)
    with st.expander("Candidates"):
        c = st.columns(3)
        s.pool_size = int(c[0].number_input("Candidate lineups to optimize", 500, 20_000, 5_000, 500))
        s.noise = c[1].radio("Noise", ["lognormal", "simulations"],
                             format_func={"lognormal": "~25% random noise on projections",
                                          "simulations": "One simulated slate per candidate"}.get)
        s.seed = int(c[2].number_input("Random seed", 0, 10**9, 2026))
        st.caption("Classic with 5,000 candidates takes a few minutes; showdown well under a minute.")
    with st.expander("War Room rules and late-game ownership"):
        st.caption("Max exposure from a War Room tag = projected ownership x the multiplier. These are untested "
                   "starting points (SPEC 5.2). Each build records the rules it used.")
        c = st.columns(4)
        s.warroom_rules = {"OVER": c[0].number_input("OVER x", 0.0, 5.0, 1.5, 0.1),
                           "WITH": c[1].number_input("WITH x", 0.0, 5.0, 1.0, 0.1),
                           "UNDER": c[2].number_input("UNDER x", 0.0, 5.0, 0.6, 0.1),
                           "FADE_MAX": c[3].number_input("FADE max %", 0.0, 10.0, 3.0, 0.5)}
        if st.checkbox("Late-game ownership haircut (off by default)"):
            s.late_haircut = st.slider("Cut projected ownership of 4:05/4:25 players by", 0.05, 0.8, 0.4, 0.05)

    with st.expander("Player limits (optional)"):
        ss = (pre or exports)[-1][2]
        players = ss.players
        tags = parsed[detect.WARROOM][-1][2] if parsed[detect.WARROOM] else None
        base, _, _ = builder.prepare(players, ss, ent, tags, s)
        base = base[base["proj"] >= builder.MIN_POOL_PROJ].sort_values("proj", ascending=False)
        table = pd.DataFrame({"dfs_id": base["dfs_id"], "Player": base["name"], "Pos": base["pos"],
                              "Team": base["team"], "Salary": base["salary"], "Proj": base["proj"],
                              "Proj own %": base["own"].round(1), "War Room": base["tag"],
                              "Rule max %": base["max_exp"].round(1), "Min %": None, "Max %": None})
        if fmt == rosters.SHOWDOWN:
            table["CPT tier"] = None
        cfg = {"dfs_id": None, "Min %": st.column_config.NumberColumn(min_value=0, max_value=100),
               "Max %": st.column_config.NumberColumn(min_value=0, max_value=100)}
        if fmt == rosters.SHOWDOWN:
            cfg["CPT tier"] = st.column_config.SelectboxColumn(options=list(builder.CAPTAIN_TIERS))
            st.caption("Captain tiers: " + "; ".join(f"{k} {a}-{b}%" for k, (a, b) in builder.CAPTAIN_TIERS.items()))
        edited = st.data_editor(table, hide_index=True, width="stretch", column_config=cfg,
                                disabled=["Player", "Pos", "Team", "Salary", "Proj", "Proj own %", "War Room",
                                          "Rule max %"], key=f"limits-{sid}")
        for row in edited.to_dict("records"):
            lo, hi = row["Min %"], row["Max %"]
            if pd.notna(lo) or pd.notna(hi):
                s.exposures[str(row["dfs_id"])] = [float(lo) if pd.notna(lo) else 0.0,
                                                   float(hi) if pd.notna(hi) else float(row["Rule max %"])]
            if fmt == rosters.SHOWDOWN and row.get("CPT tier"):
                s.captain_tiers[str(row["dfs_id"])] = row["CPT tier"]
    s.allow_post_game_export = allow_post

    if st.button("Build", type="primary", disabled=not (pre or allow_post)):
        try:
            with st.status("Building...", expanded=True) as status:
                st.session_state["built"] = builder.build(sid, s, progress=status.write)
                status.update(label="Built", state="complete")
        except FileProblem as e:
            st.error(str(e))
    if "built" in st.session_state and st.session_state["built"].slate_id == sid:
        show_build(st.session_state["built"])


def show_build(r):
    c = r.checks
    st.header(f"{c['lineups']} of {c['target']} lineups built")
    if c["legal"] == c["lineups"] and not c["duplicates"]:
        st.success(f"All {c['lineups']} lineups are legal DraftKings lineups, with no duplicates.")
    else:
        st.error(f"{len(c['illegal'])} illegal lineup(s), {c['duplicates']} duplicate(s): " + "; ".join(c["illegal"][:5]))
    m = st.columns(4)
    m[0].metric("Avg projection", c["avg_proj"])
    m[1].metric("Avg salary", f"${c['avg_salary']:,.0f}")
    m[2].metric("Avg projected ownership", f"{c['avg_own']}%")
    m[3].metric("Candidates", f"{r.candidates:,}")
    for w in r.warnings:
        st.warning(w)
    for w in c["chalk"]:
        st.warning(f"Chalk: {w}")
    st.info(ownership.summary_text(r, ownership.history(r.fmt)))
    with open(r.csv_path, "rb") as f:
        st.download_button("Download the DraftKings upload file", f.read(), file_name=f"DKEntries-dfslab-{r.settings.name}.csv",
                           mime="text/csv", type="primary")
    st.caption(f"Also saved as {r.csv_path}. Upload it in DraftKings' entry editor yourself.")
    st.markdown("**Exposure**")
    st.dataframe(builder.exposure_table(r), hide_index=True, width="stretch")
    if c["coverage"]:
        st.markdown("**Game coverage**")
        st.dataframe(pd.DataFrame(c["coverage"]), hide_index=True, width="stretch")
    st.markdown("**Lineups**")
    names = r.pool["name"].to_dict()
    slots = r.pool["slot"].to_dict()
    st.dataframe(pd.DataFrame([{
        "#": i + 1, "Proj": round(float(r.pool.loc[lu, "proj"].sum()), 2),
        "Salary": int(r.pool.loc[lu, "salary"].sum()), "Proj own %": round(float(r.pool.loc[lu, "own"].sum()), 1),
        "Players": " / ".join(("CPT " if slots[x] == "CPT" else "") + names[x] for x in lu),
    } for i, lu in enumerate(r.lineups)]), hide_index=True, width="stretch")


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

elif screen == "Build lineups":
    st.title("Build lineups")
    st.write("DFS Lab's own builder. It writes a DraftKings upload file; you upload it yourself. "
             "DFS Lab never logs in to or touches DraftKings.")
    sid = pick_slate()
    if sid:
        build_screen(sid)

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
