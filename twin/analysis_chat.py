"""Twin chat for the analysis page: an avatar that gives tips and answers "what if" questions.

Design (after the danilel-juli-merge ``twin/agent.py``, which follows Juli's ``agent.cjs``): the language model is
only a ROUTER. It picks exactly one computed tool (JSON-schema constrained answer ``{"tool", "age", "price"}``);
every number in the reply is templated from ``twin.engine.simulate`` / ``twin.tipps`` / ``twin.analysis``
results. Without Ollama (or on any error / timeout) a deterministic keyword router (English and German) picks
the same tools, so the demo never hangs; ``mode`` says which router was used.

Tools: ``edit_plan`` (the user says what should happen in their life – "I buy a house at 35 for 800k", "add a child
at 30", "move the house to 40", "remove the gap year", "ich gehe mit 62 in Rente": the twin adds / moves / removes
that game option on the plan, computes the effect on the net worth at the end with the same seed, and returns the
edit as ``plan_edit`` for the PAGE to apply – the chat never changes any state itself) ·
``house`` (what if I buy at age X for price Y) · ``strategy`` (investment styles side by side) · ``pillar3a`` ·
``savings`` · ``crisis`` (job loss / market crash) · ``drivers`` (what matters most, tornado) · ``plan`` (how am
I doing) · ``ride`` (what the film ride / new data showed) · ``decisions`` (what I played) · ``review`` (did I do
well in the game, what could I have done better: from ``twin.review``) · ``suggest`` (another path for the played
life: the twin's moves / other life decisions with their effect at 85, from ``twin.alt_path.suggestions``; applying
one stays a click on the page) · ``tips`` · ``other``.

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

PLAN_KEYS = ("bachelor", "master", "lehre", "grad_job", "job_start", "switch", "parttime", "retire", "buy_house",
             "flat", "costs", "wedding", "child", "gap_year")       # the game's options = what the plan can hold
PLAN_OPS = ("add", "move", "remove")
from .tipps import STYLES, tipps

DISCLAIMER = "Not investment advice."
MAX_QUESTION = 400
MAX_YEARS = 50                       # engine horizon limit (kept conservative)
HOUSE_PRICE = 850_000                # default price, same as the game's "Buy a home" card
STATUS_TTL = 30.0
STATUS_TIMEOUT = 1.0
TOOLS = ("edit_plan", "house", "strategy", "pillar3a", "savings", "crisis", "drivers", "plan", "ride", "decisions", "review",
         "suggest", "tips", "other")
TOOL_HELP = {
    "edit_plan": "The user states what should HAPPEN in their life plan: add, move or remove a life event (buy a home, "
                 "child, wedding, bachelor, master, apprenticeship, job, job change, part-time, retire, luxury flat, "
                 "monthly costs, gap year) at an age – not a what-if question",
    "house": "Buy a house or flat (optionally at an age and for a price): net worth, range, credit risk, equity",
    "strategy": "Compare the investment styles (cash, cautious, balanced, bold) for this person",
    "pillar3a": "Is pillar 3a (Swiss private pension) worth it for this person?",
    "savings": "How to save more, emergency fund, budget, spending, rent",
    "crisis": "What if I lose my job or the market crashes?",
    "drivers": "Which assumptions matter most for the result",
    "plan": "How am I doing overall: net worth, range, credit risk, goals",
    "ride": "What the film ride / the newly uploaded data showed",
    "decisions": "The decisions played in the game",
    "review": "Looking back at the game: did I do well, how did I do, what could I have done better",
    "suggest": "Suggest another path / other life decisions for the played life (move, drop or add a decision)",
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
    review: dict | None = None                       # twin.review.review(game session): verdict, timeline, ...
    sim: Callable | None = None                      # (events: tuple, years, a) -> engine.Result (e.g. cached)
    tips_fn: Callable | None = None                  # () -> tipps(...) dict
    drivers_fn: Callable | None = None               # () -> (base, rows) as twin.analysis.tornado
    suggest_fn: Callable | None = None               # () -> twin.alt_path.suggestions(...) list (played game only)
    game: object | None = None                       # played game session: plan edits go into its alternative path
    alt: dict | None = None                          # the current alternative path (twin.alt_path state)
    plan_sim: Callable | None = None                 # (events: tuple) -> engine.Result for the plan's chart numbers
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

    def plan_range(self) -> tuple[int, int]:
        """(start age, end age) of the plan the twin edits: the played life (to 85) or this page's plan."""
        if self.game is not None:
            from .review import inputs
            inp = inputs(self.game)
            if inp is not None:
                return int(inp.person.age), int(inp.person.age + inp.years)
        return int(self.person.age), int(self.person.age + self.years)

    def plan_run(self, events):
        return self.plan_sim(tuple(events)) if self.plan_sim is not None else self.run(events)


