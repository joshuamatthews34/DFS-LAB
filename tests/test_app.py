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
