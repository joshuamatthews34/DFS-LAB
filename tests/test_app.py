"""Smoke-test the Streamlit screens without a browser."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from core import slate

APP = str(Path(__file__).resolve().parents[1] / "app" / "app.py")


def test_import_screen_loads(home):
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Import a slate's files"


def test_reports_screen_shows_a_slate(home, classic_slate):
    slate.import_files("2026-wk02-main", classic_slate.values())
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.radio[0].set_value("Slate reports").run()
    assert not at.exception
    assert at.header[0].value == "2 entries · 1 standings file · 0 FPTS mismatches"


def test_grade_screen(home, classic_slate):
    slate.import_files("2026-wk02-main", classic_slate.values())
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Grade lineups").run()
    assert not at.exception
    at.button[0].click().run()
    assert not at.exception
    assert any(m.value.startswith("**Graded against NFL $3 Play-Action") for m in at.markdown)
    assert len(at.dataframe) >= 3          # build summary, player exposure, lineups


def test_compare_late_swap_and_season_screens(home, classic_slate):
    from core import builds, compare
    slate.import_files("2026-wk02-main", classic_slate.values())
    builds.save_meta("2026-wk02-main", {"entries:DKEntries.csv": {"name": "UR3", "method": "SaberSim UR3"}})
    compare.compare("2026-wk02-main", "195648006", ["entered:standings", "entries:DKEntries.csv"])
    for screen in ("Compare builds", "Late swap", "Season"):
        at = AppTest.from_file(APP, default_timeout=60).run()
        at.sidebar.radio[0].set_value(screen).run()
        assert not at.exception, screen
    assert len(at.dataframe) >= 1                                   # the season table
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Late swap").run()
    at.button[0].click().run()
    assert not at.exception
    assert at.header[0].value.endswith("better, 0 worse)")


def test_simulator_screen(home, classic_slate):
    slate.import_files("2026-wk02-main", classic_slate.values())
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Simulator").run()
    assert not at.exception
    assert len(at.dataframe) >= 2                                   # calibration table, correlations table
    sim_button = [b for b in at.button if b.label == "Simulate"][0]
    sim_button.click().run()
    assert not at.exception


def test_build_screen(home, downloads):
    import test_builder as tb
    slate.import_files("tnf", tb._showdown_slate(downloads))
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.sidebar.radio[0].set_value("Build lineups").run()
    assert not at.exception
    [n for n in at.number_input if n.label == "Candidate lineups to optimize"][0].set_value(500).run()
    [b for b in at.button if b.label == "Build"][0].click().run()
    assert not at.exception
    assert at.header[0].value == "20 of 20 lineups built"
    assert any("All 20 lineups are legal" in s.value for s in at.success)
