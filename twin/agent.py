"""Twin chat: Juli's agent design (financial-twin/agent.cjs, dialog.cjs, story.js) on OUR SDE.

The language model is only a ROUTER: it picks exactly one key among computed actions (JSON-schema constrained
answer, ``{"choice": enum[...]}``). Every number in the reply is templated from ``twin.engine.simulate`` results.
If Ollama is not reachable (or anything fails / times out) a deterministic keyword router (English and German)
picks the same tools, so the answers are identical; ``mode`` says which router was used.

Tools (each returns a text and a trace entry ``{name, args, result}``):
  check_life_plan · compare_option(key) · what_if(group id | key) · what_matters ·
  best_next_step · other

Environment: ``TWIN_OLLAMA_URL`` (default http://127.0.0.1:11434), ``TWIN_OLLAMA_MODEL`` (default qwen3:4b),
``TWIN_OLLAMA_TIMEOUT`` (seconds for one chat request, default 20).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from .dashboard import chf, chf_delta

MAX_MESSAGES = 30
MAX_QUESTION = 400
STATUS_TTL = 30.0
STATUS_TIMEOUT = 1.2

PROMPTS_PLAY = ["Can I afford a house?", "What matters most?", "What is my best next step?"]
PROMPTS_END = ["What matters most?", "What if I skipped my biggest decision?", "Where was my biggest risk?"]

TOOL_NAMES = ("check_life_plan", "compare_option", "what_if", "what_matters", "best_next_step", "other")

GOAL_EN = {"Emergency savings": "Rainy-day fund", "Career transition": "Cushion for a job change",
           "Education flexibility": "Education reserve", "Housing deposit": "Home deposit",
           "Long-term financial resilience": "Long-term reserve", "Retirement reserve": "Retirement savings"}


def ollama_url() -> str:
    return os.environ.get("TWIN_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def model_name() -> str:
    return os.environ.get("TWIN_OLLAMA_MODEL", "qwen3:4b")


# ---------------------------------------------------------------- Ollama
def _open(req, timeout: float):
    """urlopen that never routes a loopback Ollama through an HTTP proxy."""
    url = req if isinstance(req, str) else req.full_url
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


_status_cache: dict = {"t": -1e9, "value": None, "key": None}


def status(force: bool = False) -> dict:
    """{'available': bool, 'model': str}; one GET /api/tags with a short timeout, cached for 30 s."""
    key = (ollama_url(), model_name())
    now = time.monotonic()
    if not force and _status_cache["value"] is not None and _status_cache["key"] == key \
            and now - _status_cache["t"] < STATUS_TTL:
        return dict(_status_cache["value"])
    model = model_name()
    available = False
    try:
        with _open(ollama_url() + "/api/tags", STATUS_TIMEOUT) as r:
            models = json.loads(r.read().decode("utf-8")).get("models") or []
        available = any(m.get("name") == model or m.get("model") == model for m in models if isinstance(m, dict))
    except Exception:
        available = False
    value = {"available": available, "model": model}
    _status_cache.update(t=now, value=value, key=key)
    return dict(value)


def request_chat(messages: list[dict], fmt: dict, max_tokens: int = 32, temperature: float = 0.1,
                 timeout: float | None = None) -> dict:
    """POST /api/chat (no streaming, ``think: false``) and parse the JSON answer of the model."""
    timeout = float(os.environ.get("TWIN_OLLAMA_TIMEOUT", "20")) if timeout is None else timeout
    body = json.dumps({"model": model_name(), "think": False, "stream": False, "keep_alive": "15m",
                       "messages": messages, "format": fmt,
                       "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096}})
    req = urllib.request.Request(ollama_url() + "/api/chat", data=body.encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with _open(req, timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return json.loads(data["message"]["content"])


# ---------------------------------------------------------------- context the session hands to the agent
@dataclass
class ChatCtx:
    """Everything the tools need; built by ``GameSession`` (all numbers come from ``sim``)."""
    phase: str                                   # 'play' | 'end'
    start_age: int
    age: int
    month: int                                   # "now" (end phase: 12*YEARS)
    state: str                                   # 'student' | 'employed' | ...
    events: tuple                                # played events
    groups: list[dict]                           # decision groups (id, key, emoji, title, cat, start_month, events)
    options: list[dict]                          # all cards: {key, title, emoji, cat, locked, joy}
    sim: Callable[[tuple, int], object]          # (events, fixed_until) -> engine.Result (same seed)
    make: Callable[[str], list]                  # option key -> its events at "now"
    drivers: Callable[[], list[dict]]            # tornado rows (sorted ascending by impact)
    turn: int = 0
    end_age: int = 0
    fixed: int = field(default=0)                # fixed_until used for comparisons (play: month, end: 0)

    def option(self, key: str) -> dict | None:
        return next((o for o in self.options if o["key"] == key), None)

    def open_options(self) -> list[dict]:
        return [o for o in self.options if o["locked"] is None] if self.phase == "play" else []


def _trace(name: str, args, result: str) -> dict:
    return {"name": name, "args": "" if args is None else str(args), "result": result}


def _pct(p: float) -> str:
    return f"{p * 100:.0f} %"


# ---------------------------------------------------------------- tools
def check_life_plan(ctx: ChatCtx) -> dict:
    res = ctx.sim(ctx.events, ctx.fixed)
    m = res.metrics
    lines = []
    credit = m["p_credit_future"]
    if credit >= 0.5:
        lines.append(f"In {_pct(credit)} of my simulated lives I {'still ' if ctx.phase == 'play' else ''}"
                     f"need a loan – that is my biggest risk.")
    elif credit >= 0.05:
        lines.append(f"In {_pct(credit)} of lives money gets so tight that I need a loan.")
    else:
        lines.append("I get by without a loan in practically every simulated life.")
    start = ctx.fixed
    liquid = res.path0["liquid"][start:]
    low_i = int(liquid.argmin())
    low_age = ctx.start_age + (start + low_i) // 12
    lines.append(f"My lowest liquid money in this life: {chf(liquid[low_i])} at {low_age}; "
                 f"in the worst 5 % of lives {chf(m['p5_lowest_liquid'])}.")
    houses = [g for g in ctx.groups if g["key"] in ("buy_flat", "buy_house")]
    house_txt = None
    if houses and "p_house_failed" in m:
        if m["p_house_failed"] > 0.01:
            house_txt = f"The purchase ({houses[-1]['title']}) fails for lack of equity in {_pct(m['p_house_failed'])} of lives."
        elif m.get("p_house_unaffordable", 0) > 0.01:
            house_txt = (f"The purchase ({houses[-1]['title']}) works, but in {_pct(m['p_house_unaffordable'])} "
                         f"of lives it fails the affordability check (over ⅓ of gross pay).")
        else:
            house_txt = f"The purchase ({houses[-1]['title']}) is financed and affordable."
    elif ctx.phase == "play":
        flat = ctx.option("buy_flat")
        if flat is not None and flat["locked"]:
            house_txt = f"An own flat is not possible right now: {flat['locked']}."
    if house_txt:
        lines.append(house_txt)
    goals = [g for g in res.goals]
    if goals:
        parts = [f"{GOAL_EN.get(g['goal'], g['goal'])} {_pct(g['p_reached'])}" for g in goals]
        lines.append("Goals reached in: " + ", ".join(parts) + " of lives.")
    result = f"loan {_pct(credit)}, lowest liquidity {chf(liquid[low_i])}"
    return {"text": " ".join(lines), "tool": _trace("check_life_plan", None, result), "suggestion": None}


def compare_option(ctx: ChatCtx, key: str) -> dict:
    opt = ctx.option(key)
    if opt is None:
        return other(ctx)
    if ctx.phase != "play":
        played = [g for g in ctx.groups if g["key"] == key]
        if played:
            return what_if(ctx, played[-1]["id"])
        return {"text": f"The game is over – I can't plan {opt['title']} any more. Ask me instead "
                        f"what your decisions did.",
                "tool": _trace("compare_option", key, "game over"), "suggestion": None}
    if opt["locked"]:
        alt = ""
        if key == "buy_house":
            flat = ctx.option("buy_flat")
            if flat and not flat["locked"]:
                alt = " An own flat would be possible though – ask me about it."
            elif flat:
                alt = f" The own flat is not possible yet either: {flat['locked']}."
        return {"text": f"{opt['emoji']} {opt['title']} is not possible right now: {opt['locked']}.{alt}",
                "tool": _trace("compare_option", key, f"locked: {opt['locked']}"), "suggestion": None}
    stay = ctx.sim(ctx.events, ctx.month).metrics
    res = ctx.sim(tuple(ctx.events) + tuple(ctx.make(key)), ctx.month)
    m = res.metrics
    d = m["median_net_worth_end"] - stay["median_net_worth_end"]
    lines = [f"{opt['emoji']} {opt['title']} now at {ctx.age}: at {ctx.end_age} my median is "
             f"{chf(m['median_net_worth_end'])} – {chf_delta(d)} compared with driving on.",
             f"Range: {chf(m['p5_net_worth_end'])} to {chf(m['p95_net_worth_end'])}.",
             f"Loan risk {_pct(m['p_credit_future'])} (without the decision {_pct(stay['p_credit_future'])})."]
    if "p_house_failed" in m and key in ("buy_flat", "buy_house"):
        if m["p_house_failed"] > 0.01:
            lines.append(f"The purchase fails for lack of equity in {_pct(m['p_house_failed'])} of lives.")
        if m.get("p_house_unaffordable", 0) > 0.01:
            lines.append(f"In {_pct(m['p_house_unaffordable'])} of lives it fails the affordability check.")
        if m["p_house_failed"] <= 0.01 and m.get("p_house_unaffordable", 0) <= 0.01:
            lines.append("Equity and affordability hold in practically every life.")
    result = f"{chf_delta(d)} at {ctx.end_age}, loan {_pct(m['p_credit_future'])}"
    return {"text": " ".join(lines), "tool": _trace("compare_option", key, result),
            "suggestion": {"key": key, "title": opt["title"]}}


def _find_group(ctx: ChatCtx, ref: str | None) -> dict | None:
    if not ctx.groups:
        return None
    if ref:
        for g in ctx.groups:
            if g["id"] == ref:
                return g
        keyed = [g for g in ctx.groups if g["key"] == ref]
        if keyed:
            return keyed[-1]
        return None
    return ctx.groups[-1]


def _biggest_group(ctx: ChatCtx) -> dict | None:
    """The decision group whose removal changes the median end wealth the most (same seed)."""
    if not ctx.groups:
        return None
    base = ctx.sim(ctx.events, ctx.fixed).metrics["median_net_worth_end"]
    best, best_d = None, -1.0
    for g in ctx.groups:
        ids = {id(e) for e in g["events"]}
        wo = ctx.sim(tuple(e for e in ctx.events if id(e) not in ids), ctx.fixed).metrics["median_net_worth_end"]
        if abs(base - wo) > best_d:
            best, best_d = g, abs(base - wo)
    return best


def what_if(ctx: ChatCtx, ref: str | None = None) -> dict:
    biggest = ref == "*"
    g = _biggest_group(ctx) if biggest else _find_group(ctx, ref)
    if biggest:
        ref = None
    if g is None:
        if ref and ctx.option(ref) is not None and ctx.phase == "play":
            return compare_option(ctx, ref)
        return {"text": "I have no decision yet that I could take out. Make a choice – then I'll show you "
                        "what it does in exactly this life.",
                "tool": _trace("what_if", ref, "no decision"), "suggestion": None}
    ids = {id(e) for e in g["events"]}
    without = tuple(e for e in ctx.events if id(e) not in ids)
    with_res = ctx.sim(ctx.events, ctx.fixed)
    wo_res = ctx.sim(without, ctx.fixed)
    life_with = float(with_res.path0["net_worth"][-1])
    life_wo = float(wo_res.path0["net_worth"][-1])
    d_life = life_with - life_wo
    d_med = with_res.metrics["median_net_worth_end"] - wo_res.metrics["median_net_worth_end"]
    g_age = ctx.start_age + g["start_month"] // 12
    verdict = "paid off" if d_life > 0.5 else "cost me money" if d_life < -0.5 else "was neutral"
    text = (("My most impactful decision: " if biggest else "") +
            f"{g['emoji']} {g['title']} (at {g_age}) {verdict}: in exactly this life I have {chf(life_with)} "
            f"at {ctx.end_age} instead of {chf(life_wo)} – {chf_delta(d_life)}. Across all simulated lives "
            f"{chf_delta(d_med)} in the median. Same random numbers, only this decision differs.")
    result = f"{chf_delta(d_life)} in your life, {chf_delta(d_med)} in the median"
    return {"text": text, "tool": _trace("what_if", g["id"], result), "suggestion": None}


def what_matters(ctx: ChatCtx) -> dict:
    rows = list(reversed(ctx.drivers()))[:3]
    if not rows:
        return other(ctx)
    lines = [f"What moves my net worth at {ctx.end_age} the most:"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. {r['parameter']}: at {r['low_label']} {chf_delta(r['low'])}, at {r['high_label']} "
                     f"{chf_delta(r['high'])} in the median.")
    names = ", ".join(r["parameter"] for r in rows)
    return {"text": " ".join(lines), "tool": _trace("what_matters", None, names), "suggestion": None}


def _score(m: dict, joy: int) -> float:
    return m["median_net_worth_end"] - 150_000 * m["p_credit_future"] + 4_000 * joy


def best_next_step(ctx: ChatCtx) -> dict:
    opts = ctx.open_options()
    if not opts:
        if ctx.phase != "play":
            return {"text": "Your life path is fully played. In the dashboard you can move decisions "
                            "and see what that would have changed.",
                    "tool": _trace("best_next_step", None, "game over"), "suggestion": None}
        return {"text": "No option is open right now – driving on is the only step.",
                "tool": _trace("best_next_step", None, "drive on only"), "suggestion": None}
    stay = ctx.sim(ctx.events, ctx.month).metrics
    stay_score = _score(stay, 0)
    ranked = []
    for o in opts:
        m = ctx.sim(tuple(ctx.events) + tuple(ctx.make(o["key"])), ctx.month).metrics
        ranked.append((_score(m, o.get("joy", 0)), o, m))
    ranked.sort(key=lambda x: -x[0])
    score, best, m = ranked[0]
    d = m["median_net_worth_end"] - stay["median_net_worth_end"]
    lead = (f"My suggestion: {best['emoji']} {best['title']}." if score >= stay_score else
            f"No option clearly beats driving on – {best['emoji']} {best['title']} comes closest.")
    text = (f"{lead} Median at {ctx.end_age}: {chf(m['median_net_worth_end'])} ({chf_delta(d)} compared with "
            f"driving on), loan risk {_pct(m['p_credit_future'])}.")
    if len(ranked) > 1:
        text += f" Next best: {ranked[1][1]['title']}."
    text += " Rated by median net worth, loan risk and joy."
    result = f"{best['title']}: {chf_delta(d)}, loan {_pct(m['p_credit_future'])}"
    return {"text": text, "tool": _trace("best_next_step", None, result),
            "suggestion": {"key": best["key"], "title": best["title"]}}


def other(ctx: ChatCtx) -> dict:
    return {"text": "I can't calculate that. Ask me about your life plan, a risk, an option "
                    "like a house or a master, or what a decision did.",
            "tool": None, "suggestion": None}


# ---------------------------------------------------------------- routing
def _norm(text: str) -> str:
    t = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("’", "'")):
        t = t.replace(a, b)
    return t


def _has(t: str, *words: str) -> bool:
    return any(w in t for w in words)


def _option_from_text(ctx: ChatCtx, t: str) -> str | None:
    """Which option key a (normalised) question is about (English and German keywords)."""
    def open_(k):
        o = ctx.option(k)
        return o is not None and o["locked"] is None

    if _has(t, "house", "garden", "haus", "garten"):
        return "buy_house"
    if _has(t, "flat", "apartment", "condo", "property", "real estate", "home",
            "wohnung", "eigentum", "eigenheim", "immobilie"):
        return "buy_flat"
    if "master" in t:
        return "master"
    if "bachelor" in t:
        return "bachelor"
    if _has(t, "apprentice", "lehre"):
        return "lehre"
    if _has(t, "study", "studies", "degree", "university", "college", "studium", "studier") or re.search(r"\buni\b", t):
        return "master" if (open_("master") or any(g["key"] == "bachelor" for g in ctx.groups)) else "bachelor"
    if _has(t, "startup", "start-up", "found", "own business", "gruend"):
        return "startup"
    if _has(t, "training", "course", "weiterbildung", "kurs"):
        return "course"
    if _has(t, "part-time", "part time", "parttime", "teilzeit"):
        return "parttime"
    if _has(t, "job", "switch", "work", "career", "wechsel", "arbeit", "stelle"):
        if ctx.state == "employed":
            return "switch"
        for k in ("job_tech", "job_office", "job_start"):
            if open_(k):
                return k
        return "job_start"
    if _has(t, "wedding", "marry", "married", "hochzeit", "heirat"):
        return "wedding"
    if _has(t, "child", "kid", "baby", "family", "kind", "familie"):
        return "child"
    if "sabbat" in t:
        return "sabbatical12"
    if _has(t, "travel", "trip", "world", "reise", "welt"):
        return "travel"
    if _has(t, "break", "time off", "auszeit"):
        return "sabbatical3"
    if re.search(r"\bcars?\b", t) or "auto" in t:
        return "car"
    if _has(t, "save", "saving", "frugal", "spar"):
        return "frugal"
    return None


def route_offline(ctx: ChatCtx, question: str) -> tuple[str, str | None]:
    """Deterministic keyword router -> (tool name, argument)."""
    t = _norm(question)
    key = _option_from_text(ctx, t)
    if _has(t, "what if", "without", "skipped", "had not", "hadn't", "didn't", "did not", "paid off", "worth it",
            "what did", "was waere", "waere", "haette", "ohne mein", "ohne die", "ohne den", "ohne das", "gebracht",
            "bewirkt", "gelohnt"):
        if key and any(g["key"] == key for g in ctx.groups):
            return "what_if", key
        if not key and _has(t, "biggest", "most important", "largest", "best decision", "groesst", "wichtigst",
                            "am meisten", "staerkst", "beste entscheidung"):
            return "what_if", "*"
        if key and ctx.phase == "play":
            return "compare_option", key
        return "what_if", None
    if _has(t, "risk", "loan", "debt", "credit", "tight", "broke", "enough", "afford", "buffer", "goal",
            "risiko", "kredit", "schulden", "engpass", "pleite", "reicht", "tragbar", "puffer", "ziel"):
        if key in ("buy_flat", "buy_house") and ctx.phase == "play" \
                and not any(g["key"] in ("buy_flat", "buy_house") for g in ctx.groups):
            return "compare_option", key
        return "check_life_plan", None
    if _has(t, "matter", "important", "influence", "driver", "depend", "sensitiv",
            "wichtig", "zaehlt", "einfluss", "beeinfluss", "treiber", "haengt"):
        return "what_matters", None
    if _has(t, "next", "step", "recommend", "suggest", "advice", "advise", "should i", "improve", "better",
            "naechste", "schritt", "empfehl", "empfiehl", "tipp", "raten", "soll ich", "verbesser", "besser"):
        if key and ctx.phase == "play":
            return "compare_option", key
        return "best_next_step", None
    if key in ("buy_flat", "buy_house") and any(g["key"] in ("buy_flat", "buy_house") for g in ctx.groups):
        return "check_life_plan", None
    if key:
        return "compare_option", key
    if _has(t, "plan", "how am i", "where do i stand", "situation", "status", "leisten", "geht es", "stehe", "lage"):
        return "check_life_plan", None
    return "other", None


def choices(ctx: ChatCtx) -> dict[str, str]:
    """Computed actions the LLM may pick from (key -> description)."""
    out = {"check_life_plan": "Check loan risk, cash squeezes, home affordability and goals of the current plan",
           "what_matters": "Explain which assumptions move the net worth the most",
           "best_next_step": "Recommend the best next decision among the open options"}
    for o in ctx.options:
        if ctx.phase == "play":
            out[f"option:{o['key']}"] = f"Calculate option \"{o['title']}\" now" + \
                (f" (locked: {o['locked']})" if o["locked"] else "")
    if ctx.groups:
        out["whatif:*"] = "Which past decision had the biggest effect (what if it had not been made)?"
    for g in ctx.groups:
        out[f"whatif:{g['id']}"] = f"What if the decision \"{g['title']}\" at " \
                                   f"{ctx.start_age + g['start_month'] // 12} had not been made?"
    out["other"] = "The question is outside this financial simulation"
    return out


def route_llm(ctx: ChatCtx, question: str) -> tuple[str, str | None]:
    acts = choices(ctx)
    reply = request_chat([
        {"role": "system", "content": "Pick only the key of the matching action from the given JSON. "
                                      "Prefer a concrete option when the question is about a specific decision."},
        {"role": "user", "content": json.dumps({"question": question, "age": ctx.age, "status": ctx.state,
                                                "actions": acts}, ensure_ascii=False) + " /no_think"},
    ], {"type": "object", "properties": {"choice": {"type": "string", "enum": list(acts)}},
        "required": ["choice"], "additionalProperties": False})
    choice = reply.get("choice") if isinstance(reply, dict) else None
    if choice not in acts:
        raise ValueError("unknown action")
    if choice.startswith("option:"):
        return "compare_option", choice.split(":", 1)[1]
    if choice.startswith("whatif:"):
        return "what_if", choice.split(":", 1)[1]
    return choice, None


def run_tool(ctx: ChatCtx, name: str, arg: str | None) -> dict:
    if name == "check_life_plan":
        return check_life_plan(ctx)
    if name == "compare_option" and arg:
        return compare_option(ctx, arg)
    if name == "what_if":
        return what_if(ctx, arg)
    if name == "what_matters":
        return what_matters(ctx)
    if name == "best_next_step":
        return best_next_step(ctx)
    return other(ctx)


def answer(ctx: ChatCtx, question: str) -> dict:
    """Route (LLM if available, else keywords) and compute the reply.

    Returns {'text', 'tools': [trace], 'suggestion', 'mode': 'llm'|'offline', 'tool': name}."""
    question = (question or "").strip()[:MAX_QUESTION]
    mode, routed = "offline", None
    if status()["available"]:
        try:
            routed = route_llm(ctx, question)
            mode = "llm"
        except Exception:
            routed = None
    if routed is None:
        routed = route_offline(ctx, question)
    name, arg = routed
    out = run_tool(ctx, name, arg)
    return {"text": out["text"], "tools": [out["tool"]] if out.get("tool") else [],
            "suggestion": out.get("suggestion"), "mode": mode, "tool": name}


# ---------------------------------------------------------------- station openers (adapted from dialog.cjs STAGES)
STAGES = {
    "First job": ("Check how long your savings last with the income you have during your education.",
                  "Do you want to finish a degree first or start earning money right away?"),
    "Education": ("Keep an eye on your buffer while tuition fees or low pay are running.",
                  "Will your income last until you graduate, or do you need a reserve?"),
    "Housing": ("Besides the equity, also check the running housing costs after buying.",
                "What matters more to you: a home of your own early, or a thicker buffer?"),
    "Family": ("Test the cost of a child together with your buffer before you decide.",
               "Does a wedding or a child fit your monthly budget right now?"),
    "Time off": ("For a break, plan the running costs on top of the travel budget.",
                 "Do you want to test a short break or a whole sabbatical year?"),
    "Savings plan": ("Compare your monthly investments with the surplus you actually have.",
                     "When might you need the money from your savings plan again?"),
    "Review": ("Look at the cash squeezes first, then decide which life decision should stay.",
               "Which decision do you want to move in the dashboard to see the difference?"),
}
ROTATION = ("Housing", "Family", "Time off", "Savings plan")


def stage_for(phase: str, state: str, turn: int, studying: bool = False) -> str:
    """in education -> First job (while a degree runs: alternating with Education),
    employed/self-employed -> Housing/Family/Time off/Savings plan rotating, end -> Review."""
    if phase == "end":
        return "Review"
    if state in ("employed", "self_employed"):
        return ROTATION[turn % len(ROTATION)]
    if studying and turn % 2:
        return "Education"
    return "First job"


def opener(phase: str, state: str, turn: int, age: int, studying: bool = False) -> dict:
    stage = stage_for(phase, state, turn, studying)
    tip, question = STAGES[stage]
    head = "Review" if stage == "Review" else f"Station {age} · {stage}"
    return {"role": "twin", "text": f"{head}: {tip} {question}", "tools": [], "suggestion": None, "stage": stage}


def trim(messages: list[dict]) -> list[dict]:
    return messages[-MAX_MESSAGES:]


def chat_block(messages: list[dict], phase: str, mode: str | None) -> dict:
    st = status()
    return {"available": bool(st["available"]), "model": st["model"],
            "mode": mode or ("llm" if st["available"] else "offline"),
            "messages": [dict(m) for m in trim(messages)],
            "prompts": list(PROMPTS_END if phase == "end" else PROMPTS_PLAY)}
