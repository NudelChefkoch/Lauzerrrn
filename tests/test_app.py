"""Smoke test of the Streamlit UI without a browser or server."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_runs_presets_and_tornado():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.switch_page("ui/analyse.py").run()
    assert not at.exception
    for name in ["basis", "jobverlust", "hauskauf"]:
        at.selectbox(key="tpl").select(name).run()
        next(b for b in at.button if b.label == "Load template").click().run()
        assert not at.exception
    next(b for b in at.button if b.label == "Compute sensitivity").click().run()
    assert not at.exception


def test_apollo13_and_investing_sections_are_gone():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    subs = [h.value for h in at.subheader]
    assert not any("Apollo" in v or "How could you invest" in v for v in subs)
    assert not any("Job loss 6 months" in b.label or "Market crash −35" in b.label or b.label == "Remove crises"
                   for b in at.button)
    assert not at.radio and not any("Crisis in year" in sl.label for sl in at.slider)
    assert [t.label for t in at.tabs][0] == "💡 Tips"
    card = next(m.value for m in at.markdown if "TWIN VS. REALITY" in m.value)
    assert "Fitted on months" not in card and "simulated futures per person" not in card


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


def _plan_view(at) -> dict | None:
    return _views(at).get("timeline")


def _last_is_chart(at) -> dict:
    """The expected-net-worth chart is the very last element of the page; returns its data."""
    seq = _texts(at)
    last = seq[-1]
    if last.startswith("COMPONENT"):
        args = json.loads(last.split(" ", 2)[2])
        assert args["view"] == "chart", last[:200]
        return args["data"]
    assert False, f"last element is not the chart: {last[:200]}"


def test_analysis_without_game_shows_plan_timeline():
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    md = [m.value for m in at.markdown]
    assert not any("YOUR LIFE REVIEW" in v for v in md)
    plan = _plan_view(at)
    assert plan is not None and plan["title"] == "YOUR PLAN" and plan["mode"] == "plan" and plan["items"] == []
    assert plan["addable"] and plan["start_age"] == 24 and plan["end_age"] == 34
    chart = _last_is_chart(at)
    assert chart["alt"] is None and chart["names"]["played"] == "Your plan" and len(chart["ages"]) == 11
    at.selectbox(key="tpl").select("hauskauf").run()
    next(b for b in at.button if b.label == "Load template").click().run()
    assert not at.exception, at.exception
    plan = _plan_view(at)
    assert any(it["emoji"] == "🏡" and it["kind"] == "decision" for it in plan["items"])
    chart = _last_is_chart(at)
    assert chart["alt"] is not None and chart["names"] == {"played": "No events", "alt": "Your plan",
                                                           "life": "one simulated life",
                                                           "alt_events": "Your plan's events"}
    assert chart["metrics"]["alt_end"] == pytest.approx(chart["alt"]["p50"][-1], rel=0.05)
    assert at.session_state["twin_chat"][0]["tool"] == "tips"


def test_plan_timeline_actions_without_game():
    """Drag / remove / add on YOUR PLAN change st.session_state.events (the life plan below shows the same list)."""
    from twin.scenarios import HouseBuy
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.switch_page("ui/analyse.py").run()
    at.selectbox(key="tpl").select("hauskauf").run()
    next(b for b in at.button if b.label == "Load template").click().run()
    house = next(it for it in _plan_view(at)["items"] if it["emoji"] == "🏡")
    at.session_state["plan_action"] = {"action": "move", "id": house["id"], "age": 28}
    at.run()
    assert not at.exception, at.exception
    ev = at.session_state["events"]
    assert next(e for e in ev if isinstance(e, HouseBuy)).start == 48
    assert at.session_state["twin_chat"][-1]["tool"] == "plan_timeline"
    assert "I moved 🏡 Buy a home" in at.session_state["twin_chat"][-1]["content"]
    at.session_state["plan_action"] = {"action": "add", "key": "child", "age": 30, "params": {"cost": 1500}}
    at.run()
    labels = [e.label for e in at.session_state["events"]]
    assert "Child" in labels and "Child costs" in labels
    child = next(it for it in _plan_view(at)["items"] if it["emoji"] == "👶")
    at.session_state["plan_action"] = {"action": "remove", "id": child["id"]}
    at.run()
    assert [e.label for e in at.session_state["events"]] == ["Job", "House purchase"]
    assert any("Year 4.0" in m.value and "House purchase" in m.value for m in at.markdown)   # "Explore more" list


def test_chat_edits_the_plan_without_game(monkeypatch):
    """“I buy a house at 30 for 800k” → the twin adds it to YOUR PLAN (draggable chip), the bottom chart compares
    the plan with no events; then it moves and removes it on request."""
    from twin.scenarios import HouseBuy
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.switch_page("ui/analyse.py").run()
    at.chat_input(key="twin_q").set_value("I buy a house at 30 for 800k").run()
    assert not at.exception, at.exception
    msg = at.session_state["twin_chat"][-1]
    assert msg["tool"] == "edit_plan" and msg["plan_edit"] == [{"op": "add", "key": "buy_house", "age": 30,
                                                                 "params": {"price": 800_000.0}}]
    assert "I added 🏡 Buy a home (CHF 800'000) at 30" in msg["content"] and "vs. before" in msg["content"]
    houses = [e for e in at.session_state["events"] if isinstance(e, HouseBuy)]
    assert len(houses) == 1 and houses[0].start == 72 and houses[0].price == 800_000
    n_chat = len(at.session_state["twin_chat"])
    at.run()                                                              # a plain rerun applies nothing again
    assert len([e for e in at.session_state["events"] if isinstance(e, HouseBuy)]) == 1
    assert len(at.session_state["twin_chat"]) == n_chat
    chip = next(it for it in _plan_view(at)["items"] if it["emoji"] == "🏡")
    assert chip["movable"] and chip["age"] == 30 and "800'000" in chip["title"]
    chart = _last_is_chart(at)
    assert chart["alt"] is not None and any(mk["emoji"] == "🏡" and mk["age"] == 30 for mk in chart["markers"])
    end = chart["metrics"]["alt_end"]
    assert f"{end:,.0f}".replace(",", "'") in msg["content"]           # the reply's number = the chart's number

    at.chat_input(key="twin_q").set_value("Verschiebe das Haus auf 32").run()
    assert not at.exception, at.exception
    assert [e.start for e in at.session_state["events"] if isinstance(e, HouseBuy)] == [96]
    assert "I moved 🏡 Buy a home" in at.session_state["twin_chat"][-1]["content"]
    at.chat_input(key="twin_q").set_value("retire at 62").run()           # outside the 10-year plan: said, not done
    assert at.session_state["twin_chat"][-1]["plan_edit"] is None
    assert "beyond your plan" in at.session_state["twin_chat"][-1]["content"]
    at.chat_input(key="twin_q").set_value("remove the house").run()
    assert at.session_state["events"] == []
    assert _last_is_chart(at)["alt"] is None


def test_chat_edits_the_new_path_after_a_game(monkeypatch):
    """After a game the twin's plan edits go into the alternative path: draggable on YOUR TIMELINE, orange in the
    chart at the very bottom."""
    pytest.importorskip("twin.alt_path")
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(APP, default_timeout=240).run()
    _played_game(at)
    at.switch_page("ui/analyse.py").run()
    assert not at.exception, at.exception
    assert _last_is_chart(at)["alt"] is None
    at.chat_input(key="twin_q").set_value("I buy a house at 40 for 800k").run()
    assert not at.exception, at.exception
    msg = at.session_state["twin_chat"][-1]
    assert msg["tool"] == "edit_plan" and "I added 🏡 Buy a home (CHF 800'000) at 40" in msg["content"]
    alt = at.session_state["alt_path"]
    assert alt["added"] == [{"id": "a1", "key": "buy_house", "age": 40, "params": {"price": 800_000}}]
    tl = _views(at)["timeline"]
    chip = next(it for it in tl["items"] if it["kind"] == "added")
    assert chip["movable"] and chip["age"] == 40 and tl["has_alt"]
    chart = _last_is_chart(at)
    assert chart["alt"] is not None
    assert f"{chart['metrics']['alt_end']:,.0f}".replace(",", "'") in msg["content"]

    at.chat_input(key="twin_q").set_value("move the house to 45").run()
    assert at.session_state["alt_path"]["added"][0]["age"] == 45
    at.chat_input(key="twin_q").set_value("I don't want the wedding").run()
    assert not at.exception, at.exception
    assert at.session_state["alt_path"]["removed"] == ["d2"]
    assert "out of your new path" in at.session_state["twin_chat"][-1]["content"]
