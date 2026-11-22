"""Life review after the game: timeline of the played choices, a verdict, positives and negatives.

``review(session_or_inputs)`` reads a played :class:`twin.session.GameSession` (or a dict with the same pieces) and
returns::

    {"verdict": {"grade": "A".."E", "level": "great|good|mixed|risky", "score": 0..100, "title": str, "text": str},
     "timeline": [{"age", "emoji", "title", "cat", "key", "impact": "up"|"down"|"flat", "delta", "effect", "vs",
                   "note"}],
     "positives": [{"icon", "title", "text"}],
     "negatives": [{"icon", "title", "text", "better"}],
     "facts": {...}}            # the numbers behind the texts (net worth, credit months, savings rate, ...)

Every number comes from our simulation (``twin.game.play`` = ``engine.simulate`` with the game's paths, seed and
forced retirement at 70):

* the arrow / ``delta`` of a decision = what its card showed in the game (``history[].delta`` / ``base``: median at the
  end with the choice minus "drive on" at that moment, same seed; ``game.impact`` = the cards' rule), so the timeline
  never contradicts the cards (after a degree "drive on" means taking the degree job, see ``game.assume_degree_jobs``);
* ``effect`` = median net worth at the end of life WITH all played decisions minus the median WITHOUT that one
  decision (same seed = common random numbers, ``fixed_until=0``: the whole life is re-simulated) – also the
  fallback ``delta`` when the card delta was not recorded (``vs`` = "not doing it" instead of "driving on");
* life-wide checks on the played life (path 0, the life the player saw): months on credit, the biggest loan, the
  cash buffer, the savings rate, the retirement age, gap years and children, house purchases that would often fail.

Without a played game (no person, or no decision and the game not finished) ``review`` returns None.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import game
from .calibration import Person, calibrate
from .config import EMPLOYED, SELF_EMPLOYED, Assumptions
from .scenarios import ExpenseChange

CAT_KEYS = {c: k for c, k in zip(game.CATS, ["education", "career", "housing", "family", "timeoff"])}
BUFFER_MONTHS = 3            # "buffer OK" = liquid money covers 3 months of expenses (as in the game's status tile)
FLAT_SHARE, FLAT_ABS = 0.01, 20_000   # "about the same": |delta| < 1 % of the median and < CHF 20'000 (as the cards)

# what to do better when a decision cost money (keyed by the game's option key)
BETTER = {
    "bachelor": "A degree pays off through the job after it – take the degree job right after graduating.",
    "master": "A master pays off only with the master job – start it right after graduating, skip the gap.",
    "lehre": "Take the skilled job right after the apprenticeship.",
    "grad_job": "Stay in the job longer before changing course.",
    "job_start": "Use the entry job to build a buffer, then study or switch with savings behind you.",
    "switch": "Switch only when the raise clearly beats the month without pay.",
    "parttime": "Go part-time later, once your savings work for you – or cut monthly costs at the same time.",
    "retire": "Every extra year of work adds a salary and shortens the years on about 60 % of it.",
    "buy_house": "Pick a cheaper home or buy later with a bigger down payment.",
    "flat": "Rent the luxury flat only while your buffer covers 3 months of expenses.",
    "costs": "Small monthly amounts add up over decades – try cutting CHF 300 a month instead.",
    "wedding": "A smaller party: money you keep early grows for decades.",
    "child": "Kids are a life choice, not a mistake – build a 3-month buffer before the birth.",
    "gap_year": "Take time off once your buffer covers the whole year without pay.",
}
GRADES = ((85, "A", "great", "Money master!"), (70, "B", "good", "Well played!"),
          (55, "C", "mixed", "Solid, with gaps"), (40, "D", "risky", "A bumpy ride"),
          (-1, "E", "risky", "Life on credit"))


def money(x: float) -> str:
    """CHF amount for the texts: millions with two decimals, else rounded to CHF 1'000 (below 10'000: to 100)."""
    v = float(x)
    sign = "−" if v < 0 else ""
    v = abs(v)
    if v >= 1e6:
        return f"{sign}CHF {v / 1e6:,.2f} M".replace(",", "'")
    step = 1000 if v >= 10_000 else 100
    return f"{sign}CHF {round(v / step) * step:,.0f}".replace(",", "'")


def money_delta(x: float) -> str:
    return ("+" if x >= 0 else "") + money(x)


# ---------------------------------------------------------------- inputs
@dataclass(frozen=True)
class Inputs:
    person: Person
    events: tuple
    history: tuple            # ((turn, key, emoji, title, cat, card_delta, card_base), ...) of the decisions
    #                           (no "stay"); card_delta / card_base = what the card showed (None if not recorded)
    a: Assumptions
    seed: int
    years: int
    step: int
    name: str
    finished: bool


def _get(src, name, default=None):
    if isinstance(src, dict):
        return src.get(name, default)
    return getattr(src, name, default)


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def inputs(src) -> Inputs | None:
    """Pieces of a played game from a GameSession (or a dict with person, events, history, seed, assumptions /
    a, total / years, step, avatar / name, phase). None if there is nothing to review."""
    if src is None:
        return None
    person = _get(src, "person")
    if person is None:
        person = _get(src, "_person")
    if not isinstance(person, Person):
        return None
    hist = []
    for h in _get(src, "history") or []:
        if not isinstance(h, dict) or h.get("key") in (None, game.STAY.key) or h.get("key") not in game.OPTION_BY_KEY:
            continue
        hist.append((int(h.get("turn", 0)), str(h["key"]), str(h.get("emoji", "")), str(h.get("title", "")),
                     str(h.get("cat", "")), _num(h.get("delta")), _num(h.get("base"))))
    finished = _get(src, "phase") == "end"
    if not hist and not finished:
        return None
    years = int(_get(src, "total") or _get(src, "years") or game.life_span(person.age)[2])
    avatar = _get(src, "avatar") or {}
    name = str(_get(src, "name") or (avatar.get("name") if isinstance(avatar, dict) else None) or person.name)
    a = _get(src, "assumptions") or _get(src, "a") or Assumptions(strategy=game.GAME_STRATEGY)
    return Inputs(person, tuple(_get(src, "events") or ()), tuple(hist), a, int(_get(src, "seed") or 0), years,
                  int(_get(src, "step") or 1), name, finished)


# ---------------------------------------------------------------- simulation (cached, shared across sessions)
@lru_cache(maxsize=256)
def _sim(person: Person, events: tuple, a: Assumptions, seed: int, years: int):
    """The whole life re-simulated from month 0 (``fixed_until=0``), only metrics + path 0 (fast)."""
    return game.play(person, list(events), a, calibrate(), seed, 0, years, pct_series=())


def _groups(inp: Inputs) -> list[tuple[int, ...]]:
    """Indices of the events each decision added: a decision at turn i adds events starting at its month."""
    used: set[int] = set()
    out = []
    for turn, *_ in inp.history:
        month = 12 * min(turn * inp.step, inp.years)
        idx = tuple(i for i, e in enumerate(inp.events) if i not in used and int(getattr(e, "start", -1)) == month)
        used.update(idx)
        out.append(idx)
    return out


def effects(inp: Inputs) -> tuple[float, list[float]]:
    """(median net worth at the end with all decisions, [effect of each decision])."""
    full = _sim(inp.person, inp.events, inp.a, inp.seed, inp.years).metrics["median_net_worth_end"]
    out = []
    for idx in _groups(inp):
        if not idx:
            out.append(0.0)
            continue
        without = tuple(e for i, e in enumerate(inp.events) if i not in idx)
        out.append(float(full - _sim(inp.person, without, inp.a, inp.seed, inp.years).metrics["median_net_worth_end"]))
    return float(full), out


def impact(delta: float, base: float) -> str:
    """The cards' rule (``game.impact``): "up", "down" or "flat"."""
    return game.impact(delta, base) or "flat"


