"""Game layer "Life path": one station per year, the player CHOOSES (no dice), very gamified.

* Decisions are grouped by category; locked options show why (e.g. "Missing equity").
* Every card shows the twin's preview (median net worth at the end, range, credit risk).
* XP, levels, happiness meter, achievements and quests make the trade-offs tangible.
* The played life is path 0 of the Monte Carlo run; ``fixed_until`` makes all other paths share
  its past, so the fan always shows the futures still possible from where the player stands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .calibration import Calibration, Person
from .config import Assumptions, EMPLOYED, SELF_EMPLOYED, STUDENT, UNEMPLOYED
from .engine import Result, simulate
from .scenarios import (Event, ExpenseChange, HouseBuy, Job, JobChange, OneOff, SelfEmployment, StrategyChange,
                        Study)

YEARS = 15
N_PATHS = 400


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
    joy: int = 0
    xp: int = 50
    once: bool = True


CATS = ["🎓 Education", "💼 Career", "🏡 Housing", "👨‍👩‍👧 Family", "🏝️ Time off", "💰 Money"]

# labels of finished degrees (plan.labels) -> degree key
DEGREES = {"Bachelor's degree": "bachelor", "Master's degree": "master", "Apprenticeship diploma": "lehre"}


def _studying(c: Ctx) -> str | None:
    return "You are still studying" if c.snap.state == STUDENT and ({"bachelor", "master", "lehre"} & c.done) else None


def _house(price: int) -> Callable[[Ctx], str | None]:
    def f(c: Ctx) -> str | None:
        if c.snap.state not in (EMPLOYED, SELF_EMPLOYED):
            return "Needs a steady income first"
        need = 0.22 * price
        return None if c.snap.liquid >= need else f"Missing equity: CHF {need - c.snap.liquid:,.0f}".replace(",", "'")
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
    Option("bachelor", CATS[0], "🎓", "Bachelor", "3 years of university, CHF 1'500 fees/year. Then a first job at CHF 5'200.",
           lambda t, s: [Study(t, 36, 1500, None, 5200, 800, "Bachelor", "Bachelor's degree")],
           lambda c: "Already done" if {"bachelor", "lehre"} & c.done else None, joy=1, xp=100),
    Option("master", CATS[0], "🎓", "Master", "2 years, CHF 1'500/year. Then a first job at CHF 6'300.",
           lambda t, s: [Study(t, 24, 1500, None, 6300, 1000, "Master", "Master's degree")],
           lambda c: None if "bachelor" in c.finished and "master" not in c.done else
           ("Already done" if "master" in c.done else "Finish a bachelor first"), joy=1, xp=120),
    Option("lehre", CATS[0], "🛠️", "Apprenticeship", "3 years, apprentice pay CHF 900. Then a skilled job at CHF 5'000.",
           lambda t, s: [Study(t, 36, 0, 900, 5000, 600, "Apprenticeship", "Apprenticeship diploma")],
           lambda c: "Already done" if {"bachelor", "lehre"} & c.done else ("Only up to age 25" if c.age > 25 else None), joy=1, xp=100),
    # ---- Career
    Option("job_start", CATS[1], "🛒", "Entry-level job", "Earn money now: CHF 4'300 net, own flat +CHF 800/month.",
           lambda t, s: [Job(t, 4300, 800, "Job: Entry-level")], _job_lock(None), joy=0, xp=60),
    Option("job_office", CATS[1], "🏢", "Office job", "CHF 5'800 net. Needs a bachelor or apprenticeship.",
           lambda t, s: [Job(t, 5800, 900, "Job: Office")], _job_lock("abschluss"), joy=0, xp=80),
    Option("job_tech", CATS[1], "💻", "Tech job", "CHF 7'400 net. Needs a master.",
           lambda t, s: [Job(t, 7400, 1000, "Job: Tech")], _job_lock("master"), joy=1, xp=100),
    Option("switch", CATS[1], "🚀", "Job change", "+15 % pay, 1 month without income in between.",
           lambda t, s: [JobChange(t, 0.15, 1, "Job change")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", joy=0, xp=70, once=False),
    Option("course", CATS[1], "📚", "Further training", "CHF 12'000 now, +20 % pay in 18 months.",
           lambda t, s: [OneOff(t, 12_000, "Further training"), JobChange(t + 18, 0.20, 0, "Promotion")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", joy=-1, xp=90),
    Option("startup", CATS[1], "💡", "Found a startup", "CHF 20'000 seed capital, income ~CHF 6'000, very volatile.",
           lambda t, s: [SelfEmployment(t, 6000, 20_000, "Startup")],
           lambda c: None if c.snap.state == EMPLOYED else "Get work experience first", joy=2, xp=120),
    Option("parttime", CATS[1], "⏳", "Part-time 80 %", "20 % less pay, more free time.",
           lambda t, s: [JobChange(t, -0.20, 0, "Part-time")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", joy=2, xp=40),
    # ---- Housing
    Option("flat", CATS[2], "🛋️", "Nicer flat", "+CHF 600 rent per month.",
           lambda t, s: [ExpenseChange(t, 600, "New flat")],
           lambda c: None if c.snap.state in (EMPLOYED, SELF_EMPLOYED) else "Needs a steady income first", joy=2, xp=40),
    Option("buy_flat", CATS[2], "🏢", "Own flat", "CHF 550'000 – 20 % equity, 2 % mortgage.",
           lambda t, s: [HouseBuy(t, 550_000, "Buy: Flat")], _house(550_000), joy=3, xp=200),
    Option("buy_house", CATS[2], "🏡", "House with garden", "CHF 850'000 – 20 % equity, 2 % mortgage.",
           lambda t, s: [HouseBuy(t, 850_000, "Buy: House")], _house(850_000), joy=4, xp=250),
    Option("car", CATS[2], "🚙", "Own car", "CHF 25'000 and +CHF 350/month upkeep.",
           lambda t, s: [OneOff(t, 25_000, "Car purchase"), ExpenseChange(t, 350, "Car costs")],
           lambda c: None if c.snap.state in (EMPLOYED, SELF_EMPLOYED) else "Needs a steady income first", joy=2, xp=40),
    # ---- Family
    Option("wedding", CATS[3], "💍", "Wedding", "A party for CHF 20'000.",
           lambda t, s: [OneOff(t, 20_000, "Wedding")], lambda c: None if c.age >= 22 else "From age 22", joy=4, xp=150),
    Option("child", CATS[3], "👶", "Have a child", "CHF 3'000 for the birth, then +CHF 1'100/month (after child allowance).",
           lambda t, s: [OneOff(t, 3000, "Child"), ExpenseChange(t, 1100, "Child costs")],
           lambda c: "From age 22" if c.age < 22 else ("At most 2 children in the game" if c.kids >= 2 else None),
           joy=5, xp=200, once=False),
    # ---- Time off
    Option("travel", CATS[4], "🌍", "World trip", "Travel for 3 months for CHF 7'000.",
           lambda t, s: [OneOff(t, 7000, "World trip")], joy=4, xp=80),
    Option("sabbatical3", CATS[4], "🏝️", "3-month break", "3 months without pay, then the same job.",
           lambda t, s: [JobChange(t, 0.0, 3, "Time off")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", joy=3, xp=60, once=False),
    Option("sabbatical12", CATS[4], "🏖️", "Sabbatical year", "12 months without pay, then the same job.",
           lambda t, s: [JobChange(t, 0.0, 12, "Time off")],
           lambda c: None if c.snap.state == EMPLOYED else "Only with a job", joy=6, xp=100),
    # ---- Money
    Option("frugal", CATS[5], "🥦", "Live frugally", "CHF 300 less spending per month.",
           lambda t, s: [ExpenseChange(t, -300, "Frugal")], joy=-1, xp=40, once=False),
    Option("risk_up", CATS[5], "📈", "More risk", "Portfolio 100 % in stocks.",
           lambda t, s: [StrategyChange(t, 1.0, "100 % stocks")],
           lambda c: None if c.snap.portfolio > 1000 else "Invest first (portfolio > CHF 1'000)", joy=0, xp=40, once=False),
    Option("risk_down", CATS[5], "🛡️", "Less risk", "Portfolio 25 % in stocks.",
           lambda t, s: [StrategyChange(t, 0.25, "25 % stocks")],
           lambda c: None if c.snap.portfolio > 1000 else "Invest first (portfolio > CHF 1'000)", joy=0, xp=40, once=False),
]
STAY = Option("stay", "", "🛣️", "Drive on", "Change nothing.", lambda t, s: [], joy=0, xp=10, once=False)
OPTION_BY_KEY = {o.key: o for o in OPTIONS + [STAY]}


def available(ctx: Ctx) -> list[tuple[Option, str | None]]:
    """All options with their lock reason (None = selectable)."""
    out = []
    for o in OPTIONS:
        reason = "Already done" if (o.once and o.key in ctx.done) else o.lock(ctx)
        out.append((o, reason))
    return out


# ---------------------------------------------------------------- simulation helpers
def play(person: Person, events: list[Event], a: Assumptions, calib: Calibration, seed: int, now_month: int) -> Result:
    return simulate(person, events, YEARS, a, N_PATHS, seed, calib=calib, fixed_until=now_month)


def preview(person: Person, events: list[Event], opt: Option, snap: Snapshot, a: Assumptions,
            calib: Calibration, seed: int) -> dict:
    res = play(person, events + opt.make(snap.month, snap), a, calib, seed, snap.month)
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
        if label in DEGREES:
            typ = "graduation"
        elif label.startswith("Job") or label in ("First job", "Promotion"):
            typ = "job"
        elif label == "Startup":
            typ = "startup"
        elif label in ("Time off", "World trip"):
            typ = "vacation"
        elif label.startswith("Buy"):
            typ = "house"
        elif label == "Child":
            typ = "child"
        elif label == "Wedding":
            out.append({"id": f"{turn}-{len(out)}", "type": "fate", "emoji": "💍", "label": "Wedding!"})
            continue
        else:
            continue
        out.append({"id": f"{turn}-{len(out)}", "type": typ, "label": label})
        if typ == "graduation":   # a finished degree goes straight into the first job
            out.append({"id": f"{turn}-{len(out)}", "type": "job", "label": "First job!"})
    return out


def finished_degrees(plan, month: int) -> frozenset[str]:
    return frozenset(DEGREES[l] for t, l in plan.labels if l in DEGREES and t <= month)


# ---------------------------------------------------------------- gamification
LEVELS = ["Rookie", "Go-getter", "Pro", "Money ace", "Legend"]


def level(xp: int) -> tuple[int, str, float]:
    lv = min(xp // 400, len(LEVELS) - 1)
    return lv + 1, LEVELS[lv], (xp % 400) / 400 if lv < len(LEVELS) - 1 else 1.0


@dataclass(frozen=True)
class Achievement:
    key: str
    emoji: str
    title: str
    test: Callable[[Ctx, dict], bool]


ACHIEVEMENTS = [
    Achievement("grad", "🎓", "Graduated", lambda c, f: bool(c.finished)),
    Achievement("job", "💼", "First job", lambda c, f: c.snap.state == EMPLOYED or f.get("ever_job", False)),
    Achievement("buffer", "🐷", "Rainy-day fund: 3 months of spending", lambda c, f: c.snap.cash >= 3 * f["expenses"]),
    Achievement("k10", "💯", "First CHF 10'000", lambda c, f: c.snap.net_worth >= 10_000),
    Achievement("k50", "🥈", "50k-Club", lambda c, f: c.snap.net_worth >= 50_000),
    Achievement("k100", "🥇", "100k-Club", lambda c, f: c.snap.net_worth >= 100_000),
    Achievement("debtfree", "🧾", "Debt-free", lambda c, f: f.get("had_credit", False) and f["credit"] <= 0),
    Achievement("investor", "📈", "Investor: portfolio ≥ CHF 20'000", lambda c, f: c.snap.portfolio >= 20_000),
    Achievement("home", "🏡", "A home of your own", lambda c, f: bool({"buy_flat", "buy_house"} & c.done)),
    Achievement("family", "👶", "Started a family", lambda c, f: c.kids > 0),
    Achievement("balance", "🏝️", "Work-Life-Balance", lambda c, f: bool({"travel", "sabbatical3", "sabbatical12", "parttime"} & c.done)),
    Achievement("happy", "😄", "Lucky one: joy ≥ 85", lambda c, f: f["joy"] >= 85),
]


def joy_label(j: int) -> str:
    return "😄" if j >= 80 else "🙂" if j >= 60 else "😐" if j >= 40 else "😟"