def _out(tool: str, text: str, args: dict | None = None, numbers: dict | None = None,
         plan_edit: list | None = None) -> dict:
    return {"tool": tool, "text": text, "args": dict(args or {}), "numbers": dict(numbers or {}),
            "plan_edit": plan_edit}


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
        return _out("ride", "No new monthly data has been loaded yet, so there is nothing to compare – I work with "
                            "the status quo you entered in the game.")
    months = (ctx.ride or {}).get("months")
    head = f"The film ride with {months} months of new data showed: " if months else "The film ride showed: "
    return _out("ride", head + " ".join(str(s) for s in st[:4]), {}, {"statements": st[:4]})


def decisions_tool(ctx: ChatCtx) -> dict:
    if not ctx.decisions:
        return _out("decisions", "You have not played any decisions yet. In the game every card shows its effect "
                                 "before you choose it.")
    items = ", ".join(f"{d.get('emoji', '')} {d.get('title', '')} ({d.get('age')})".strip() for d in ctx.decisions[:8])
    return _out("decisions", f"In the game you chose: {items}. Ask me about any of them, e.g. a house at another age.")


def review_tool(ctx: ChatCtx) -> dict:
    """Did I do well? The verdict, the biggest wins and where to do better – all from ``twin.review``."""
    r = ctx.review
    if not r:
        return _out("review", "Play the game to the end first – then I can tell you how you did and what you could "
                              "have done better.")
    v = r["verdict"]
    neg, pos = r.get("negatives") or [], r.get("positives") or []
    text = f"Grade {v['grade']} – {v['title']} {v['text']}"
    if pos:
        text += " What went well: " + "; ".join(f"{p['icon']} {p['title']}" for p in pos[:3]) + "."
    if neg:
        text += " Where you could do better: " + " ".join(
            f"{i}. {n['icon']} {n['title']} – {n['better']}" for i, n in enumerate(neg[:3], 1))
    return _out("review", text, {}, {"grade": v["grade"], "score": v.get("score"),
                                     "better": [n["title"] for n in neg[:3]]})


def suggest_tool(ctx: ChatCtx, n: int = 4) -> dict:
    """Another path for the played life: the twin's best moves and the instructive costly ones (``alt_path``)."""
    if ctx.suggest_fn is None:
        return _out("suggest", "Play the game to the end first – then I can try other paths for your life and show "
                               "you what each one changes at 85.")
    items = [s for s in (ctx.suggest_fn() or []) if isinstance(s, dict)]
    if not items:
        return _out("suggest", "I tried other paths for your life, but none changes your money in a way worth "
                               "showing – your choices are hard to beat.")
    ups = [s for s in items if s.get("impact") == "up"][:max(1, n - 1)]
    downs = [s for s in items if s.get("impact") == "down"][:1]
    pick = ups + downs or items[:n]

    def line(s: dict) -> str:
        arrow = {"up": "▲", "down": "▼"}.get(s.get("impact"), "●")
        d = s.get("delta")
        amount = f" ({chf_delta(float(d))} at 85)" if isinstance(d, (int, float)) else ""
        return f"{arrow} {s.get('emoji', '')} {s.get('title', '')}{amount}".replace("  ", " ")

    text = "I tried other paths for your life with the same random numbers."
    if ups:
        text += " Worth a try: " + "; ".join(line(s) for s in ups) + "."
    if downs:
        text += " Careful: " + "; ".join(line(s) for s in downs) + "."
    if not ups and not downs:
        text += " " + "; ".join(line(s) for s in pick) + "."
    text += " Click “Try it” under TRY ANOTHER PATH to put one on your timeline – the chart shows the new path."
    return _out("suggest", text, {}, {"suggestions": [{"id": s.get("id"), "title": s.get("title"),
                                                       "delta": s.get("delta"), "impact": s.get("impact")}
                                                      for s in pick]})


