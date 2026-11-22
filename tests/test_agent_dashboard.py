"""Zwilling-Chat (twin/agent.py), dashboard (twin/dashboard.py) and their GameSession actions. No network."""
import json
import time

import pytest

from twin import agent, dashboard
from twin.game import YEARS
from twin.session import GameSession


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Ollama is never reachable in tests; a real request would be a bug."""
    monkeypatch.setattr(agent, "status", lambda force=False: {"available": False, "model": "qwen3:4b"})

    def no_network(*a, **k):
        raise AssertionError("request_chat must not be called while offline")
    monkeypatch.setattr(agent, "request_chat", no_network)


def session(choices=("bachelor", "stay", "stay", "stay"), seed=5) -> GameSession:
    s = GameSession()
    s.start("P00001", None, "ausgewogen", seed=seed)
    for k in choices:
        assert s.choose(k), k
    return s


def last_twin(s: GameSession) -> dict:
    p = s.payload()
    msgs = p[p["phase"]]["chat"]["messages"]
    assert msgs[-1]["role"] == "twin" and msgs[-2]["role"] == "user"
    return msgs[-1]


def ask(s: GameSession, nonce: int, text: str) -> dict:
    seq = s.payload()["seq"]
    s.handle({"action": "chat", "nonce": nonce, "message": text})
    assert s.payload()["seq"] == seq + 1
    return last_twin(s)


# ---------------------------------------------------------------- decision groups
def test_choose_records_decision_groups():
    s = session(("bachelor", "stay", "stay", "stay", "switch"))
    assert [g["key"] for g in s.groups] == ["bachelor", "switch"]
    g1, g2 = s.groups
    assert g1["id"] == "d1" and g1["turn"] == 0 and g1["start_month"] == 0 and g1["cat"] == "bildung"
    assert g2["id"] == "d2" and g2["start_month"] == 48 and g2["emoji"] == "🚀"
    flat = [id(e) for g in s.groups for e in g["events"]]
    assert flat == [id(e) for e in s.events]            # every played event belongs to exactly one group


def test_shift_events_keeps_offsets_and_clamps():
    s = session(("bachelor", "stay", "stay", "stay", "course"))
    course = s.groups[-1]
    a, b = course["events"]
    moved = dashboard.shift_events(course["events"], 24)
    assert [e.start for e in moved] == [a.start + 24, b.start + 24]
    early = dashboard.shift_events(course["events"], -1000)
    assert early[0].start == 0 and early[1].start == b.start - a.start
    late = dashboard.shift_events(course["events"], 1000)
    assert all(e.start == 12 * YEARS - 1 for e in late)


# ---------------------------------------------------------------- dashboard
def test_dashboard_series_shapes_and_counterfactual():
    s = session()
    kw = dict(pid=s.pid, start_age=s.person.age, events=s.events, groups=s.groups, a=s.assumptions,
              seed=s.seed, phase="play", turn=s.turn)
    d = dashboard.build(**kw)
    n = YEARS + 1
    assert d["ages"] == list(range(s.person.age, s.person.age + n)) and d["now_index"] == s.turn
    assert set(d["series"]["plan"]) == {"p5", "p50", "p95", "life"}
    assert set(d["series"]["no_saving"]) == set(d["series"]["no_events"]) == {"p50", "life"}
    assert all(len(v) == n for blk in ("plan", "no_saving", "no_events") for v in d["series"][blk].values())
    assert d["series"]["alt"] is None and d["alt_label"] is None
    assert d["inflation"] == s.assumptions.macro.inflation
    plan = d["series"]["plan"]
    assert all(lo <= mid <= hi for lo, mid, hi in zip(plan["p5"], plan["p50"], plan["p95"]))
    # the played life is the same path everywhere it is shared, and the past is fixed
    assert plan["p50"][: s.turn + 1] == pytest.approx(plan["life"][: s.turn + 1])   # fixed_until: shared past
    assert plan["p50"][0] == plan["life"][0]
    assert d["series"]["no_events"]["life"] != plan["life"]          # the bachelor made a difference
    assert d["metrics"]["net_now"] == plan["life"][s.turn] and d["metrics"]["current_age"] == s.person.age + 4
    assert d["summary"].startswith("With your plan, your net worth at ") and "CHF" in d["summary"]
    assert d["timeline"] == [{"id": "d1", "emoji": "🎓", "title": "Bachelor", "age": s.person.age,
                              "cat": "bildung", "movable": True, "alt_age": None}]

    # alt == plan when nothing moves (common random numbers), moving a decision changes alt
    same_events, label = dashboard.apply_moves(s.groups, {}, s.person.age)
    same = dashboard.build(**kw, alt_events=same_events, alt_label="gleich")
    assert same["series"]["alt"] == same["series"]["plan"]
    moved_events, labels = dashboard.apply_moves(s.groups, {"d1": s.person.age + 2}, s.person.age)
    assert labels == ["Bachelor 2 years later"] and moved_events[0].start == 24
    moved = dashboard.build(**kw, alt_events=moved_events, alt_label=labels[0], moves={"d1": s.person.age + 2})
    assert moved["series"]["alt"] != moved["series"]["plan"] and moved["alt_label"] == "Bachelor 2 years later"
    assert moved["timeline"][0]["alt_age"] == s.person.age + 2 and "Variant" in moved["summary"]
    json.dumps(moved, allow_nan=False)

    t = time.perf_counter()
    dashboard.build(**kw, alt_events=moved_events, alt_label=labels[0])
    assert time.perf_counter() - t < 0.05                             # cached


def test_dashboard_end_phase_uses_full_distribution():
    s = session(("bachelor",) + ("stay",) * (YEARS - 1))
    assert s.phase == "end"
    d = dashboard.build(pid=s.pid, start_age=s.person.age, events=s.events, groups=s.groups, a=s.assumptions,
                        seed=s.seed, phase="end", turn=s.turn)
    assert d["now_index"] == YEARS and d["metrics"]["current_age"] == s.person.age + YEARS
    plan = d["series"]["plan"]
    assert plan["p5"][5] < plan["p95"][5]                              # fixed_until = 0: the past is uncertain too


def test_no_saving_invests_nothing():
    s = session(("bachelor",) + ("stay",) * 8)
    d = dashboard.build(pid=s.pid, start_age=s.person.age, events=s.events, groups=s.groups, a=s.assumptions,
                        seed=s.seed, phase="play", turn=s.turn)
    assert d["series"]["no_saving"]["p50"][-1] != d["series"]["plan"]["p50"][-1]
    assert dashboard.chf(1234567.4) == "CHF 1'234'567" and dashboard.chf(-1200) == "−CHF 1'200"
    assert dashboard.chf_delta(5) == "+CHF 5" and dashboard.chf_delta(0) == "CHF 0"


# ---------------------------------------------------------------- dashboard actions through GameSession
def test_dashboard_actions_through_handle():
    s = session()
    p = s.payload()
    assert p["play"]["dashboard"] is None and p["play"]["chat"]["mode"] == "offline"
    seq = p["seq"]
    s.handle({"action": "dashboard", "nonce": 101, "open": True})
    d = s.payload()["play"]["dashboard"]
    assert s.payload()["seq"] == seq + 1 and d is not None and d["series"]["alt"] is None
    s.handle({"action": "dashboard", "nonce": 101, "open": False})       # duplicate nonce: ignored
    assert s.payload()["play"]["dashboard"] is not None and s.payload()["seq"] == seq + 1

    s.handle({"action": "plan_edit", "nonce": 102, "moves": {"d1": s.person.age + 3, "nope": 30}})
    d = s.payload()["play"]["dashboard"]
    assert d["alt_label"] == "Bachelor 3 years later" and d["series"]["alt"] is not None
    assert d["series"]["alt"]["p50"] != d["series"]["plan"]["p50"]
    s.handle({"action": "plan_edit", "nonce": 103, "moves": {"d1": s.person.age}})     # back to the original age
    d = s.payload()["play"]["dashboard"]
    assert d["alt_label"] == "Plan unchanged" and d["series"]["alt"] == d["series"]["plan"]

    s.handle({"action": "plan_alt", "nonce": 104, "key": "switch"})
    d = s.payload()["play"]["dashboard"]
    assert d["alt_label"] == f"Plan + Job change at {s.person.age + s.turn}"
    assert d["series"]["alt"]["p50"][-1] != d["series"]["plan"]["p50"][-1]
    assert d["series"]["alt"]["life"][: s.turn + 1] == d["series"]["plan"]["life"][: s.turn + 1]

    seq = s.payload()["seq"]
    s.handle({"action": "plan_alt", "nonce": 105, "key": "buy_house"})    # locked: nothing changes
    assert s.payload()["seq"] == seq + 1 and s.payload()["play"]["dashboard"]["alt_label"].startswith("Plan + Job")

    s.handle({"action": "plan_reset", "nonce": 106})
    d = s.payload()["play"]["dashboard"]
    assert d["series"]["alt"] is None and d["alt_label"] is None
    s.handle({"action": "dashboard", "nonce": 107, "open": False})
    p = s.payload()
    assert p["play"]["dashboard"] is None and p["seq"] == seq + 3
    json.dumps(p, allow_nan=False)


def test_end_phase_payload_has_chat_and_dashboard():
    s = session(("bachelor", "stay", "stay", "stay", "switch") + ("stay",) * (YEARS - 5))
    p = s.payload()
    assert p["phase"] == "end"
    e = p["end"]
    assert e["dashboard"] is None and e["chat"]["messages"][-1]["stage"] == "Review"
    assert e["chat"]["prompts"] == agent.PROMPTS_END
    s.handle({"action": "dashboard", "nonce": 1, "open": True})
    s.handle({"action": "plan_edit", "nonce": 2, "moves": {"d2": s.person.age + 8}})
    d = s.payload()["end"]["dashboard"]
    assert d["now_index"] == YEARS and d["alt_label"] == "Job change 4 years later"
    assert [t["id"] for t in d["timeline"]] == ["d1", "d2"]
    m = ask(s, 3, "What if I had skipped the job change?")
    assert m["tools"][0]["name"] == "what_if" and m["tools"][0]["args"] == "d2"
    m = ask(s, 4, "What is my best next step?")
    assert m["suggestion"] is None and "fully played" in m["text"]
    json.dumps(s.payload(), allow_nan=False)


# ---------------------------------------------------------------- chat: offline routing
@pytest.mark.parametrize("question, tool, arg", [
    ("Can I afford a house?", "compare_option", "buy_house"),
    ("Is an own flat worth buying?", "compare_option", "buy_flat"),
    ("What would a master bring?", "compare_option", "master"),
    ("Should I switch jobs?", "compare_option", "switch"),
    ("And a child?", "compare_option", "child"),
    ("Go on a world trip?", "compare_option", "travel"),
    ("How high is my risk of debt?", "check_life_plan", ""),
    ("What matters most?", "what_matters", ""),
    ("What is my best next step?", "best_next_step", ""),
    ("What if I had skipped the bachelor?", "what_if", "d1"),
    # German questions still route the same way
    ("Kann ich mir ein Haus leisten?", "compare_option", "buy_house"),
    ("Was zählt am meisten?", "what_matters", ""),
    ("Was wäre ohne den Bachelor?", "what_if", "d1"),
])
def test_offline_routing(question, tool, arg):
    s = session()
    m = ask(s, 50, question)
    assert m["mode"] == "offline" and s.payload()["play"]["chat"]["mode"] == "offline"
    assert m["tools"][0]["name"] == tool and m["tools"][0]["args"] == arg
    assert m["tools"][0]["result"] and m["text"]


def test_other_question_is_redirected():
    s = session()
    m = ask(s, 1, "What will the weather be tomorrow?")
    assert m["tools"] == [] and m["suggestion"] is None and "life plan" in m["text"]


def test_tool_answers_are_sde_numbers():
    s = session()
    card = next(c for c in s.payload()["play"]["cards"] if c["key"] == "switch")
    m = ask(s, 1, "Should I switch jobs?")
    assert dashboard.chf_delta(card["delta"]) in m["text"]                 # same number as on the card
    assert m["suggestion"] == {"key": "switch", "title": "Job change"}
    m = ask(s, 2, "What is my best next step?")
    assert m["suggestion"]["key"] in {c["key"] for c in s.payload()["play"]["cards"] if c["locked"] is None}
    m = ask(s, 3, "What matters most?")
    assert len(m["tools"][0]["result"].split(", ")) == 3
    m = ask(s, 4, "Can I afford a house?")
    assert "Missing equity" in m["text"]


def test_station_openers_and_trim():
    s = GameSession()
    s.start("P00001", None, "ausgewogen", seed=1)
    msgs = s.payload()["play"]["chat"]["messages"]
    assert len(msgs) == 1 and msgs[0]["stage"] == "First job" and msgs[0]["text"].endswith("?")
    s.choose("job_start")
    assert s.payload()["play"]["chat"]["messages"][-1]["stage"] in agent.ROTATION
    for i in range(20):
        s.handle({"action": "chat", "nonce": 1000 + i, "message": "What matters most?"})
    assert len(s.payload()["play"]["chat"]["messages"]) == agent.MAX_MESSAGES
    s.restart()
    s.start("P00001", None, "ausgewogen", seed=1)
    assert len(s.payload()["play"]["chat"]["messages"]) == 1


# ---------------------------------------------------------------- chat: LLM path (fake Ollama)
def test_llm_router_path(monkeypatch):
    seen = []

    def fake(messages, fmt, **kw):
        enum = fmt["properties"]["choice"]["enum"]
        seen.append(enum)
        q = json.loads(messages[1]["content"].replace(" /no_think", ""))["question"]
        return {"choice": {"A": "what_matters", "B": "option:master", "C": "whatif:d1", "D": "broken"}[q]}

    monkeypatch.setattr(agent, "status", lambda force=False: {"available": True, "model": "qwen3:4b"})
    monkeypatch.setattr(agent, "request_chat", fake)
    s = session()
    assert s.payload()["play"]["chat"]["available"] is True
    m = ask(s, 1, "A")
    assert m["mode"] == "llm" and m["tools"][0]["name"] == "what_matters"
    assert s.payload()["play"]["chat"]["mode"] == "llm"
    assert {"check_life_plan", "what_matters", "best_next_step", "other", "option:master",
            "whatif:d1"} <= set(seen[0])
    m = ask(s, 2, "B")
    assert m["mode"] == "llm" and m["tools"][0]["name"] == "compare_option" and m["tools"][0]["args"] == "master"
    m = ask(s, 3, "C")
    assert m["tools"][0]["name"] == "what_if" and m["tools"][0]["args"] == "d1"
    m = ask(s, 4, "D")                                                    # invalid choice -> offline fallback
    assert m["mode"] == "offline"

    def boom(*a, **k):
        raise TimeoutError("too slow")
    monkeypatch.setattr(agent, "request_chat", boom)
    m = ask(s, 5, "What matters most?")
    assert m["mode"] == "offline" and m["tools"][0]["name"] == "what_matters"


def test_request_chat_body(monkeypatch):
    monkeypatch.undo()                                                    # the real request_chat, fake transport
    captured = {}

    class Resp:
        def __init__(self, data):
            self.data = data

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_open(req, timeout):
        captured["url"], captured["timeout"] = req.full_url, timeout
        captured["body"] = json.loads(req.data.decode())
        return Resp(json.dumps({"message": {"content": json.dumps({"choice": "other"})}}).encode())

    monkeypatch.setattr(agent, "_open", fake_open)
    fmt = {"type": "object", "properties": {"choice": {"type": "string", "enum": ["other"]}}}
    assert agent.request_chat([{"role": "user", "content": "x"}], fmt) == {"choice": "other"}
    b = captured["body"]
    assert captured["url"].endswith("/api/chat") and b["think"] is False and b["stream"] is False
    assert b["format"] == fmt and b["options"]["temperature"] == 0.1 and b["options"]["num_predict"] == 32
    assert b["model"] == agent.model_name()


def test_status_unreachable_is_fast_and_cached(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setenv("TWIN_OLLAMA_URL", "http://127.0.0.1:9")          # nothing listens there
    calls = []
    real_open = agent._open

    def counting(req, timeout):
        calls.append(timeout)
        return real_open(req, timeout)

    monkeypatch.setattr(agent, "_open", counting)
    t = time.perf_counter()
    st = agent.status(force=True)
    assert st == {"available": False, "model": agent.model_name()}
    assert time.perf_counter() - t < 1.5 and calls == [agent.STATUS_TIMEOUT] and agent.STATUS_TIMEOUT <= 1.5
    agent.status()
    assert len(calls) == 1                                                # cached for 30 s


# ---------------------------------------------------------------- integration fixes
def test_biggest_decision_prompt_picks_most_impactful_group():
    s = session(("bachelor", "travel", "wedding") + ("stay",) * (YEARS - 3))
    assert s.phase == "end"
    t0 = time.perf_counter()
    m = ask(s, 1, "What if I skipped my biggest decision?")       # one of agent.PROMPTS_END
    assert time.perf_counter() - t0 < 3
    ctx = s._chat_ctx()
    base = ctx.sim(ctx.events, ctx.fixed).metrics["median_net_worth_end"]

    def effect(g):
        ids = {id(e) for e in g["events"]}
        wo = ctx.sim(tuple(e for e in ctx.events if id(e) not in ids), ctx.fixed).metrics["median_net_worth_end"]
        return abs(base - wo)
    best = max(s.groups, key=effect)
    assert m["tools"][0]["name"] == "what_if" and m["tools"][0]["args"] == best["id"]
    assert m["text"].startswith("My most impactful decision")


def test_dashboard_closes_when_the_game_ends():
    s = session(("bachelor",) + ("stay",) * (YEARS - 2))
    s.handle({"action": "dashboard", "nonce": 1, "open": True})
    assert s.payload()["play"]["dashboard"] is not None
    s.handle({"action": "choose", "nonce": 2, "key": "stay"})
    p = s.payload()
    assert p["phase"] == "end" and p["end"]["dashboard"] is None
    s.handle({"action": "dashboard", "nonce": 3, "open": True})
    assert s.payload()["end"]["dashboard"]["now_index"] == YEARS
