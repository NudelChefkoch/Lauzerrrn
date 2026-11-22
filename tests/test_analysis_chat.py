"""Twin chat on the analysis page: routing, numbers from our model, LLM path (faked) and the offline fallback."""
import socket

import pytest

from twin import analysis_chat as ac
from twin.avatar import avatar_svg
from twin.calibration import calibrate
from twin.config import Assumptions
from twin.engine import simulate
from twin.lifechart import chart_data
from twin.scenarios import HouseBuy, MarketCrash

PATHS = 300


@pytest.fixture(scope="module")
def calib():
    return calibrate()


@pytest.fixture
def ctx(calib, monkeypatch):
    monkeypatch.setattr(ac, "status", lambda force=False: {"available": False, "model": "test"})
    return ac.ChatCtx(person=calib.persons["P00004"], years=10, calib=calib, n_paths=PATHS, seed=0)


@pytest.mark.parametrize("question, tool", [
    ("What if I buy a house at 30?", "house"),
    ("Hauskauf mit 40 zu CHF 900k", "house"),
    ("Is pillar 3a worth it?", "pillar3a"),
    ("Lohnt sich die Säule 3a?", "pillar3a"),
    ("Which investment style suits me?", "strategy"),
    ("What if I lose my job?", "crisis"),
    ("What if the market crashes?", "crisis"),
    ("What matters most?", "drivers"),
    ("How is my current plan?", "plan"),          # "current" must not hit the savings keyword "rent"
    ("How can I save more each month?", "savings"),
    ("What did the film ride show?", "ride"),
    ("Which decisions did I take in the game?", "decisions"),
    ("Any tips for me?", "tips"),
    ("What's the weather tomorrow?", "other"),
])
def test_offline_router(ctx, question, tool):
    assert ac.route_offline(ctx, question)[0] == tool


def test_argument_parsing():
    assert ac.parse_age("What if I buy a house at 30?", 24) == 30
    assert ac.parse_age("at the age of 35", 24) == 35
    assert ac.parse_age("in 5 years", 24) == 29
    assert ac.parse_age("Hauskauf mit 40 zu CHF 900k", 24) == 40
    assert ac.parse_age("a house for 900k", 24) is None
    assert ac.parse_price("a house for 900k") == 900_000
    assert ac.parse_price("CHF 1'200'000") == 1_200_000
    assert ac.parse_price("1.2m") == 1_200_000 and ac.parse_price("1,2 Mio") == 1_200_000
    assert ac.parse_price("at 30") is None


def test_house_at_30_equals_direct_simulate(ctx, calib):
    p = ctx.person
    out = ac.answer(ctx, "What if I buy a house at 30 for CHF 900'000?")
    assert out["tool"] == "house" and out["mode"] == "offline"
    n = out["numbers"]
    assert n["age"] == 30 and n["price"] == 900_000 and n["month"] == (30 - p.age) * 12
    years = max(ctx.years, 30 - p.age + 10)
    a = Assumptions()
    direct = simulate(p, [HouseBuy(n["month"], 900_000.0, "House purchase")], years, a, PATHS, 0, calib=calib).metrics
    base = simulate(p, [], years, a, PATHS, 0, calib=calib).metrics
    assert n["median"] == pytest.approx(direct["median_net_worth_end"])
    assert n["p5"] == pytest.approx(direct["p5_net_worth_end"]) and n["p95"] == pytest.approx(direct["p95_net_worth_end"])
    assert n["p_credit"] == pytest.approx(direct["p_ever_credit"])
    assert n["delta"] == pytest.approx(direct["median_net_worth_end"] - base["median_net_worth_end"])
    assert ac.chf(direct["median_net_worth_end"]) in out["text"]
    assert out["text"].endswith(ac.DISCLAIMER)


def test_every_tool_answers_in_english_with_disclaimer(ctx):
    for q in ["Is pillar 3a worth it?", "Which investment style?", "What if the market crashes?", "What matters most?",
              "How am I doing?", "How can I save?", "film ride?", "my decisions in the game", "tips", "hello"]:
        out = ac.answer(ctx, q)
        assert out["text"].endswith(ac.DISCLAIMER) and out["mode"] == "offline", q
        assert not any(w in out["text"] for w in (" und ", " nicht ", "Vermögen")), q


def test_crisis_numbers_from_model(ctx, calib):
    out = ac.answer(ctx, "What if the market crashes?")
    m = simulate(ctx.person, [MarketCrash(12, -0.35, "Market crash")], 10, Assumptions(), PATHS, 0, calib=calib).metrics
    assert out["args"] == {"kind": "crash"} and out["numbers"]["median"] == pytest.approx(m["median_net_worth_end"])