def edit_plan_tool(ctx: ChatCtx, edits: list[dict] | None, unknown: bool = False) -> dict:
    """Add / move / remove life events on the plan the user sees ("YOUR TIMELINE" after a game, else "YOUR PLAN").

    Computes the new plan with ``twin.alt_path`` (the same functions the page uses to apply it) and the median net
    worth at the end before and after with OUR simulation (same seed: the alternative path's chart after a game, the
    page's plan chart otherwise). Returns the reply plus ``plan_edit`` = the valid edits for the page to apply."""
    from . import alt_path
    from .game import OPTION_BY_KEY
    edits = [e for e in (edits or []) if isinstance(e, dict)]
    if not edits:
        known = ", ".join(OPTION_BY_KEY[k].title.lower() for k in PLAN_KEYS)
        return _out("edit_plan", ("I can't put that on your timeline – " if unknown else "Tell me what should happen, "
                                  "e.g. “I buy a house at 35 for 800k”. ") +
                    f"I know these life events: {known}.", {"edits": []})
    start, end = ctx.plan_range()
    played = ctx.game is not None
    infos, ok_edits = [], []
    if played:
        state0 = alt_path.normalize(ctx.alt)
        state = state0
        for e in edits:
            state, info = alt_path.alt_apply_chat_edit(ctx.game, state, e)
            infos.append(info)
            if info["ok"]:
                ok_edits.append(_resolved(e, info))
    else:
        state0 = list(ctx.events)
        state = list(state0)
        for e in edits:
            state, info = alt_path.plan_apply_edit(ctx.person, state, e, ctx.years, ctx.a)
            infos.append(info)
            if info["ok"]:
                ok_edits.append(_resolved(e, info))
    where = "your new path" if played else "your plan"
    parts = []
    for info in infos:
        if not info["ok"]:
            err = str(info["error"] or "")
            if err.startswith(("There is no", "I don't know", "Play the game")) or info["age"] is None:
                parts.append(err)
            elif info["op"] == "move":
                parts.append(f"I can't move {info['title']} to {info['age']}: {err}")
            else:
                parts.append(f"I can't add {info['title']} at {info['age']}: {err}")
        elif info["op"] == "remove":
            parts.append(f"I took {info['title']} out of {where}")
        elif info["op"] == "move":
            parts.append(f"I moved {info['title']} from {info['from_age']} to {info['age']}")
        elif info["op"] == "replace":
            parts.append(f"I put {info['title']} at {info['age']} instead of the one at {info['from_age']}")
        else:
            parts.append(f"I added {info['title']} at {info['age']}")
    nums: dict = {"start_age": start, "end_age": end}
    text = ". ".join(p.rstrip(".") for p in parts) + "."
    if ok_edits:
        before, after, extra = _plan_ends(ctx, state0, state)
        if before is not None and after is not None:
            d = after - before
            text = (text[:-1] + f" – {where} ends at {chf(after)} at {end} ({chf_delta(d)} vs. before, median, same "
                    f"random numbers).")
            nums.update(before=before, after=after, delta=d)
        text += extra
        movable = [i for i in infos if i["ok"] and i["op"] != "remove"]
        if movable:
            text += f" Drag {'it' if len(movable) == 1 else 'them'} on your timeline to try another age."
        elif played:
            text += " ↺ on the timeline brings it back."
    return _out("edit_plan", text, {"edits": edits}, nums, ok_edits or None)


def _resolved(edit: dict, info: dict) -> dict:
    """The edit as the page re-applies it: absolute age (a relative "5 years later" resolved), no shift."""
    out = {"op": str(edit.get("op") or "add"), "key": info["key"] or edit.get("key"), "age": info["age"],
           "params": dict(edit.get("params") or {})}
    if out["op"] == "remove":
        out["age"] = None
    return out


def _plan_ends(ctx: ChatCtx, state0, state) -> tuple[float | None, float | None, str]:
    """Median net worth at the end before / after the edits (+ a warning when a home purchase often fails)."""
    from . import alt_path
    if ctx.game is not None:
        def end(alt):
            paths = alt_path.simulate_paths(ctx.game, alt) or {}
            m = paths.get("metrics") or {}
            v = m.get("alt_end") if m.get("alt_end") is not None else m.get("played_end")
            return None if v is None else float(v)
        return end(state0), end(state), ""
    b, a = ctx.plan_run(state0).metrics, ctx.plan_run(state).metrics
    extra = ""
    failed = float(a.get("p_house_failed", 0.0))
    if failed > 0.25:
        extra = (f" Careful: the down payment is not there in {pct(failed)} of the simulated lives – a later or "
                 f"cheaper home helps.")
    return float(b["median_net_worth_end"]), float(a["median_net_worth_end"]), extra


