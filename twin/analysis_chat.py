"""Twin chat for the analysis page: an avatar that gives tips and answers "what if" questions.

Design (after the danilel-juli-merge ``twin/agent.py``, which follows Juli's ``agent.cjs``): the language model is
only a ROUTER. It picks exactly one computed tool (JSON-schema constrained answer ``{"tool", "age", "price"}``);
every number in the reply is templated from ``twin.engine.simulate`` / ``twin.tipps`` / ``twin.analysis``
results. Without Ollama (or on any error / timeout) a deterministic keyword router (English and German) picks
the same tools, so the demo never hangs; ``mode`` says which router was used.

Tools: ``house`` (buy at age X for price Y) · ``strategy`` (investment styles side by side) · ``pillar3a`` ·
``savings`` · ``crisis`` (job loss / market crash) · ``drivers`` (what matters most, tornado) · ``plan`` (how am
I doing) · ``ride`` (what the film ride / new data showed) · ``decisions`` (what I played) · ``tips`` · ``other``.

Environment: ``TWIN_OLLAMA_URL`` (default http://127.0.0.1:11434), ``TWIN_OLLAMA_MODEL`` (default qwen3:4b),
``TWIN_OLLAMA_TIMEOUT`` (seconds for one request, default 8), ``TWIN_CHAT_PHRASE=1`` lets the model also re-phrase
the answer (accepted only if every number stays exactly the same).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from .avatar import COLORS, HAIR_COLORS, SKIN, Avatar
from .calibration import Calibration, Person
from .config import Assumptions
from .engine import simulate
from .scenarios import HouseBuy, MarketCrash, Unemployment
from .tipps import STYLES, tipps

DISCLAIMER = "Not investment advice."
MAX_QUESTION = 400
MAX_YEARS = 50                       # engine horizon limit (kept conservative)
HOUSE_PRICE = 850_000                # default price, same as the game's "Buy a home" card
STATUS_TTL = 30.0
STATUS_TIMEOUT = 1.0
TOOLS = ("house", "strategy", "pillar3a", "savings", "crisis", "drivers", "plan", "ride", "decisions", "tips",
         "other")
TOOL_HELP = {
    "house": "Buy a house or flat (optionally at an age and for a price): net worth, range, credit risk, equity",
    "strategy": "Compare the investment styles (cash, cautious, balanced, bold) for this person",
    "pillar3a": "Is pillar 3a (Swiss private pension) worth it for this person?",
    "savings": "How to save more, emergency fund, budget, spending, rent",
    "crisis": "What if I lose my job or the market crashes?",
    "drivers": "Which assumptions matter most for the result",
    "plan": "How am I doing overall: net worth, range, credit risk, goals",
    "ride": "What the film ride / the newly uploaded data showed",
    "decisions": "The decisions played in the game",
    "tips": "General tips: what could I do better?",
    "other": "The question is outside this financial simulation",
}


# ---------------------------------------------------------------- formatting
def chf(v: float) -> str:
    return ("CHF −" if v < -0.5 else "CHF ") + f"{abs(v):,.0f}".replace(",", "'")


def chf_delta(v: float) -> str:
    return ("+" if v > 0.5 else "−" if v < -0.5 else "±") + f"CHF {abs(v):,.0f}".replace(",", "'")


def pct(p: float) -> str:
    return f"{p * 100:.0f} %"


# ---------------------------------------------------------------- Ollama (loopback, short timeouts)
def ollama_url() -> str:
    return os.environ.get("TWIN_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def model_name() -> str:
    return os.environ.get("TWIN_OLLAMA_MODEL", "qwen3:4b")


def _open(req, timeout: float):
    """urlopen that never routes a loopback Ollama through an HTTP proxy."""
    url = req if isinstance(req, str) else req.full_url
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("127.0.0.1", "localhost", "::1"):
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


_status_cache: dict = {"t": -1e9, "value": None, "key": None}


def status(force: bool = False) -> dict:
    """{'available': bool, 'model': str}: one GET /api/tags with a short timeout, cached for 30 s."""
    key = (ollama_url(), model_name())
    now = time.monotonic()
    if not force and _status_cache["value"] is not None and _status_cache["key"] == key \
            and now - _status_cache["t"] < STATUS_TTL:
        return dict(_status_cache["value"])
    model, available = model_name(), False
    try:
        with _open(ollama_url() + "/api/tags", STATUS_TIMEOUT) as r:
            models = json.loads(r.read().decode("utf-8")).get("models") or []
        available = any(m.get("name") == model or m.get("model") == model for m in models if isinstance(m, dict))
    except Exception:
        available = False
    value = {"available": available, "model": model}
    _status_cache.update(t=now, value=value, key=key)
    return dict(value)


def request_chat(messages: list[dict], fmt: dict | None = None, max_tokens: int = 48, temperature: float = 0.1,
                 timeout: float | None = None):
    """POST /api/chat (no streaming, ``think: false``). With ``fmt`` the JSON answer is parsed, else the text."""
    timeout = float(os.environ.get("TWIN_OLLAMA_TIMEOUT", "8")) if timeout is None else timeout
    body = {"model": model_name(), "think": False, "stream": False, "keep_alive": "15m", "messages": messages,
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096}}
    if fmt is not None:
        body["format"] = fmt
    req = urllib.request.Request(ollama_url() + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with _open(req, timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    content = data["message"]["content"]
    return json.loads(content) if fmt is not None else str(content)


# ---------------------------------------------------------------- context
@dataclass
class ChatCtx:
    """Everything the tools need. The analysis page builds it from its person, horizon and assumptions."""
    person: Person
    years: int = 10
    a: Assumptions = field(default_factory=Assumptions)
    events: tuple = ()
    calib: Calibration | None = None
    n_paths: int = 1000
    seed: int = 0
    name: str | None = None                          # player / avatar name
    decisions: list[dict] = field(default_factory=list)   # [{"age", "emoji", "title"}] played in the game
    ride: dict | None = None                         # film ride: {"statements": [...], "months": n, ...}
    sim: Callable | None = None                      # (events: tuple, years, a) -> engine.Result (e.g. cached)
    tips_fn: Callable | None = None                  # () -> tipps(...) dict
    drivers_fn: Callable | None = None               # () -> (base, rows) as twin.analysis.tornado
    _tips: dict | None = field(default=None, repr=False)

    def run(self, events=None, years: int | None = None, a: Assumptions | None = None):
        events = tuple(self.events if events is None else events)
        years = int(years or self.years)
        a = a or self.a
        if self.sim is not None:
            return self.sim(events, years, a)
        return simulate(self.person, list(events), years, a, self.n_paths, self.seed, calib=self.calib)

    def tips(self) -> dict:
        if self._tips is None:
            self._tips = self.tips_fn() if self.tips_fn else tipps(self.person, self.calib, self.a, self.years,
                                                                   800, self.seed)
        return self._tips

    def drivers(self) -> tuple[float, list[dict]]:
        if self.drivers_fn is not None:
            return self.drivers_fn()
        from .analysis import tornado
        return tornado(self.person, list(self.events), self.years, self.a, self.calib, 400, self.seed)

    @property
    def end_age(self) -> int:
        return self.person.age + self.years


def _out(tool: str, text: str, args: dict | None = None, numbers: dict | None = None) -> dict:
    return {"tool": tool, "text": text, "args": dict(args or {}), "numbers": dict(numbers or {})}


# ---------------------------------------------------------------- tools (all numbers from our model)
def house_tool(ctx: ChatCtx, age: int | None = None, price: float | None = None) -> dict:
    p = ctx.person
    note = ""
    age = p.age if age is None else int(age)
    if age < p.age:
        note = f"{age} is behind you, so I calculate the purchase for now ({p.age}). "
        age = p.age
    if age - p.age > MAX_YEARS - 5:
        note = f"That is too far ahead for the simulation, so I take age {p.age + MAX_YEARS - 5}. "
        age = p.age + MAX_YEARS - 5
    price = float(HOUSE_PRICE if not price else min(max(float(price), 100_000), 10_000_000))
    month = (age - p.age) * 12
    years = min(MAX_YEARS, max(ctx.years, age - p.age + 10))
    base = ctx.run(ctx.events, years)
    res = ctx.run(tuple(ctx.events) + (HouseBuy(month, price, "House purchase"),), years)
    m, b = res.metrics, base.metrics
    so = ctx.a.social
    need = price * (so.min_equity + so.purchase_fees)
    liquid = float(base.percentiles["liquid"][2, month])
    end_age = p.age + years
    d = m["median_net_worth_end"] - b["median_net_worth_end"]
    failed, unaff = m.get("p_house_failed", 0.0), m.get("p_house_unaffordable", 0.0)
    when = "now" if month == 0 else f"at {age}"
    lines = [f"{note}Buying a {chf(price)} home {when}: at {end_age} your median net worth is "
             f"{chf(m['median_net_worth_end'])} ({chf_delta(d)} compared with renting on), "
             f"90 % range {chf(m['p5_net_worth_end'])} to {chf(m['p95_net_worth_end'])}.",
             f"You need about {chf(need)} of your own money (20 % equity + 2 % fees, today's prices); "
             f"the median of your liquid money {'today' if month == 0 else f'at {age}'} is {chf(liquid)}."]
    if failed > 0.01:
        lines.append(f"With UBS as the lender, the purchase fails for lack of equity in {pct(failed)} of the "
                     f"simulated lives.")
    if unaff > 0.01:
        lines.append(f"In {pct(unaff)} of lives it breaks the affordability rule (costs over ⅓ of gross income) – "
                     f"UBS would probably not grant this mortgage{'' if price <= 500_000 else '; a cheaper home helps'}.")
    if failed <= 0.01 and unaff <= 0.01:
        lines.append("Equity and affordability hold in practically every simulated life.")
    lines.append(f"Credit risk: {pct(m['p_ever_credit'])} (without the purchase {pct(b['p_ever_credit'])}).")
    nums = {"age": age, "price": price, "month": month, "years": years,
            "median": m["median_net_worth_end"], "p5": m["p5_net_worth_end"], "p95": m["p95_net_worth_end"],
            "p_credit": m["p_ever_credit"], "p_failed": failed, "p_unaffordable": unaff, "delta": d,
            "need": need, "liquid": liquid}
    return _out("house", " ".join(lines), {"age": age, "price": price}, nums)


def strategy_tool(ctx: ChatCtx) -> dict:
    rows = []
    for key, label, strat in STYLES:
        m = ctx.run(ctx.events, ctx.years, ctx.a.with_(strategy=strat)).metrics
        rows.append({"key": key, "label": label, "median": m["median_net_worth_end"], "p5": m["p5_net_worth_end"],
                     "p95": m["p95_net_worth_end"], "p_credit": m["p_ever_credit"]})
    cash, best = rows[0], max(rows, key=lambda r: r["median"])
    parts = " · ".join(f"{r['label']} {chf(r['median'])}" for r in rows)
    text = (f"Same random numbers, only the investment style changes. Median net worth at {ctx.end_age}: {parts}. "
            f"Highest median: {best['label']}")
    if best is not cash:
        text += (f" ({chf_delta(best['median'] - cash['median'])} vs keeping cash), but in the worst 5 % of lives it "
                 f"ends at {chf(best['p5'])} (cash: {chf(cash['p5'])}).")
    else:
        text += " – investing does not pay off here, the buffer comes first."
    risky = max(rows, key=lambda r: r["p_credit"])
    if risky["p_credit"] > 0.05:
        text += f" Credit risk is highest with {risky['label']} ({pct(risky['p_credit'])})."
    return _out("strategy", text, {}, {"styles": rows})


def _tip(ctx: ChatCtx, *words: str) -> dict | None:
    for t in ctx.tips()["tips"]:
        if any(w in t["title"].lower() for w in words):
            return t
    return None


def pillar3a_tool(ctx: ChatCtx) -> dict:
    p = ctx.person
    buffer = p.cash / p.expenses if p.expenses > 0 else 99.0
    if p.state not in (1, 3):
        text = (f"Pillar 3a needs income from work (AHV-liable). As someone {p.status.lower()} you can start once "
                f"you earn a salary. Until then: build your emergency fund (now {buffer:.1f} months of expenses).")
    elif p.mu <= 0:
        text = (f"Not yet: your typical month is {chf(p.mu)}, so there is nothing left to put away. First get the "
                f"monthly budget positive and an emergency fund of 3 months ({chf(3 * p.expenses)}), then 3a.")
    elif buffer < 3:
        text = (f"Your typical month leaves {chf(p.mu)}, but your cash covers only {buffer:.1f} months of expenses. "
                f"Fill the emergency fund first (3 months = {chf(3 * p.expenses)}) – 3a money is locked until "
                f"retirement – then pay into pillar 3a.")
    else:
        text = (f"Likely yes: your typical month leaves {chf(p.mu)} and your emergency fund covers {buffer:.1f} "
                f"months. Paying into pillar 3a lowers your taxes and builds your pension at the same time; "
                f"the money is locked until retirement (except home purchase or self-employment).")
    text += " The tax effect is simplified and not part of this simulation."
    return _out("pillar3a", text, {}, {"mu": p.mu, "buffer_months": buffer})


def savings_tool(ctx: ChatCtx) -> dict:
    p = ctx.person
    tips = [t for t in ctx.tips()["tips"] if t["kind"] in ("warn", "do")
            and any(w in t["title"].lower() for w in ("spend", "saving", "emergency", "rent", "debt", "goal", "swing",
                                                      "idle", "credit"))][:3]
    rate = p.mu / p.income if p.income > 0 else 0.0
    head = (f"Your typical month: {chf(p.mu)}" + (f" ({rate:.0%} of your income)" if p.income > 0 else "") +
            f", expenses about {chf(p.expenses)}.")
    if tips:
        body = " ".join(f"{t['icon']} {t['title']}: {t['text']}" for t in tips)
    else:
        good = _tip(ctx, "strong savings", "emergency fund in place")
        body = f"{good['icon']} {good['title']}: {good['text']}" if good else "Your budget looks solid."
    return _out("savings", f"{head} {body}", {}, {"mu": p.mu, "rate": rate})


def crisis_tool(ctx: ChatCtx, kind: str = "job") -> dict:
    t = min(12, ctx.years * 12 - 1)
    ev = Unemployment(t, 6, "Job loss") if kind != "crash" else MarketCrash(t, -0.35, "Market crash")
    what = "you lose your job for 6 months" if kind != "crash" else "the stock market drops 35 %"
    base = ctx.run(ctx.events).metrics
    m = ctx.run(tuple(ctx.events) + (ev,)).metrics
    d = m["median_net_worth_end"] - base["median_net_worth_end"]
    text = (f"If {what} {'in a year' if t == 12 else 'soon'}: median net worth at {ctx.end_age} "
            f"{chf(m['median_net_worth_end'])} ({chf_delta(d)}), credit risk {pct(m['p_ever_credit'])} "
            f"(without the crisis {pct(base['p_ever_credit'])}), lowest liquid money in the worst 5 % of lives "
            f"{chf(m['p5_lowest_liquid'])}.")
    if kind != "crash" and m.get("p_alv_exhausted", 0) > 0.01:
        text += f" Unemployment benefits run out in {pct(m['p_alv_exhausted'])} of lives."
    text += " A buffer of 3–6 months of expenses is what absorbs this." if m["p_ever_credit"] > base["p_ever_credit"] \
        else " Your buffer absorbs it."
    return _out("crisis", text, {"kind": "crash" if kind == "crash" else "job"},
                {"median": m["median_net_worth_end"], "delta": d, "p_credit": m["p_ever_credit"]})


def drivers_tool(ctx: ChatCtx) -> dict:
    base, rows = ctx.drivers()
    top = list(reversed(rows))[:3]
    if not top:
        return other_tool(ctx)
    parts = [f"{i}. {r['parameter']}: {r['low_label']} {chf_delta(r['low'])}, {r['high_label']} {chf_delta(r['high'])}"
             for i, r in enumerate(top, 1)]
    text = (f"What moves your median net worth at {ctx.end_age} (base {chf(base)}) the most: " + "; ".join(parts) +
            ". If you are unsure about these, check them first.")
    return _out("drivers", text, {}, {"base": base, "rows": top})


def plan_tool(ctx: ChatCtx) -> dict:
    res = ctx.run()
    m = res.metrics
    text = (f"With your current plan: median net worth at {ctx.end_age} {chf(m['median_net_worth_end'])}, 90 % range "
            f"{chf(m['p5_net_worth_end'])} to {chf(m['p95_net_worth_end'])}. ")
    if m["p_ever_credit"] >= 0.05:
        text += f"In {pct(m['p_ever_credit'])} of the simulated lives you need credit at some point. "
    else:
        text += "You get by without credit in practically every simulated life. "
    text += f"Lowest liquid money in the worst 5 %: {chf(m['p5_lowest_liquid'])}."
    if res.goals:
        text += " Goals: " + ", ".join(f"{g['goal']} {pct(g['p_reached'])}" for g in res.goals) + " of lives."
    return _out("plan", text, {}, {"median": m["median_net_worth_end"], "p_credit": m["p_ever_credit"]})


def ride_tool(ctx: ChatCtx) -> dict:
    st = list((ctx.ride or {}).get("statements") or [])
    if not st:
        return _out("ride", "You have not done the film ride yet. In the game, start with your data (or the example "
                            "data) and I will update myself with the new months.")
    months = (ctx.ride or {}).get("months")
    head = f"The film ride with {months} months of new data showed: " if months else "The film ride showed: "
    return _out("ride", head + " ".join(str(s) for s in st[:4]), {}, {"statements": st[:4]})


def decisions_tool(ctx: ChatCtx) -> dict:
    if not ctx.decisions:
        return _out("decisions", "You have not played any decisions yet. In the game every card shows its effect "
                                 "before you choose it.")
    items = ", ".join(f"{d.get('emoji', '')} {d.get('title', '')} ({d.get('age')})".strip() for d in ctx.decisions[:8])
    return _out("decisions", f"In the game you chose: {items}. Ask me about any of them, e.g. a house at another age.")


def tips_tool(ctx: ChatCtx, n: int = 3) -> dict:
    tips = ctx.tips()["tips"][:n]
    text = " ".join(f"{t['icon']} {t['title']}: {t['text']}" for t in tips) or "No tips – your numbers look solid."
    return _out("tips", text, {}, {"titles": [t["title"] for t in tips]})


def other_tool(ctx: ChatCtx) -> dict:
    return _out("other", "I can only answer with numbers from your simulation. Ask me e.g. “What if I buy a house at "
                         f"{max(ctx.person.age + 5, 30)}?”, “Is pillar 3a worth it?”, “Which investment style?”, "
                         "“What if I lose my job?” or “What matters most?”.")


def run_tool(ctx: ChatCtx, tool: str, args: dict | None = None) -> dict:
    args = args or {}
    if tool == "house":
        return house_tool(ctx, args.get("age"), args.get("price"))
    if tool == "crisis":
        return crisis_tool(ctx, args.get("kind") or "job")
    fn = {"strategy": strategy_tool, "pillar3a": pillar3a_tool, "savings": savings_tool, "drivers": drivers_tool,
          "plan": plan_tool, "ride": ride_tool, "decisions": decisions_tool, "tips": tips_tool}.get(tool, other_tool)
    return fn(ctx)


# ---------------------------------------------------------------- argument parsing
def _norm(text: str) -> str:
    t = (text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("’", "'")):
        t = t.replace(a, b)
    return t


def _has(t: str, *words: str) -> bool:
    """True if one of the words starts a word in ``t`` (so "rent" does not match "current")."""
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w), t) for w in words)


def parse_age(text: str, now_age: int) -> int | None:
    t = _norm(text)
    m = re.search(r"\bin\s+(\d{1,2})\s*(?:years?|yrs?|y\b|jahren?|j\b)", t)
    if m:
        return now_age + int(m.group(1))
    m = re.search(r"\b(?:at|age|aged|with|mit|alter|when i(?:'m| am)|by|turn)\s*(?:the age of|age|von)?\s*(\d{2})\b"
                  r"(?!\s*(?:k\b|'|’|,\d|\.\d|000|m\b|mio|million|tsd|thousand|%))", t)
    if m and 16 <= int(m.group(1)) <= 95:
        return int(m.group(1))
    if _has(t, "next year", "naechstes jahr", "in a year", "in einem jahr"):
        return now_age + 1
    if _has(t, "now", "today", "jetzt", "heute", "right away", "sofort"):
        return now_age
    return None


_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:['’,]\d{3})+|\d+(?:[.,]\d+)?)\s*"
                  r"(k\b|m\b|mio\b|mio\.|million|millionen|mn\b|tsd\b|thousand|'000)?")


def parse_price(text: str) -> float | None:
    t = _norm(text)
    for m in _NUM.finditer(t):
        raw, suf = m.group(1), (m.group(2) or "").strip(".")
        if re.search(r"['’,]\d{3}", raw):
            v = float(re.sub(r"['’,]", "", raw))
        else:
            v = float(raw.replace(",", "."))
        v *= {"k": 1e3, "tsd": 1e3, "thousand": 1e3, "'000": 1e3, "m": 1e6, "mio": 1e6, "mn": 1e6,
              "million": 1e6, "millionen": 1e6}.get(suf, 1.0)
        if 50_000 <= v <= 20_000_000:
            return v
    return None


# ---------------------------------------------------------------- routing
def route_offline(ctx: ChatCtx, question: str) -> tuple[str, dict]:
    """Deterministic keyword router (English + German) -> (tool, args)."""
    t = _norm(question)
    if _has(t, "house", "home", "flat", "apartment", "condo", "property", "real estate", "mortgage",
            "haus", "wohnung", "eigenheim", "immobilie", "hypothek", "eigentum"):
        return "house", {"age": parse_age(question, ctx.person.age), "price": parse_price(question)}
    if _has(t, "lose my job", "lost my job", "job loss", "jobloss", "unemploy", "fired", "laid off",
            "jobverlust", "arbeitslos", "kuendigung", "job verlier"):
        return "crisis", {"kind": "job"}
    if _has(t, "crash", "recession", "market drop", "market fall", "bear market", "boersencrash", "rezession", "krise"):
        return "crisis", {"kind": "crash"}
    if _has(t, "3a", "pillar", "saeule", "pension", "retirement sav", "vorsorge", "altersvorsorge"):
        return "pillar3a", {}
    if _has(t, "invest", "strategy", "stock", "etf", "portfolio", "equit", "cautious", "balanced", "bold", "risky",
            "anlage", "aktie", "strategie", "anlegen", "fonds"):
        return "strategy", {}
    if _has(t, "matter", "important", "influence", "driver", "depend", "sensitiv", "assumption",
            "wichtig", "einfluss", "haengt", "annahme"):
        return "drivers", {}
    if _has(t, "film", "ride", "new data", "my data", "csv", "upload", "update", "fahrt", "neue daten"):
        return "ride", {}
    if _has(t, "decision", "played", "my choices", "in the game", "entscheidung", "gespielt", "im spiel"):
        return "decisions", {}
    if _has(t, "save", "saving", "budget", "emergency", "buffer", "spend", "expens", "cost", "rent", "debt",
            "spar", "notgroschen", "puffer", "ausgaben", "kosten", "miete", "schulden"):
        return "savings", {}
    if _has(t, "tip", "advice", "advise", "improve", "better", "recommend", "suggest", "should i",
            "tipp", "ratschlag", "verbesser", "besser", "empfehl", "soll ich"):
        return "tips", {}
    if _has(t, "plan", "how am i", "how do i", "where do i stand", "situation", "status", "risk", "credit", "afford",
            "enough", "net worth", "future", "kredit", "risiko", "reicht", "vermoegen", "zukunft", "wie steh"):
        return "plan", {}
    return "other", {}


def route_llm(ctx: ChatCtx, question: str) -> tuple[str, dict]:
    """The model picks one tool + its arguments (0 = not mentioned) via a JSON-schema constrained answer."""
    reply = request_chat([
        {"role": "system", "content": "You route questions of a personal finance simulator. Pick the one tool "
                                      "that answers the question. Fill age (years) and price (CHF) only if the "
                                      "question mentions them, else 0. Answer JSON only."},
        {"role": "user", "content": json.dumps({"question": question, "person_age": ctx.person.age,
                                                "tools": TOOL_HELP}, ensure_ascii=False) + " /no_think"},
    ], {"type": "object", "properties": {"tool": {"type": "string", "enum": list(TOOLS)},
                                         "age": {"type": "integer"}, "price": {"type": "integer"}},
        "required": ["tool", "age", "price"], "additionalProperties": False})
    tool = reply.get("tool") if isinstance(reply, dict) else None
    if tool not in TOOLS:
        raise ValueError("unknown tool")
    args: dict = {}
    if tool == "house":
        age, price = parse_age(question, ctx.person.age), parse_price(question)   # the text wins over the model
        try:
            llm_age, llm_price = int(reply.get("age") or 0), float(reply.get("price") or 0)
        except (TypeError, ValueError):
            llm_age, llm_price = 0, 0.0
        args = {"age": age if age is not None else (llm_age if 16 <= llm_age <= 95 else None),
                "price": price if price is not None else (llm_price if 50_000 <= llm_price <= 20_000_000 else None)}
    elif tool == "crisis":
        args = {"kind": "crash" if _has(_norm(question), "crash", "market", "boerse", "rezession", "recession")
                else "job"}
    return tool, args


_NUM_TOKEN = re.compile(r"\d[\d'’.,]*")


def _numbers(text: str) -> list[str]:
    return sorted(re.sub(r"[.,]$", "", x) for x in _NUM_TOKEN.findall(text))


def phrase(text: str) -> str:
    """Optional: let the model shorten the wording. Accepted only if every number is unchanged."""
    try:
        out = request_chat([
            {"role": "system", "content": "Rewrite the message for the user: friendly, short, plain English, second "
                                          "person. Keep every number exactly as written. No new facts."},
            {"role": "user", "content": text + " /no_think"}], None, max_tokens=220, temperature=0.2)
        out = re.sub(r"<think>.*?</think>", "", str(out), flags=re.S).strip()
        return out if out and _numbers(out) == _numbers(text) else text
    except Exception:
        return text


def answer(ctx: ChatCtx, question: str) -> dict:
    """Route (LLM if available, else keywords) and compute the reply with our model.

    Returns {'text', 'tool', 'args', 'numbers', 'mode': 'llm'|'offline'}; the text ends with the disclaimer."""
    question = (question or "").strip()[:MAX_QUESTION]
    mode, routed = "offline", None
    if question and status()["available"]:
        try:
            routed = route_llm(ctx, question)
            mode = "llm"
        except Exception:
            routed = None
    if routed is None:
        routed = route_offline(ctx, question)
    tool, args = routed
    try:
        out = run_tool(ctx, tool, args)
    except Exception:                       # never break the page because of a question (but log why)
        logging.getLogger(__name__).exception("twin chat tool %s failed for %r", tool, question)
        out = other_tool(ctx)
    text = out["text"]
    if mode == "llm" and os.environ.get("TWIN_CHAT_PHRASE") == "1":
        text = phrase(text)
    return {**out, "text": f"{text} {DISCLAIMER}", "mode": mode}


def greeting(ctx: ChatCtx, n: int = 3) -> dict:
    """Proactive first message: 2–3 tips from ``tipps()`` (+ the film ride, if any). Also a short bubble text."""
    who = ctx.name or ctx.person.name
    tips = ctx.tips()["tips"][:max(2, min(n, 3))]
    lines = [f"Hi {who}! I'm your financial twin – I ran your numbers {ctx.years} years ahead. "
             f"{'Three' if len(tips) >= 3 else 'Two' if len(tips) == 2 else 'A few'} things stand out:"]
    lines += [f"{i}. {t['icon']} **{t['title']}** – {t['text']}" for i, t in enumerate(tips, 1)]
    st = list((ctx.ride or {}).get("statements") or [])
    if st:
        lines.append(f"🎬 From your film ride: {st[0]}")
    if ctx.decisions:
        lines.append("🎮 In the game you chose " + ", ".join(f"{d.get('emoji', '')} {d.get('title', '')}".strip()
                                                         for d in ctx.decisions[:4]) + ".")
    lines.append(f"Ask me anything, e.g. “What if I buy a house at {max(ctx.person.age + 5, 30)}?” {DISCLAIMER}")
    bubble = f"Hi {who}! " + (" · ".join(f"{t['icon']} {t['title']}" for t in tips) if tips
                              else "Your numbers look solid.")
    return {"text": "\n\n".join(lines), "bubble": bubble, "tool": "tips", "mode": "offline",
            "numbers": {"titles": [t["title"] for t in tips]}}


def suggestions(ctx: ChatCtx) -> list[str]:
    return [f"What if I buy a house at {max(ctx.person.age + 5, 30)}?", "Is pillar 3a worth it?",
            "Which investment style suits me?", "What if I lose my job?", "What matters most?"]


# ---------------------------------------------------------------- avatar: 3D game config -> SVG kit
_HAIR = {"kurz": "kurz", "lang": "lang", "dutt": "dutt", "locken": "locken", "pferdeschwanz": "pferdeschwanz",
         "afro": "afro", "iro": "undercut", "glatze": "glatze"}
_HAT = {"keiner": "keine", "keine": "keine", "cap": "cap", "beanie": "beanie", "kopfhoerer": "kopfhoerer",
        "strohhut": "cap", "partyhut": "beanie"}
_OUTFIT = {"hoodie": "hoodie", "tshirt": "tshirt", "hemd": "hemd", "kleid": "tshirt", "sport": "tshirt",
           "jacke": "jacke"}


def avatar_from_cfg(cfg: dict | None, fallback_name: str = "Alex") -> Avatar:
    """Map the 3D creator config (gender, skin, hair, hairColor, hat, outfit, color, car) onto the SVG kit."""
    cfg = cfg if isinstance(cfg, dict) else {}
    pick = lambda v, table, default: v if v in table else default
    color = pick(cfg.get("color"), COLORS, "blau")
    return Avatar(name=str(cfg.get("name") or fallback_name)[:24],
                  skin=pick(cfg.get("skin"), SKIN, "rosig"),
                  hair=_HAIR.get(cfg.get("hair"), "kurz"),
                  hair_color=pick(cfg.get("hairColor"), HAIR_COLORS, "braun"),
                  outfit=_OUTFIT.get(cfg.get("outfit"), "hoodie"), outfit_color=color,
                  hat=_HAT.get(cfg.get("hat"), "keine"), hat_color="orange" if color != "orange" else "navy",
                  car_color=pick(cfg.get("car"), COLORS, "rot"))
