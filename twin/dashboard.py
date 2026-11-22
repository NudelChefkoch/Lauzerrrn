"""Juli's dashboard, rebuilt on OUR SDE (see CONTRACT.md, "Extension: Juli's analysis inside the game").

``build`` returns the CONTRACT ``dashboard`` block. Every series is a Monte Carlo run of ``twin.engine.simulate``
with the SAME seed and the SAME ``fixed_until`` (common random numbers), so "plan" vs "no_saving" vs
"no_events" vs "alt" is a counterfactual comparison in the same simulated world:

* plan       – the played decisions
* no_saving  – the same decisions, but nothing invested (``Strategy.invest_rate = 0``)
* no_events  – no player decisions at all
* alt        – an edited plan (decision groups moved) or the plan plus one more option

Play phase: ``fixed_until`` = current month (the realised past is shared by all paths).
End phase:  ``fixed_until`` = 0 (the full distribution of lives that were possible).

Results are cached per (events tuple, assumptions, seed, fixed_until), so reruns are instant.
All numbers in the output are plain Python ints/floats/None.
"""
from __future__ import annotations

import math
from dataclasses import replace
from functools import lru_cache
from typing import Callable, Iterable

from . import game
from .calibration import calibrate
from .config import Assumptions
from .game import YEARS

T_MAX = 12 * YEARS - 1          # last month a decision can start in


# ---------------------------------------------------------------- formatting helpers (CHF with ')
def chf(x: float) -> str:
    """CHF 12'345 / −CHF 1'200 (typographic minus)."""
    v = float(x)
    s = f"CHF {abs(v):,.0f}".replace(",", "'")
    return ("−" + s) if v <= -0.5 else s


def chf_delta(x: float) -> str:
    """+CHF 12'345 / −CHF 1'200 / CHF 0."""
    v = float(x)
    return ("+" + chf(v)) if v >= 0.5 else chf(v)


def age_of(start_age: int, month: int) -> int | float:
    """Age at ``month`` (int when the month is a whole year, else one decimal)."""
    a = start_age + month / 12
    return int(a) if float(a).is_integer() else round(a, 1)


def _f(x) -> float | None:
    if x is None:
        return None
    v = float(x)
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- simulation (cached)
@lru_cache(maxsize=512)
def _sim(pid: str, events: tuple, a: Assumptions, seed: int, fixed_until: int):
    c = calibrate()
    return game.play(c.persons[pid], list(events), a, c, seed, fixed_until)


Sim = Callable[[tuple, Assumptions, int], object]     # (events, assumptions, fixed_until) -> engine.Result


def default_sim(pid: str, seed: int) -> Sim:
    return lambda events, a, fixed: _sim(pid, tuple(events), a, seed, int(fixed))


def no_saving_assumptions(a: Assumptions) -> Assumptions:
    return a.with_(strategy=replace(a.strategy, invest_rate=0.0))


# ---------------------------------------------------------------- decision groups
def shift_events(events: Iterable, delta: int) -> list:
    """Shift all events of one decision group by the same ``delta`` months.

    The shift is limited so the group's first event stays inside [0, T_MAX] (relative offsets kept);
    a later event that would leave the game is clamped to the last month."""
    events = list(events)
    if not events:
        return []
    lo = min(ev.start for ev in events)
    delta = int(min(max(delta, -lo), T_MAX - lo))
    return [replace(ev, start=int(min(max(ev.start + delta, 0), T_MAX))) for ev in events]


def move_month(group: dict, target_age: float, start_age: int) -> int:
    """New start month for a group dragged to ``target_age`` (whole months, clamped to the game)."""
    return int(min(max(round((float(target_age) - start_age) * 12), 0), T_MAX))


def apply_moves(groups: list[dict], moves: dict, start_age: int) -> tuple[list, list[str]]:
    """Events of the played plan with the given groups moved to new ages.

    ``moves`` maps group id -> target age. Returns (events, labels) where labels describe each real move."""
    events, labels = [], []
    for g in groups:
        target = moves.get(g["id"])
        if target is None or not g.get("movable", True):
            events += list(g["events"])
            continue
        new = move_month(g, target, start_age)
        delta = new - g["start_month"]
        events += shift_events(g["events"], delta)
        if delta:
            labels.append(move_label(g["title"], delta))
    return events, labels