def tips_tool(ctx: ChatCtx, n: int = 3) -> dict:
    tips = ctx.tips()["tips"][:n]
    text = " ".join(f"{t['icon']} {t['title']}: {t['text']}" for t in tips) or "No tips – your numbers look solid."
    return _out("tips", text, {}, {"titles": [t["title"] for t in tips]})


def other_tool(ctx: ChatCtx) -> dict:
    return _out("other", "I can only answer with numbers from your simulation. Ask me e.g. “What if I buy a house at "
                         f"{max(ctx.person.age + 5, 30)}?”, “Is pillar 3a worth it?”, “Which investment style?”, "
                         "“What if I lose my job?” or “What matters most?” – or tell me what should happen, e.g. "
                         "“I buy a house at 35 for 800k”, and I put it on your timeline.")


def run_tool(ctx: ChatCtx, tool: str, args: dict | None = None) -> dict:
    args = args or {}
    if tool == "edit_plan":
        return edit_plan_tool(ctx, args.get("edits"), bool(args.get("unknown")))
    if tool == "house":
        return house_tool(ctx, args.get("age"), args.get("price"))
    if tool == "crisis":
        return crisis_tool(ctx, args.get("kind") or "job")
    fn = {"strategy": strategy_tool, "pillar3a": pillar3a_tool, "savings": savings_tool, "drivers": drivers_tool,
          "plan": plan_tool, "ride": ride_tool, "decisions": decisions_tool, "review": review_tool,
          "suggest": suggest_tool, "tips": tips_tool}.get(tool, other_tool)
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


# ---------------------------------------------------------------- plan edits ("I buy a house at 35 for 800k")
# keywords per option, checked in this order (the first hit wins; "*" = word prefix, else whole word +- plural)
PLAN_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("flat", ("luxury flat", "luxury apartment", "luxurious flat", "bigger flat", "nicer flat", "fancy flat",
              "luxuswohnung", "luxus-wohnung", "luxus wohnung", "groessere wohnung", "teurere wohnung")),
    ("child", ("child", "children", "baby", "babies", "kid", "son", "daughter", "kind", "kinder", "nachwuchs",
               "sohn", "tochter")),
    ("buy_house", ("house", "home", "property", "real estate", "condo", "apartment", "flat", "haus", "eigenheim",
                   "immobilie*", "eigentumswohnung", "wohnung", "hauskauf")),
    ("wedding", ("marry", "married", "marriage", "wedding", "heirat*", "hochzeit", "verheirat*")),
    ("retire", ("retire*", "rente", "in pension", "pensionier*", "frueh-rente", "fruehrente")),
    ("gap_year", ("gap year", "gap-year", "gapyear", "sabbatical", "year off", "time off", "auszeit", "zwischenjahr",
                  "sabbat*", "weltreise", "world trip")),
    ("parttime", ("part-time", "part time", "parttime", "80 %", "80%", "teilzeit", "pensum")),
    ("grad_job", ("job after", "degree job", "graduate job", "first job", "job nach", "erste stelle", "erster job",
                  "ersten job")),
    ("master", ("master", "masters", "msc", "masterstudium")),
    ("lehre", ("apprentice*", "lehre", "ausbildung", "berufslehre")),
    ("bachelor", ("bachelor", "university", "uni", "study", "studies", "studying", "degree", "studium", "studier*")),
    ("switch", ("switch job*", "change job*", "job change", "job switch", "new job", "switch my job", "change my job",
                "switch jobs", "jobwechsel", "job wechseln", "stelle wechseln", "neue stelle", "neuen job",
                "wechsle*", "wechsel*")),
    ("job_start", ("entry job", "entry-level", "entry level", "start working", "get a job", "start a job", "job",
                   "einstiegsjob", "arbeiten", "stelle")),
    ("costs", ("monthly cost*", "costs", "cost", "expenses", "spend*", "ausgaben", "kosten", "budget")),
)
_REMOVE = ("remove", "delete", "drop", "cancel", "undo", "take out", "take away", "get rid", "without", "no more",
           "don't want", "do not want", "dont want", "never", "skip", "scrap", "entfern*", "loesch*", "streich*",
           "ohne", "kein", "keine", "keinen", "nicht mehr", "raus", "weg")
