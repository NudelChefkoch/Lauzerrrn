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
        next(b for b in at.button if b.label == "Load template").click().run()
        assert not at.exception
    next(b for b in at.button if "Job loss 6 months" in b.label).click().run()
    assert not at.exception and at.radio[0].value == "Plan without crises"
    next(b for b in at.button if b.label == "Compute sensitivity").click().run()
    assert not at.exception


def test_game_page_runs_and_links_to_analysis():
    """The game itself lives in a custom component (not clickable in AppTest): check the host page runs."""
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert not at.exception, at.exception
    sess = at.session_state["game_session"]
    assert sess.phase == "boot" and sess.payload()["phase"] == "boot"
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    assert any(b.label == "Load template" for b in at.button)


def test_analysis_twin_chat_with_own_data(monkeypatch):
    """Avatar + chat on the analysis page: proactive tips on load, a question answered offline by the model."""
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")          # no Ollama: offline router
    at = AppTest.from_file(APP, default_timeout=180).run()
    sess = at.session_state["game_session"]
    sess.start({"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
                "portfolio": 8000, "debt": 0},
               {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "iro", "hairColor": "blond", "hat": "cap",
                "outfit": "tshirt", "color": "gruen", "car": "rot"}, seed=1)
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    chat = at.session_state["twin_chat"]
    assert len(chat) == 1 and chat[0]["role"] == "assistant" and chat[0]["content"].startswith("Hi Testi!")
    assert "Not investment advice." in chat[0]["content"]
    at.chat_input(key="twin_q").set_value("What if I buy a house at 32?").run()
    assert not at.exception, at.exception
    chat = at.session_state["twin_chat"]
    assert [m["role"] for m in chat] == ["assistant", "user", "assistant"]
    assert chat[-1]["tool"] == "house" and chat[-1]["mode"] == "offline"
    assert "at 32" in chat[-1]["content"] and chat[-1]["content"].endswith("Not investment advice.")


def test_analysis_starts_with_life_review_after_a_finished_game(monkeypatch):
    """Finished game: the page starts with the review (timeline, positives / negatives) and the twin greets with the
    verdict and the 2 biggest improvements; a review question is answered by the review tool."""
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=240).run()
    sess = at.session_state["game_session"]
    sess.start({"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
                "portfolio": 8000, "debt": 0},
               {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "iro", "hairColor": "blond", "hat": "cap",
                "outfit": "tshirt", "color": "gruen", "car": "rot"}, seed=1)
    for key in ("switch", "wedding", "child"):
        assert sess.choose(key)
    while sess.phase == "play":
        sess.skip(10)
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown]
    first = next(i for i, v in enumerate(md) if "YOUR LIFE REVIEW" in v)
    tl = next(i for i, v in enumerate(md) if "YOUR TIMELINE" in v)
    asp = next(i for i, v in enumerate(md) if "WHAT WENT WELL" in v and "WHERE YOU CAN DO BETTER" in v)
    assert first < tl < asp
    assert "Job change" in md[tl] and "Get married" in md[tl] and "Have a child" in md[tl]
    assert "BETTER" in md[asp]
    assert not any('class="twin-av"' in v for v in md)          # the 3D character on its podium, no SVG fallback
    assert "🔍 Explore more" in [h.value for h in at.header]
    chat = at.session_state["twin_chat"]
    assert len(chat) == 1 and chat[0]["tool"] == "review" and chat[0]["content"].startswith("Hi Testi!")
    assert "Grade " in chat[0]["content"] and "done better" in chat[0]["content"]
    at.chat_input(key="twin_q").set_value("What could I have done better?").run()
    assert not at.exception, at.exception
    chat = at.session_state["twin_chat"]
    assert chat[-1]["tool"] == "review" and chat[-1]["mode"] == "offline"
    assert "Where you could do better" in chat[-1]["content"]


def test_analysis_without_game_shows_plan_timeline():
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown]
    assert any("YOUR PLAN" in v for v in md) and not any("YOUR LIFE REVIEW" in v for v in md)
    at.selectbox(key="tpl").select("hauskauf").run()
    next(b for b in at.button if b.label == "Load template").click().run()
    assert not at.exception, at.exception
    tl = next(v for v in (m.value for m in at.markdown) if "YOUR PLAN" in v)
    assert "lr-mark" in tl and "🏡" in tl
    assert at.session_state["twin_chat"][0]["tool"] == "tips"
