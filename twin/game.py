"""Game layer "Lebensweg": one station per year, the player CHOOSES (no dice), very gamified.

* Decisions are grouped by category; locked options show why (e.g. "Eigenkapital fehlt").
* Every card shows the twin's preview (median net worth at the end, range, credit risk).
* Goals (quests) make the trade-offs tangible (no XP, levels, achievements or joy meter).
* Life span: from the player's age to retirement at 65; one station = one year (see ``life_span``).
* Investing is not part of the game: the game simulates the balanced default; strategies are compared on the
  analysis page (with tips).
* The played life is path 0 of the Monte Carlo run; ``fixed_until`` makes all other paths share
  its past, so the fan always shows the futures still possible from where the player stands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .calibration import Calibration, Person
from .config import Assumptions, EMPLOYED, SELF_EMPLOYED, STRATEGY_PRESETS, STUDENT, UNEMPLOYED, Strategy
from .engine import Result, simulate
from .scenarios import (Event, ExpenseChange, HouseBuy, Job, JobChange, OneOff, SelfEmployment, StrategyChange,
                        Study)

RETIRE_AGE = 65
YEARS = 15          # default horizon when no age is known (tests, helpers)
N_PATHS = 400


def life_span(age: int) -> tuple[int, int, int]:
    """(step years per station, number of stations K, total years) from ``age`` to retirement at 65.
    One station = one year (the film ride with real data runs month by month instead)."""
    total = max(5, min(50, RETIRE_AGE - int(age)))
    return 1, total, total


# ---------------------------------------------------------------- snapshot & context
@dataclass(frozen=True)
class Snapshot:
    month: int
    state: int
    income: float
    cash: float
    portfolio: float
    debt: float
    net_worth: float
    liquid: float


def snapshot(res: Result, month: int) -> Snapshot:
    p = res.path0
    m = min(month, res.plan.months - 1)
    return Snapshot(month, int(p["state"][month]), float(res.plan.income[m]), float(p["cash"][month]),
                    float(p["portfolio"][month]), float(p["debt"][month]), float(p["net_worth"][month]),
                    float(p["liquid"][month]))


@dataclass(frozen=True)
class Ctx:
    snap: Snapshot
    done: frozenset[str]
    age: int
    kids: int
    finished: frozenset[str]     # completed degrees: "bachelor", "master", "lehre"
    style: str | None = None     # chosen investment style (option key), None = not decided yet
    turn: int = 0                # station index (0 = start)


# ---------------------------------------------------------------- decision cards
@dataclass(frozen=True)
class Option:
    key: str
    cat: str
    emoji: str
    title: str
    text: str
    make: Callable[[int, Snapshot], list[Event]]
    lock: Callable[[Ctx], str | None] = lambda c: None   # None = available, else reason
    once: bool = True


CATS = ["🎓 Education", "💼 Career", "🏡 Housing", "👨‍👩‍👧 Family", "🏝️ Time off"]   # money/investing: analysis page


def _studying(c: Ctx) -> str | None:
    return "You are studying right now" if c.snap.state == STUDENT and ({"bachelor", "master", "lehre"} & c.done) else None


def _house(price: int) -> Callable[[Ctx], str | None]:
    def f(c: Ctx) -> str | None:
        if c.snap.state not in (EMPLOYED, SELF_EMPLOYED):
            return "Needs a steady income first"
        need = 0.22 * price
        return None if c.snap.liquid >= need else f"Down payment missing: CHF {need - c.snap.liquid:,.0f}".replace(",", "'")
    return f


def _job_lock(req: str | None) -> Callable[[Ctx], str | None]:
    def f(c: Ctx) -> str | None:
        if c.snap.state == EMPLOYED:
            return "You already have a job"
        if _studying(c):
            return _studying(c)
        if req and req not in c.finished and not (req == "abschluss" and c.finished):
            return {"abschluss": "Needs a bachelor or apprenticeship", "master": "Needs a master"}[req]
        return None
    return f


OPTIONS: list[Option] = [
    # ---- Education
    Option("bachelor", CATS[0], "🎓", "Bachelor", "3 years of uni, CHF 1'500 fees/year. Then a first job at CHF 5'200.",
           lambda t, s: [Study(t, 36, 1500, None, 5200, 800, "Bachelor", "Bachelor's degree")],
           lambda c: "Already done" if {"bachelor", "lehre"} & c.done else None),
    Option("master", CATS[0], "🎓", "Master", "2 years, CHF 1'500/year. Then a first job at CHF 6'300.",
           lambda t, s: [Study(t, 24, 1500, None, 6300, 1000, "Master", "Master's degree")],
           lambda c: None if "bachelor" in c.finished and "master" not in c.done else
           ("Already done" if "master" in c.done else "Finish a bachelor first")),
    Option("lehre", CATS[0], "🛠️", "Apprenticeship", "3 years, apprentice pay CHF 900. Then a skilled job at CHF 5'000.",
           lambda t, s: [Study(t, 36, 0, 900, 5000, 600, "Apprenticeship", "Apprenticeship done")],
           lambda c: "Already done" if {"bachelor", "lehre"} & c.done else ("Only up to age 25" if c.age > 25 else None)),
    # ---- Career
    Option("job_start", CATS[1], "🛒", "Entry job", "Earn money now: CHF 4'300 net, own flat +CHF 800/month.",
           lambda t, s: [Job(t, 4300, 800, "Job: entry level")], _job_lock(None)),
    Option("switch", CATS[1], "🚀", "Job change", "+15 % salary, 1 month without income in between.",
           lambda t, s: [JobChange(t, 0.15, 1, "Job switch")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", once=False),
    Option("parttime", CATS[1], "⏳", "Part-time 80 %", "20 % less salary, more free time.",
           lambda t, s: [JobChange(t, -0.20, 0, "Part-time")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job"),
    # ---- Housing: buy a property (mortgage from UBS) or rent a more luxurious flat
    Option("buy_house", CATS[2], "🏡", "Buy a home", "CHF 850'000 property – 20 % down payment, UBS mortgage at 2 %.",
           lambda t, s: [HouseBuy(t, 850_000, "Purchase: house")], _house(850_000)),
    Option("flat", CATS[2], "🛋️", "Rent a luxury flat", "Bigger, nicer, central: +CHF 900 rent per month.",
           lambda t, s: [ExpenseChange(t, 900, "Luxury flat")],
           lambda c: None if c.snap.state in (EMPLOYED, SELF_EMPLOYED) else "Needs a steady income first"),
    # ---- Family
    Option("wedding", CATS[3], "💍", "Get married", "Celebration for CHF 20'000. Your partner joins you on the road.",
           lambda t, s: [OneOff(t, 20_000, "Wedding")], lambda c: None if c.age >= 22 else "From age 22"),
    Option("child", CATS[3], "👶", "Have a child", "CHF 3'000 birth, then +CHF 1'100/month (after child allowance).",
           lambda t, s: [OneOff(t, 3000, "Child"), ExpenseChange(t, 1100, "Child costs")],
           lambda c: "From age 22" if c.age < 22 else ("At most 2 children in the game" if c.kids >= 2 else None), once=False),
    # ---- Time off
    Option("travel", CATS[4], "🌍", "World trip", "Travel for 3 months for CHF 7'000.",
           lambda t, s: [OneOff(t, 7000, "World trip")]),
    Option("sabbatical3", CATS[4], "🏝️", "3-month break", "3 months without pay, then the same job.",
           lambda t, s: [JobChange(t, 0.0, 3, "Time off")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", once=False),
    Option("sabbatical12", CATS[4], "🏖️", "Sabbatical year", "12 months without pay, then the same job.",
           lambda t, s: [JobChange(t, 0.0, 12, "Time off")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job"),
]

# ---- Investing is NOT part of the game (it is adjusted on the analysis page). The game simulates the default
# balanced strategy: 3 months of expenses as emergency fund, the rest invested 60 % stocks / 40 % bonds.
GAME_STRATEGY = STRATEGY_PRESETS["ausgewogen"]
STAY = Option("stay", "", "🛣️", "Drive on", "Change nothing.", lambda t, s: [], once=False)
OPTION_BY_KEY = {o.key: o for o in OPTIONS + [STAY]}


def available(ctx: Ctx) -> list[tuple[Option, str | None]]:
    """All options with their lock reason (None = selectable)."""
    out = []
    for o in OPTIONS:
        reason = "Already done" if (o.once and o.key in ctx.done) else o.lock(ctx)
        out.append((o, reason))
    return out


# ---------------------------------------------------------------- simulation helpers
def play(person: Person, events: list[Event], a: Assumptions, calib: Calibration, seed: int, now_month: int,
         years: int = YEARS) -> Result:
    return simulate(person, events, years, a, N_PATHS, seed, calib=calib, fixed_until=now_month)


def preview(person: Person, events: list[Event], opt: Option, snap: Snapshot, a: Assumptions,
            calib: Calibration, seed: int, years: int = YEARS) -> dict:
    res = play(person, events + opt.make(snap.month, snap), a, calib, seed, snap.month, years)
    return {"median": res.metrics["median_net_worth_end"], "p5": res.metrics["p5_net_worth_end"],
            "p95": res.metrics["p95_net_worth_end"], "credit": res.metrics["p_credit_future"]}


# ---------------------------------------------------------------- 3D animations from the plan
def animations(plan, m0: int, m1: int, turn: int, played: set | None = None) -> list[dict]:
    """Events from the month of the decision up to and including the arrival month.
    ``played`` remembers (month, label) pairs so an event on a station boundary animates only once."""
    out = []
    played = played if played is not None else set()
    for t, label in plan.labels:
        if not (m0 <= t <= m1) or (t, label) in played:
            continue
        played.add((t, label))
        if label in DEGREE_LABELS:
            typ = "graduation"
        elif label.startswith("Job:") or label == "Promotion":
            typ = "job"
        elif label == "Startup":
            typ = "startup"
        elif label in ("Time off", "World trip"):
            typ = "vacation"
        elif label.startswith("Purchase"):
            typ = "house"
        elif label == "Child":
            typ = "child"
        elif label == "Wedding":
            typ = "wedding"
        else:
            continue
        out.append({"id": f"{turn}-{len(out)}", "type": typ, "label": label})
        if typ == "graduation":   # a finished degree goes straight into the first job
            out.append({"id": f"{turn}-{len(out)}", "type": "job", "label": "First job!"})
    return out


DEGREE_LABELS = {"Bachelor's degree": "bachelor", "Master's degree": "master", "Apprenticeship done": "lehre"}


def finished_degrees(plan, month: int) -> frozenset[str]:
    return frozenset(DEGREE_LABELS[l] for t, l in plan.labels if l in DEGREE_LABELS and t <= month)