_MOVE = ("move", "shift", "postpone", "delay", "push", "bring forward", "reschedule", "later", "earlier", "sooner",
         "instead", "verschieb*", "spaeter", "frueher", "statt", "anstatt", "stattdessen")
# (no bare pronouns: "I like my job" is no edit – with an age, "I ... at 35", the age makes it one)
_ADD = ("add", "put", "insert", "plan", "schedule", "include", "i'll", "let me", "make",
        "do", "buy", "have", "get", "start", "switch", "change", "take", "go", "retire", "marry", "study", "rent",
        "spend", "cut", "work", "become", "fueg*", "hinzu*", "plane", "trag*", "kauf*", "mach*",
        "will", "moechte", "gehe", "nehme", "bekomme", "heirate", "studiere", "wechsle", "arbeite", "spare", "reduzier*")
_NOT_PLAN = ("lose", "lost", "losing", "fired", "laid off", "unemploy*", "verlier*", "verlor*", "arbeitslos*",
             "kuendig*", "crash*", "recession", "rezession", "krise", "pillar", "3a", "saeule")   # other tools
_STRONG = ("add", "put", "insert", "schedule", "remove", "delete", "take out", "move", "shift", "postpone",
           "fueg*", "hinzu*", "trag*", "entfern*", "loesch*", "streich*", "verschieb*")
_QUESTION = ("what", "how", "is", "are", "should", "can", "could", "would", "will it", "does", "do i", "do you",
             "was", "wie", "ist", "lohnt", "soll", "kann", "koennte", "wuerde", "wenn", "lohnen", "which", "welche",
             "why", "warum", "tell me", "show me", "explain")
_LESS = ("less", "cut", "reduce", "lower", "save", "fewer", "weniger", "spar*", "reduzier*", "senk*", "minus")
_MORE = ("more", "extra", "increase", "raise", "higher", "mehr", "erhoeh*", "plus")


def _word(t: str, w: str) -> bool:
    """``w`` as a whole word in ``t`` (plural endings allowed); ``w*`` = any word starting with ``w``."""
    if w.endswith("*"):
        return re.search(r"(?<![a-z0-9])" + re.escape(w[:-1]), t) is not None
    plural = r"(?:s|es|n|en|e)?" if len(w) >= 4 else ""
    return re.search(r"(?<![a-z0-9])" + re.escape(w) + plural + r"(?![a-z0-9])", t) is not None


def _any(t: str, words) -> bool:
    return any(_word(t, w) for w in words)


def plan_key(text: str) -> str | None:
    """The game option a sentence talks about (English or German keywords), None if none."""
    t = _norm(text)
    for key, words in PLAN_WORDS:
        if _any(t, words):
            return key
    return None


def is_question(text: str) -> bool:
    t = _norm(text).strip()
    return t.endswith("?") or any(re.match(re.escape(w) + r"(?![a-z])", t) for w in _QUESTION)


_AGE_TO = re.compile(r"(?<![a-z])(?:to|auf|until|bis|nach)\s+(?:age\s+|the age of\s+|alter\s+)?(\d{2})\b"
                     r"(?!\s*(?:k\b|'|’|,\d|\.\d|000|m\b|mio|million|tsd|thousand|%|chf|fr\b|franken|per\b|a month|pro))")
_SHIFT = re.compile(r"(\d{1,2})\s*(?:years?|yrs?|jahre?n?)\s*(later|earlier|sooner|spaeter|frueher|nach hinten|"
                    r"nach vorne)")


def _plan_age(text: str, now_age: int, op: str) -> tuple[int | None, int | None, tuple[int, int] | None]:
    """(absolute age, relative shift in years, span of the age number in the normalised text)."""
    t = _norm(text)
    m = _SHIFT.search(t)
    if op == "move" and m:
        n = int(m.group(1))
        return None, (-n if m.group(2) in ("earlier", "sooner", "frueher", "nach vorne") else n), m.span()
    if op == "move":
        m = _AGE_TO.search(t)
        if m and 16 <= int(m.group(1)) <= 95:
            return int(m.group(1)), None, m.span(1)
    m = re.search(r"\b(?:at|age|aged|with|mit|alter|when i(?:'m| am)|by|turn|turning|als|ab|from|von|in)\s*"
                  r"(?:the age of|age|von|alter)?\s*(\d{2})\b"
                  r"(?!\s*(?:k\b|'|’|,\d|\.\d|000|m\b|mio|million|tsd|thousand|%|chf|fr\b|franken|years?|jahre?n?))", t)
    if m and 16 <= int(m.group(1)) <= 95:
        return int(m.group(1)), None, m.span(1)
    m = re.search(r"\bin\s+(\d{1,2})\s*(?:years?|yrs?|y\b|jahren?|j\b)", t)
    if m:
        return now_age + int(m.group(1)), None, m.span()
    age = parse_age(text, now_age)
    return age, None, None


