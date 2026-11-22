"""Smoke test of the Streamlit UI without a browser or server."""
import json
from pathlib import Path

import pytest
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


def _played_game(at):
    sess = at.session_state["game_session"]
    sess.start({"age": 27, "status": "employed", "income": 6000, "expenses": 4700, "rent": 1600, "cash": 12000,
                "portfolio": 8000, "debt": 0},
               {"name": "Testi", "gender": "mann", "skin": "oliv", "hair": "iro", "hairColor": "blond", "hat": "cap",
                "outfit": "tshirt", "color": "gruen", "car": "rot"}, seed=1)
    for key in ("switch", "wedding", "child"):
        assert sess.choose(key)
    while sess.phase == "play":
        sess.skip(10)
    return sess


def _walk(node):
    """All elements of the page in render order (markdown text and custom-component args as strings)."""
    children = getattr(node, "children", None)
    if isinstance(children, dict):
        for k in sorted(children):
            yield from _walk(children[k])
    else:
        yield node


def _texts(at) -> list[str]:
    out = []
    for el in _walk(at.main):
        if getattr(el, "type", None) == "markdown":
            out.append(el.value)
        elif getattr(el, "type", None) == "component_instance":
            out.append(f"COMPONENT {el.proto.component_name} {el.proto.json_args}")
    return out


def _views(at) -> dict:
    """lifereview component views on the page: {view: data}."""
    out = {}
    for el in at.get("component_instance"):
        if el.proto.component_name.endswith("lifereview"):
            args = json.loads(el.proto.json_args)
            out[args.get("view")] = args.get("data")
    return out


def test_analysis_starts_with_life_review_after_a_finished_game(monkeypatch):
    """Finished game: hero → timeline (start age … 85, editable) → the twin on its podium says what went well / where
    to do better (chat underneath) → TRY ANOTHER PATH (suggestions) → EXPECTED NET WORTH; then "Explore more"."""
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=240).run()
    _played_game(at)
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    seq = _texts(at)
    first = next(i for i, v in enumerate(seq) if "YOUR LIFE REVIEW" in v)
    tl = next(i for i, v in enumerate(seq) if "YOUR TIMELINE" in v or ('"view": "timeline"' in v))
    say_h = next(i for i, v in enumerate(seq) if "YOUR TWIN SAYS" in v)
    say = next(i for i, v in enumerate(seq) if 'class="lr-speech"' in v)
    other = next(i for i, v in enumerate(seq) if "TRY ANOTHER PATH" in v)
    nw = next(i for i, v in enumerate(seq) if "EXPECTED NET WORTH" in v)
    assert first < tl < say_h < say < other < nw
    assert "Job change" in seq[tl] and "Get married" in seq[tl] and "Have a child" in seq[tl]
    assert "what went well" in seq[say] and "Where you can do better" in seq[say] and "BETTER" in seq[say]
    assert "Grade " in seq[say]
    assert not any('class="twin-av"' in v for v in seq)          # the 3D character on its podium, no SVG fallback
    assert any("twin3d" in v and '"mode": "podium"' in v for v in seq)
    assert "🔍 Explore more" in [h.value for h in at.header]
    views = _views(at)
    if views:                                                    # the lifereview component is installed
        assert set(views) == {"timeline", "suggestions", "chart"}
        t = views["timeline"]
        assert t["start_age"] == 27 and t["end_age"] == 85 and t["addable"] and not t["has_alt"]
        assert {it["kind"] for it in t["items"]} >= {"decision"}
        assert views["chart"]["ages"][0] == 27 and views["chart"]["ages"][-1] == 85 and views["chart"]["alt"] is None
    chat = at.session_state["twin_chat"]
    assert len(chat) == 1 and chat[0]["tool"] == "review" and chat[0]["content"].startswith("Hi Testi!")
    assert "Grade " in chat[0]["content"] and "done better" in chat[0]["content"]
    at.chat_input(key="twin_q").set_value("What could I have done better?").run()
    assert not at.exception, at.exception
    chat = at.session_state["twin_chat"]
    assert chat[-1]["tool"] == "review" and chat[-1]["mode"] == "offline"
    assert "Where you could do better" in chat[-1]["content"]


def test_life_review_try_another_path_round_trip(monkeypatch):
    """The twin's suggestions apply to the alternative path (session-state round trip), a moved decision shows up,
    each action nonce counts once, Reset brings the played life back; the chat lists the suggestions."""
    pytest.importorskip("twin.alt_path")
    from twin import alt_path
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=240).run()
    sess = _played_game(at)
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    assert at.session_state["alt_path"] == {"moves": {}, "removed": [], "added": []}
    sugg = at.session_state["alt_sugg"][1]
    assert sugg and {"up", "down"} <= {s["impact"] for s in sugg}
    best = next(s for s in sugg if s["impact"] == "up")

    at.session_state["alt_action"] = {"action": "apply", "id": best["id"]}
    at.run()
    assert not at.exception, at.exception
    alt = at.session_state["alt_path"]
    assert alt != {"moves": {}, "removed": [], "added": []}
    assert alt == alt_path.apply_edit({"moves": {}, "removed": [], "added": []}, best["edit"]) or alt["added"]
    note = at.session_state["twin_chat"][-1]
    assert note["tool"] == "alt_path" and "compared with the life you played" in note["content"]
    md = " ".join(m.value for m in at.markdown)
    assert "NEW PATH AT 85" in md and "vs. your path" in md
    assert any(c.value.startswith("✏️ Your new path:") for c in at.caption)
    views = _views(at)
    if views:
        assert views["timeline"]["has_alt"] and views["chart"]["alt"] is not None
        assert views["chart"]["summary"].startswith("New path: ")

    dec = next(it for it in alt_path.timeline_items(sess) if it["kind"] == "decision" and it["movable"])
    target = int(dec["age"]) + 3
    at.session_state["alt_action"] = {"action": "move", "id": dec["id"], "age": target, "nonce": "n1"}
    at.run()
    assert at.session_state["alt_path"]["moves"].get(dec["id"]) == target
    at.session_state["alt_action"] = {"action": "move", "id": dec["id"], "age": target + 2, "nonce": "n1"}
    at.run()                                                     # same nonce: not applied twice
    assert at.session_state["alt_path"]["moves"].get(dec["id"]) == target
    assert any("moved" in c.value and dec["title"] in c.value for c in at.caption)

    at.chat_input(key="twin_q").set_value("Suggest another path").run()
    assert not at.exception, at.exception
    assert at.session_state["twin_chat"][-1]["tool"] == "suggest"

    next(b for b in at.button if b.key == "alt_reset").click().run()
    assert not at.exception, at.exception
    assert at.session_state["alt_path"] == {"moves": {}, "removed": [], "added": []}
    assert "Back to the life you played" in at.session_state["twin_chat"][-1]["content"]


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