def move_label(title: str, delta_months: int) -> str:
    years = abs(delta_months) / 12
    if float(years).is_integer():
        n = int(years)
        span = f"{n} year" if n == 1 else f"{n} years"
    else:
        span = f"{abs(delta_months)} months"
    return f"{title} {span} {'later' if delta_months > 0 else 'earlier'}"


# ---------------------------------------------------------------- series
def _yearly(arr) -> list[float | None]:
    return [_f(arr[12 * i]) for i in range(YEARS + 1)]


def series_full(res) -> dict:
    pct = res.percentiles["net_worth"]
    return {"p5": _yearly(pct[0]), "p50": _yearly(pct[2]), "p95": _yearly(pct[4]),
            "life": _yearly(res.path0["net_worth"])}


def series_short(res) -> dict:
    return {"p50": _yearly(res.percentiles["net_worth"][2]), "life": _yearly(res.path0["net_worth"])}


# ---------------------------------------------------------------- the block
def build(*, pid: str, start_age: int, events: Iterable, groups: list[dict], a: Assumptions, seed: int,
          phase: str, turn: int, alt_events: Iterable | None = None, alt_label: str | None = None,
          moves: dict | None = None, sim: Sim | None = None) -> dict:
    """CONTRACT ``dashboard`` block.

    ``phase`` 'play' -> fixed_until = 12*turn, now_index = turn; 'end' -> fixed_until = 0, now_index = YEARS."""
    sim = sim or default_sim(pid, seed)
    events = tuple(events)
    end = phase == "end"
    now_month = 12 * YEARS if end else 12 * int(turn)
    fixed = 0 if end else now_month
    now_index = YEARS if end else int(turn)

    plan = sim(events, a, fixed)
    no_saving = sim(events, no_saving_assumptions(a), fixed)
    no_events = sim((), a, fixed)
    alt = sim(tuple(alt_events), a, fixed) if alt_events is not None else None

    ages = [start_age + i for i in range(YEARS + 1)]
    end_age = ages[-1]
    m = plan.metrics
    net_now = float(plan.path0["net_worth"][min(now_month, 12 * YEARS)])
    saving_effect = m["median_net_worth_end"] - no_saving.metrics["median_net_worth_end"]
    events_effect = m["median_net_worth_end"] - no_events.metrics["median_net_worth_end"]
    infl = float(a.macro.inflation)
    real_factor = (1 + infl) ** -YEARS

    summary = (f"With your plan, your net worth at {end_age} is {chf(m['median_net_worth_end'])} "
               f"(range {chf(m['p5_net_worth_end'])} to {chf(m['p95_net_worth_end'])}).")
    if m["p_credit_future"] >= 0.05:
        summary += f" In {m['p_credit_future'] * 100:.0f} % of lives you still need a loan."
    alt_block = None
    if alt is not None:
        alt_block = series_full(alt)
        d = alt.metrics["median_net_worth_end"] - m["median_net_worth_end"]
        d_life = float(alt.path0["net_worth"][-1] - plan.path0["net_worth"][-1])
        summary += (f" Variant \"{alt_label or 'Alternative'}\": {chf(alt.metrics['median_net_worth_end'])} "
                    f"({chf_delta(d)} in the median, {chf_delta(d_life)} in your life).")

    moves = moves or {}
    timeline = []
    for g in groups:
        target = moves.get(g["id"])
        timeline.append({"id": g["id"], "emoji": g["emoji"], "title": g["title"],
                         "age": age_of(start_age, g["start_month"]), "cat": g["cat"],
                         "movable": bool(g.get("movable", True)),
                         "alt_age": None if target is None else age_of(start_age, move_month(g, target, start_age))})

    metrics = {"net_now": _f(net_now), "current_age": start_age + now_month // 12,
               "end_age": end_age, "median_end": _f(m["median_net_worth_end"]),
               "p5_end": _f(m["p5_net_worth_end"]), "p95_end": _f(m["p95_net_worth_end"]),
               "median_end_real": _f(m["median_net_worth_end"] * real_factor),
               "saving_effect": _f(saving_effect), "events_effect": _f(events_effect),
               "credit_risk": _f(m["p_credit_future"])}
    return {"ages": ages, "now_index": now_index, "inflation": infl,
            "series": {"plan": series_full(plan), "no_saving": series_short(no_saving),
                       "no_events": series_short(no_events), "alt": alt_block},
            "alt_label": alt_label if alt is not None else None,
            "summary": summary, "timeline": timeline, "metrics": metrics}