def _amounts(text: str, skip: tuple[int, int] | None) -> list[float]:
    t = _norm(text)
    # "800 000" / "1 200 000" (space as thousands separator) -> "800'000" (same length: the age span stays valid)
    t = re.sub(r"(?<![\d'.,])\d{1,3}(?: \d{3})*? ?\d{0,3} 000(?![\d'.,]|\s*k\b)",
               lambda m: m.group(0).replace(" ", "'"), t)
    out = []
    for m in _NUM.finditer(t):
        if skip and m.start(1) < skip[1] and m.end(1) > skip[0]:
            continue
        raw, suf = m.group(1), (m.group(2) or "").strip(".")
        v = float(re.sub(r"['’,]", "", raw)) if re.search(r"['’,]\d{3}", raw) else float(raw.replace(",", "."))
        v *= {"k": 1e3, "tsd": 1e3, "thousand": 1e3, "'000": 1e3, "m": 1e6, "mio": 1e6, "mn": 1e6,
              "million": 1e6, "millionen": 1e6}.get(suf, 1.0)
        out.append(v)
    return out


def _plan_params(key: str, text: str, skip) -> dict:
    t = _norm(text)
    nums = [v for v in _amounts(text, skip)]
    if key == "buy_house":
        v = next((x for x in nums if 50_000 <= x <= 20_000_000), None)
        return {"price": v} if v else {}
    if key == "child":
        v = next((x for x in nums if 100 <= x <= 10_000), None)
        return {"cost": v} if v else {}
    if key == "costs":
        v = next((x for x in nums if 10 <= x <= 20_000), None)
        if v is None:
            return {}
        sign = -1.0 if _any(t, _LESS) or "-" in t or "−" in t else 1.0 if _any(t, _MORE) or "+" in t else -1.0
        return {"delta": sign * v}
    return {}


def _split_plan(text: str) -> list[str]:
    """One part per life event: "add a child at 30 and buy a house at 35" -> two parts (a part without an event of
    its own stays with the one before)."""
    parts = re.split(r"\s*(?:;|,?\s+and then\s+|,?\s+then\s+|,?\s+and\s+|,?\s+und\s+|,?\s+dann\s+|\.\s+)\s*", text)
    out: list[str] = []
    for p in parts:
        if not p.strip():
            continue
        if out and plan_key(p) is None:
            out[-1] += " and " + p
        else:
            out.append(p)
    return out


def parse_plan(text: str, now_age: int) -> list[dict] | None:
    """Plan edits stated in ``text`` (English or German) -> ``[{"op", "key", "age", "params", "shift"?}]``;
    None when the text is not a plan edit (a question, or no life event and no edit verb). An edit verb without a
    known event gives ``[]`` (the tool then says which events it knows)."""
    t = _norm(text)
    if _any(t, _NOT_PLAN):
        return None
    key = plan_key(text)
    strong = _any(t, _STRONG)
    if key is None:
        return [] if strong and not is_question(text) else None
    if is_question(text) and not strong:
        return None
    # a statement without a verb but with an event and an age ("Haus mit 35 für 800k", "child at 30 costing 1500")
    # is the user saying what should happen, too – what-ifs are questions and were handled above
    if not (strong or _any(t, _REMOVE) or _any(t, _MOVE) or _any(t, _ADD)
            or _plan_age(text, now_age, "add")[0] is not None):
        return None
    edits = []
    for part in _split_plan(text):
        k = plan_key(part)
        if k is None:
            continue
        pt = _norm(part)
        op = "remove" if _any(pt, _REMOVE) else "move" if _any(pt, _MOVE) else "add"
        if k == "costs" and op == "remove" and _any(pt, ("less", "weniger")):
            op = "add"                                     # "spend 300 less" is a cost change, not a removal
        age, shift, span = _plan_age(part, now_age, op)
        e = {"op": op, "key": k, "age": age if op != "remove" else None, "params": _plan_params(k, part, span)}
        if shift is not None:
            e["shift"] = shift
        edits.append(e)
    return edits or None