def test_fake_llm_route(ctx, monkeypatch):
    calls = []

    def fake_chat(messages, fmt=None, **kw):
        calls.append(fmt)
        assert fmt["properties"]["tool"]["enum"] == list(ac.TOOLS)
        return {"tool": "house", "age": 35, "price": 700000}

    monkeypatch.setattr(ac, "status", lambda force=False: {"available": True, "model": "fake"})
    monkeypatch.setattr(ac, "request_chat", fake_chat)
    out = ac.answer(ctx, "Could I afford a place of my own later on?")     # offline router would say "plan"
    assert calls and out["mode"] == "llm" and out["tool"] == "house"
    assert out["args"] == {"age": 35, "price": 700_000}
    direct = ac.house_tool(ctx, 35, 700_000)
    assert out["numbers"]["median"] == direct["numbers"]["median"]
    # numbers written in the question beat the model's arguments
    out = ac.answer(ctx, "House at 30 for 900k?")
    assert out["args"] == {"age": 30, "price": 900_000}
    # an unknown tool from the model -> offline router
    monkeypatch.setattr(ac, "request_chat", lambda *a, **k: {"tool": "launch_rocket", "age": 0, "price": 0})
    out = ac.answer(ctx, "Is pillar 3a worth it?")
    assert out["mode"] == "offline" and out["tool"] == "pillar3a"


def test_timeout_falls_back_to_offline(ctx, monkeypatch):
    def slow(*a, **k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(ac, "status", lambda force=False: {"available": True, "model": "slow"})
    monkeypatch.setattr(ac, "request_chat", slow)
    out = ac.answer(ctx, "What matters most?")
    assert out["mode"] == "offline" and out["tool"] == "drivers" and out["text"].endswith(ac.DISCLAIMER)


def test_status_unreachable_ollama_is_fast(monkeypatch):
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")
    st = ac.status(force=True)
    assert st == {"available": False, "model": ac.model_name()}


def test_greeting_gives_proactive_tips(ctx):
    ctx.ride = {"statements": ["Your typical month went from CHF 2'000 to CHF 2'300."], "months": 12}
    ctx.decisions = [{"age": 25, "emoji": "💍", "title": "Wedding"}]
    g = ac.greeting(ctx)
    tips = ctx.tips()["tips"]
    assert 2 <= len(g["numbers"]["titles"]) <= 3 and g["numbers"]["titles"] == [t["title"] for t in tips[:3]]
    assert "film ride" in g["text"] and "Wedding" in g["text"] and g["text"].endswith(ac.DISCLAIMER)
    assert g["bubble"].startswith("Hi Yara")
    assert ac.answer(ctx, "What did the film ride show?")["numbers"]["statements"] == ctx.ride["statements"]


def test_avatar_from_3d_config():
    cfg = {"name": "Testi", "gender": "frau", "skin": "oliv", "hair": "iro", "hairColor": "blond", "hat": "keiner",
           "outfit": "kleid", "color": "gruen", "car": "rot"}
    av = ac.avatar_from_cfg(cfg)
    assert (av.name, av.skin, av.hair, av.hair_color, av.hat, av.outfit, av.outfit_color) == \
        ("Testi", "oliv", "undercut", "blond", "keine", "tshirt", "gruen")
    assert avatar_svg(av).startswith("<svg")
    assert ac.avatar_from_cfg({"skin": "???", "hair": None}).skin == "rosig"


def test_chart_data_from_simulation(calib):
    p = calib.persons["P00004"]
    res = simulate(p, [HouseBuy(24, 800_000), MarketCrash(36, -0.3, "Crisis: Market crash")], 5, Assumptions(),
                   PATHS, 0, calib=calib)
    short = simulate(p, [], 3, Assumptions(), PATHS, 0, calib=calib)
    d = chart_data(res, [("short", "Shorter", short), ("none", "Nothing", None)], hide_label_prefix="Crisis: ")
    n = 5 * 12 + 1
    assert d["start_age"] == p.age and len(d["plan"]["p50"]) == n and len(d["plan"]["life"]) == n
    assert d["plan"]["p50"] == [int(round(v)) for v in res.percentiles["net_worth"][2]]
    assert d["plan"]["life"] == [int(round(v)) for v in res.path0["net_worth"]]
    assert [c["key"] for c in d["comps"]] == ["short"] and len(d["comps"][0]["p50"]) == n
    assert d["default_comp"] == "short"
    assert {"month": 24, "label": "House purchase"} in d["events"]
    assert {"month": 36, "label": "⚡ Market crash"} in d["events"]