# ---------------------------------------------------------------- the review
def review(src) -> dict | None:
    """Timeline, verdict, positives and negatives of a played game (see the module docstring); None without one."""
    inp = inputs(src)
    if inp is None:
        return None
    return copy.deepcopy(_review(inp))


@lru_cache(maxsize=64)
def _review(inp: Inputs) -> dict:
    p = inp.person
    full_res = _sim(p, inp.events, inp.a, inp.seed, inp.years)
    none_res = _sim(p, (), inp.a, inp.seed, inp.years)
    full, deltas = effects(inp)
    base_none = float(none_res.metrics["median_net_worth_end"])
    end_age = p.age + inp.years

    # ---- timeline (the played choices, in order)
    # The arrow and amount of a choice are the ones its card showed in the game (median at the end with the choice
    # minus "drive on" at that moment, same seed – game.preview), so the timeline never contradicts the cards
    # (e.g. after a degree "drive on" means taking the degree job). ``effect`` = the re-simulated whole-life effect
    # (all played choices with vs without this one); it is the fallback when the card delta was not recorded.
    timeline = []
    effects_ = deltas
    deltas = []
    for (turn, key, emoji, title, cat, cd, cb), eff in zip(inp.history, effects_):
        if cd is not None:
            d, imp = cd, game.impact(cd, cb)
        else:
            d, imp = eff, impact(eff, full)
        deltas.append(d)
        note = {"up": f"{money_delta(d)} by {end_age}", "down": f"{money_delta(d)} by {end_age}",
                "flat": "About the same for your money"}[imp]
        timeline.append({"age": p.age + min(turn * inp.step, inp.years), "emoji": emoji, "title": title,
                         "cat": CAT_KEYS.get(cat, cat), "key": key, "impact": imp, "delta": d, "effect": eff,
                         "vs": "driving on" if cd is not None else "not doing it", "note": note})

    # ---- the played life (path 0)
    p0, plan = full_res.path0, full_res.plan
    T = plan.months
    credit = p0["cash"] + p0["portfolio"] - p0["liquid"]
    months_credit = int(np.sum(credit[1:] > 1))
    max_credit = max(float(np.max(credit)), 0.0)
    final = float(p0["net_worth"][-1])
    infl = (1 + inp.a.macro.inflation) ** (np.arange(T) / 12)
    expenses = (p.expenses + plan.extra_expenses) * infl                     # nominal monthly expenses
    yearly = np.arange(0, T, 12)
    buffer_ok = p0["liquid"][yearly] >= BUFFER_MONTHS * np.maximum(expenses[yearly], 1.0)
    buffer_share = float(np.mean(buffer_ok)) if len(yearly) else 1.0
    working = np.isin(plan.state, (EMPLOYED, SELF_EMPLOYED)) & (plan.income > 0)
    inc = float(np.sum(plan.income[working]))
    savings_rate = float((inc - np.sum((p.expenses + plan.extra_expenses)[working])) / inc) if inc > 0 else None
    retire = next(((t, l) for t, l in sorted(plan.labels) if l in ("Retired", "Retirement")), None)
    retire_age = p.age + retire[0] // 12 if retire else None
    credit_after_retire = int(np.sum(credit[retire[0] + 1:] > 1)) if retire else 0
    kids = sum(1 for e in inp.events if isinstance(e, ExpenseChange) and e.label == "Child costs")
    gap_years = sum(1 for h in inp.history if h[1] == "gap_year")
    p_house_failed = float(full_res.metrics.get("p_house_failed", 0.0))
    p_house_unaff = float(full_res.metrics.get("p_house_unaffordable", 0.0))
    total = full - base_none
    name = inp.name

    positives: list[tuple[float, dict]] = []      # (weight, item): the biggest first
    negatives: list[tuple[float, dict]] = []

    # ---- decisions
    for item, d in zip(timeline, deltas):
        if item["impact"] == "up":
            positives.append((d, {"icon": item["emoji"], "title": f"{item['title']} paid off",
                                  "text": f"At {item['age']}: {money_delta(d)} at {end_age} compared with "
                                          f"{item['vs']}."}))
        elif item["impact"] == "down":
            negatives.append((-d, {"icon": item["emoji"], "title": f"{item['title']} cost you",
                                   "text": f"At {item['age']}: {money_delta(d)} at {end_age} compared with "
                                           f"{item['vs']}.",
                                   "better": BETTER.get(item["key"], "Check the arrow on the card before you choose.")}))

    # ---- life-wide checks
    if months_credit == 0:
        positives.append((abs(full) * 0.5 + 1, {"icon": "🛡️", "title": "Never on credit",
                                               "text": f"Your money lasted all {inp.years} years without a loan."}))
    else:
        yrs = months_credit / 12
        negatives.append((max_credit * 3 + months_credit * 1000, {
            "icon": "💳", "title": f"{months_credit} months on credit",
            "text": f"About {yrs:.0f} year{'s' if round(yrs) != 1 else ''} with a loan at 8 % interest, biggest loan "
                    f"{money(max_credit)}." if yrs >= 1 else
                    f"Short stretch with a loan at 8 % interest, biggest loan {money(max_credit)}.",
            "better": "Keep 3 months of expenses as a buffer and skip big costs while it is thin."}))
    if buffer_share >= 0.8 and months_credit <= 12:      # no "healthy buffer" next to years on credit
        positives.append((abs(full) * 0.2 + 1, {"icon": "🐷", "title": "Healthy buffer",
                                               "text": f"In {buffer_share:.0%} of the years your cash covered "
                                                       f"3 months of expenses."}))
    elif buffer_share < 0.5:
        negatives.append(((1 - buffer_share) * 100_000, {
            "icon": "🐷", "title": "Thin buffer",
            "text": f"Only in {buffer_share:.0%} of the years did your cash cover 3 months of expenses.",
            "better": "Put money aside first: 3 months of expenses before a house, a child or time off."}))
    if savings_rate is not None:
        if savings_rate >= 0.15 and months_credit <= 12:
            positives.append((abs(full) * 0.3 + 1, {"icon": "💰", "title": "Strong saver",
                                                   "text": f"Over your working years you kept {savings_rate:.0%} "
                                                           f"of your income (raises included)."}))
        elif savings_rate < 0.05:
            negatives.append((150_000, {
                "icon": "💸", "title": "Little left each month",
                "text": f"While working you kept only {savings_rate:.0%} of your income"
                        + (" – costs ate more than you earned." if savings_rate < 0 else "."),
                "better": "Cut monthly costs (🧾 card) or switch jobs for a raise – aim for 10–20 % saved."}))
    if retire_age is not None:
        if credit_after_retire > 0:
            negatives.append((max_credit + 50_000, {
                "icon": "🪑", "title": f"Retired at {retire_age}, money ran short",
                "text": f"After retirement you spent {credit_after_retire} months on credit.",
                "better": "Work a few years longer or lower your costs before you retire."}))
        elif retire_age <= 63:
            positives.append((abs(full) * 0.1 + 1, {"icon": "🪑", "title": f"Early retirement at {retire_age}",
                                                   "text": "And the money still lasted to the end."}))
    if gap_years >= 2:
        cost = sum(d for it, d in zip(timeline, deltas) if it["key"] == "gap_year")
        negatives.append((max(-cost, 0) + 1, {
            "icon": "🎒", "title": f"{gap_years} gap years",
            "text": f"Together {money_delta(cost)} at {end_age}.",
            "better": BETTER["gap_year"]}))
    if kids and months_credit == 0:
        positives.append((abs(full) * 0.15 + 1, {"icon": "👶", "title": "Kids and no debt",
                                                "text": f"{kids} child{'ren' if kids > 1 else ''} and still never "
                                                        f"on credit."}))
    if p_house_failed > 0.2:
        negatives.append((p_house_failed * 200_000, {
            "icon": "🏠", "title": "The home was a close call",
            "text": f"In {p_house_failed:.0%} of the simulated lives the down payment would not have been enough.",
            "better": BETTER["buy_house"]}))
    if p_house_unaff > 0.2:
        negatives.append((p_house_unaff * 200_000, {
            "icon": "🏦", "title": "Mortgage too heavy",
            "text": f"In {p_house_unaff:.0%} of the lives the costs break the ⅓-of-income rule.",
            "better": "Choose a price your income carries: costs at most ⅓ of your gross income."}))
    if final >= 0:
        positives.append((abs(final) * 0.05 + 1, {"icon": "🏁", "title": f"{money(final)} at {end_age}",
                                                 "text": "What your played life ends with (cash, investments, home "
                                                         "minus debts)."}))
    else:
        negatives.append((-final + 1, {"icon": "🏁", "title": f"Debts at {end_age}",
                                       "text": f"Your played life ends at {money(final)}.",
                                       "better": "Spend less than you earn for longer and keep a buffer."}))
    if not negatives:                 # always one hint: the weakest choice or the market's mood in this life
        median = full
        if timeline:
            i = int(np.argmin(deltas))
            it = timeline[i]
            negatives.append((1, {"icon": it["emoji"], "title": f"Weakest move: {it['title']}",
                                  "text": f"At {it['age']}: {money_delta(deltas[i])} at {end_age} – the smallest "
                                          f"gain of your choices.",
                                  "better": BETTER.get(it["key"], "Check the arrow on the card before you choose.")}))
        else:
            negatives.append((1, {"icon": "🛣️", "title": "You only drove on",
                                  "text": f"Typical outcome at {end_age}: {money(median)}.",
                                  "better": "Try a degree or a job change – the green arrows show what pays."}))

    positives.sort(key=lambda x: -x[0])
    negatives.sort(key=lambda x: -x[0])

    # ---- verdict (0..100 points)
    pts_credit = 30 if months_credit == 0 else 20 if months_credit <= 12 else 10 if months_credit <= 60 else 0
    scale = abs(base_none) + 100_000
    # choices that cost a large share of what was possible weigh more (−50 % of the no-choice median = 0 points),
    # so 'Money master' never comes with 'your choices cost CHF 3.5 M'
    pts_choices = 30 if total >= 0 else max(0.0, 30 * (1 + 2 * total / scale))
    pts_end = 20 if final > 0 else 0
    pts_buffer = 20 * buffer_share
    score = int(round(pts_credit + pts_choices + pts_end + pts_buffer))
    grade, level, title = next((g, lv, t) for lim, g, lv, t in GRADES if score >= lim)
    parts = []
    if inp.history:
        parts.append(f"Your {len(inp.history)} choice{'s' if len(inp.history) != 1 else ''} "
                     f"{'added' if total >= 0 else 'cost'} {money(abs(total))} at {end_age} compared with just "
                     f"driving on.")
    else:
        parts.append(f"You drove through life without a single decision: {money(full)} at {end_age} (median).")
    parts.append("You were never on credit." if months_credit == 0 else
                 f"You spent {months_credit} months on credit (biggest loan {money(max_credit)}).")
    verdict = {"grade": grade, "level": level, "score": score, "title": title, "text": " ".join(parts)}

    facts = {"name": name, "start_age": p.age, "end_age": end_age, "final_net_worth": final,
             "median_net_worth_end": full, "median_without_choices": base_none, "choices_effect": total,
             "months_on_credit": months_credit, "max_credit": max_credit, "buffer_share": buffer_share,
             "savings_rate": savings_rate, "retire_age": retire_age, "kids": kids, "gap_years": gap_years,
             "p_house_failed": p_house_failed, "p_house_unaffordable": p_house_unaff,
             "decisions": len(inp.history), "finished": inp.finished}
    return {"verdict": verdict, "timeline": timeline, "positives": [x for _, x in positives][:5],
            "negatives": [x for _, x in negatives][:5], "facts": facts}