# ---------------------------------------------------------------- routing
def route_offline(ctx: ChatCtx, question: str) -> tuple[str, dict]:
    """Deterministic keyword router (English + German) -> (tool, args)."""
    t = _norm(question)
    edits = parse_plan(question, ctx.plan_range()[0])
    if edits is not None:                       # the user says what should happen: put it on the plan
        return "edit_plan", {"edits": edits, "unknown": not edits}
    # retrospective phrases only ("how much could I have at 65" / "wie viel habe ich mit 65" are NOT a review)
    if _has(t, "did i do", "how did i", "did well", "done well", "done better", "have done", "could i have done",
            "should i have", "my game", "my life review", "life review", "review", "verdict", "grade", "rate me",
            "mistake", "habe ich gut", "habe ich richtig", "habe ich falsch", "gut gemacht", "gut gespielt",
            "besser machen", "besser gemacht", "fehler"):
        return "review", {}
    if (ctx.suggest_fn is not None or ctx.review) and _has(
            t, "suggest", "another path", "other path", "different path", "new path", "alternative", "other way",
            "different life", "other life", "other decision", "what else", "try something", "move my", "vorschlag",
            "anderen weg", "anderer weg", "alternativ", "andere entscheidung"):
        return "suggest", {}
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


LLM_SCHEMA = {"type": "object",
              "properties": {"tool": {"type": "string", "enum": list(TOOLS)},
                             "age": {"type": "integer"}, "price": {"type": "integer"},
                             "op": {"type": "string", "enum": list(PLAN_OPS) + ["none"]},
                             "key": {"type": "string", "enum": list(PLAN_KEYS) + ["none"]},
                             "amount": {"type": "integer"}},
              "required": ["tool", "age", "price", "op", "key", "amount"], "additionalProperties": False}


def llm_plan_edit(ctx: ChatCtx, question: str, reply: dict) -> list[dict]:
    """The edit the model parsed (``op``, ``key``, ``age``, ``price`` / ``amount``) – the numbers written in the
    question beat the model's (offline parser first)."""
    edits = parse_plan(question, ctx.plan_range()[0])
    if edits:
        return edits
    key, op = reply.get("key"), reply.get("op")
    if key not in PLAN_KEYS:
        return []
    op = op if op in PLAN_OPS else "add"
    try:
        age, price, amount = int(reply.get("age") or 0), float(reply.get("price") or 0), float(reply.get("amount") or 0)
    except (TypeError, ValueError):
        age, price, amount = 0, 0.0, 0.0
    params = {}
    if key == "buy_house" and 50_000 <= (price or amount) <= 20_000_000:
        params["price"] = price or amount
    elif key == "child" and 100 <= (amount or price) <= 10_000:
        params["cost"] = amount or price
    elif key == "costs" and amount:
        params["delta"] = amount
    return [{"op": op, "key": key, "age": age if (16 <= age <= 95 and op != "remove") else None, "params": params}]


