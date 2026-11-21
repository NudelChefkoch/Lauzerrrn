"""Smoke test of the Streamlit UI without a browser or server."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_runs_presets_crisis_and_tornado():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.switch_page("ui/analyse.py").run()
    assert not at.exception
    for name in ["basis", "jobverlust", "hauskauf"]:
        at.selectbox(key="tpl").select(name).run()
        next(b for b in at.button if b.label == "Vorlage laden").click().run()
        assert not at.exception
    next(b for b in at.button if "Jobverlust 6 Monate" in b.label).click().run()
    assert not at.exception and at.radio[0].value == "Plan ohne Krisen"
    next(b for b in at.button if b.label == "Sensitivitaet berechnen").click().run()
    assert not at.exception


def test_game_page_runs_and_links_to_analysis():
    """The game itself lives in a custom component (not clickable in AppTest): check the host page runs."""
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert not at.exception, at.exception
    sess = at.session_state["game_session"]
    assert sess.phase == "boot" and sess.payload()["phase"] == "boot"
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    assert any(b.label == "Vorlage laden" for b in at.button)