def route_llm(ctx: ChatCtx, question: str) -> tuple[str, dict]:
    """The model picks one tool + its arguments (0 / "none" = not mentioned) via a JSON-schema constrained answer.
    For ``edit_plan`` it also parses the edit (op, option key, age, price / amount); our model computes the rest."""
    reply = request_chat([
        {"role": "system", "content": "You route messages of a personal finance simulator. Pick the one tool that "
                                      "answers the message. Use edit_plan when the user states what should happen in "
                                      "their life plan (add, move or remove a life event); then fill op and key. Fill "
                                      "age (years), price (CHF, a home) and amount (CHF per month: child costs, change "
                                      "of monthly costs, negative = less) only if the message mentions them, else 0 "
                                      "or \"none\". Answer JSON only."},
        {"role": "user", "content": json.dumps({"message": question, "person_age": ctx.person.age,
                                                "tools": TOOL_HELP, "life_events": list(PLAN_KEYS)},
                                               ensure_ascii=False) + " /no_think"},
    ], LLM_SCHEMA, max_tokens=80)
    tool = reply.get("tool") if isinstance(reply, dict) else None
    if tool not in TOOLS:
        raise ValueError("unknown tool")
    if tool != "edit_plan" and parse_plan(question, ctx.plan_range()[0]):
        tool = "edit_plan"                                # the user clearly said what should happen: don't lose it
    args: dict = {}
    if tool == "edit_plan":
        if is_question(question) and parse_plan(question, ctx.plan_range()[0]) is None:
            return route_offline(ctx, question)           # a what-if question is not an edit
        edits = llm_plan_edit(ctx, question, reply)
        args = {"edits": edits, "unknown": not edits}
    elif tool == "house":
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

    Returns {'text', 'tool', 'args', 'numbers', 'mode': 'llm'|'offline', 'plan_edit'}; the text ends with the
    disclaimer. ``plan_edit`` is None, or for ``edit_plan`` the list of valid edits ``[{op, key, age, params}]`` the
    page applies to its plan (``twin.alt_path.alt_apply_chat_edit`` after a game, ``plan_apply_edit`` otherwise)."""
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
    return {**out, "text": f"{text} {DISCLAIMER}", "mode": mode, "plan_edit": out.get("plan_edit")}


def review_greeting(ctx: ChatCtx) -> dict:
    """First message after a played game: the verdict and the 2 biggest improvements (from ``twin.review``)."""
    who = ctx.name or ctx.person.name
    r = ctx.review
    v, neg = r["verdict"], (r.get("negatives") or [])[:2]
    lines = [f"Hi {who}! I'm your financial twin and I watched your whole life. **Grade {v['grade']} – {v['title']}** "
             f"{v['text']}"]
    if neg:
        lines.append("Where you could have done better:")
        lines += [f"{i}. {n['icon']} **{n['title']}** – {n['text']} Better: {n['better']}" for i, n in enumerate(neg, 1)]
    if ctx.suggest_fn is not None:
        lines.append("Want to see a different life? Drag a choice on your timeline, add one, tell me what should "
                     "happen (“I buy a house at 40 for 800k”) or let me suggest another path below – the chart at the "
                     "bottom shows what it changes.")
    lines.append(f"Ask me anything, e.g. “What could I have done better?”, “Suggest another path” or “What if I buy "
                 f"a house at {max(ctx.person.age + 5, 30)}?” {DISCLAIMER}")
    return {"text": "\n\n".join(lines), "bubble": f"Grade {v['grade']} – {v['title']}", "tool": "review",
            "mode": "offline", "numbers": {"grade": v["grade"], "better": [n["title"] for n in neg]}}


def greeting(ctx: ChatCtx, n: int = 3) -> dict:
    """Proactive first message: 2–3 tips from ``tipps()`` (+ the film ride, if any). Also a short bubble text.
    After a played game (``ctx.review``): the verdict and the 2 biggest improvements instead."""
    if ctx.review:
        return review_greeting(ctx)
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
    lines.append("Tell me what should happen in your life – e.g. “I buy a house at 35 for 800k” or “add a child at "
                 "30” – and I put it on YOUR PLAN, where you can drag it.")
    lines.append(f"Ask me anything, e.g. “What if I buy a house at {max(ctx.person.age + 5, 30)}?” {DISCLAIMER}")
    bubble = f"Hi {who}! " + (" · ".join(f"{t['icon']} {t['title']}" for t in tips) if tips
                              else "Your numbers look solid.")
    return {"text": "\n\n".join(lines), "bubble": bubble, "tool": "tips", "mode": "offline",
            "numbers": {"titles": [t["title"] for t in tips]}}


def plan_example(ctx: ChatCtx) -> str | None:
    """A plan edit that fits the plan, for the suggestion pills ("Add a child at 30")."""
    start, end = ctx.plan_range()
    age = max(start + 3, 30) if ctx.game is not None else min(max(start + 3, 22), end - 1)
    return f"Add a child at {age}" if 22 <= age <= 50 and start <= age < end else None


def suggestions(ctx: ChatCtx) -> list[str]:
    ex = plan_example(ctx)
    if ctx.review:
        return ["What could I have done better?", "Suggest another path", "Did I do well?"] + ([ex] if ex else []) + [
                f"What if I buy a house at {max(ctx.person.age + 5, 30)}?", "Which investment style suits me?",
                "What if I lose my job?"]
    return [f"What if I buy a house at {max(ctx.person.age + 5, 30)}?"] + ([ex] if ex else []) + [
            "Is pillar 3a worth it?", "Which investment style suits me?", "What if I lose my job?", "What matters most?"]


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
