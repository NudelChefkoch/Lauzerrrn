"""Game layer "Lebensweg": one station per year, the player CHOOSES (no dice), very gamified.

* Decisions are grouped by category; locked options show why (e.g. "Down payment missing").
* Every card carries the twin's preview (median net worth at the end, range, credit risk); the game shows only its
  direction (``impact``: green ▲ / red ▼ / grey ●), the numbers are used at the end (facts, analysis).
* Some cards are adjustable (``Option.params``: house price, child costs, monthly costs); lock, preview and text
  follow the chosen values.
* Goals (quests) make the trade-offs tangible (no XP, levels, achievements or joy meter).
* Life span: from the player's age to 85 (at most 70 years); one station = one year (see ``life_span``).
  Retirement is a card from 60 ("Retire": about 60 % of the last salary); at 70 it happens anyway.
* A finished degree does NOT start a job: the player is "graduated / looking" (no income, no ALV) and picks
  "Job after your degree" or a gap year.
* Investing is not part of the game: the game simulates the balanced default; strategies are compared on the
  analysis page (with tips).
* The played life is path 0 of the Monte Carlo run; ``fixed_until`` makes all other paths share
  its past, so the fan always shows the futures still possible from where the player stands.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from .calibration import Calibration, Person
from .config import Assumptions, EMPLOYED, RETIRED, SELF_EMPLOYED, STRATEGY_PRESETS, STUDENT, UNEMPLOYED, Strategy
from .engine import MAX_YEARS, Result, simulate
from .scenarios import (Event, ExpenseChange, HouseBuy, Job, JobChange, OneOff, Retirement, SelfEmployment,
                        StrategyChange, Study, Unemployment)

RETIRE_AGE = 65          # statutory AHV age: horizon of the twin's statements after the film ride (daten_update)
RETIRE_FROM = 60         # the "Retire" card unlocks at this age
FORCED_RETIRE_AGE = 70   # retirement happens at the latest here (label "Retirement")
END_AGE = 85             # the game ends here (retirement finale, then the financial facts)
PENSION_RATE = 0.60      # AHV + pension fund, simplified: share of the last salary
CHILD_MONTHS = 216       # child costs end when the child turns 18 and moves out
MIN_EXPENSES = 500       # monthly costs cannot be cut below this (month-0 CHF)
YEARS = 15               # default horizon when no age is known (tests, helpers)
N_PATHS = 400
INFLATION = Assumptions().macro.inflation   # the game runs with the default macro assumptions (house price level)

# first job after a degree: (salary net/month, lifestyle change/month), best degree first
GRAD_JOBS = {"master": (6300, 1000), "bachelor": (5200, 800), "lehre": (5000, 600)}
DEGREE_NAME = {"master": "master", "bachelor": "bachelor", "lehre": "apprenticeship"}


def life_span(age: int) -> tuple[int, int, int]:
    """(step years per station, number of stations K, total years) from ``age`` to 85 (at most 70 years).
    One station = one year (the film ride with real data runs month by month instead)."""
    total = max(1, min(END_AGE - int(age), MAX_YEARS))
    return 1, total, total


def chf(x: float) -> str:
    return f"CHF {x:,.0f}".replace(",", "'")


FLAT_SHARE = 0.01        # a card's effect counts as "about the same" below 1 % of the drive-on median ...
FLAT_MAX = 20_000.0      # ... and below CHF 20'000


def impact(delta: float | None, base: float | None = None) -> str | None:
    """Direction of a decision's effect on the net worth at the end, as the cards show it (no numbers):
    "up" (green ▲), "down" (red ▼) or "flat" (grey ●: |delta| < 1 % of |base| and < CHF 20'000).
    None when there is no preview (locked card)."""
    if delta is None or not math.isfinite(float(delta)):
        return None
    d = float(delta)
    if base is not None and math.isfinite(float(base)) and abs(d) < min(FLAT_SHARE * abs(float(base)), FLAT_MAX):
        return "flat"
    if d > 0:
        return "up"
    return "down" if d < 0 else "flat"


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
    expenses: float = 0.0        # planned monthly expenses at that month (month-0 prices)
    house_equity: float = 0.0    # house value minus mortgage (net worth - house equity = liquid money - credit - loan)


def snapshot(res: Result, month: int) -> Snapshot:
    """Balances at the start of ``month``; state and income are those OF that month (what the player is now:
    e.g. "graduated / looking" right at the station where the degree is finished)."""
    p = res.path0
    m = min(month, res.plan.months - 1)
    return Snapshot(month, int(p["state"][min(month + 1, res.plan.months)]), float(res.plan.income[m]),
                    float(p["cash"][month]),
                    float(p["portfolio"][month]), float(p["debt"][month]), float(p["net_worth"][month]),
                    float(p["liquid"][month]), float(res.person.expenses + res.plan.extra_expenses[m]),
                    float(p["house_equity"][month]))


@dataclass(frozen=True)
class Ctx:
    snap: Snapshot
    done: frozenset[str]
    age: int
    kids: int
    finished: frozenset[str]     # completed degrees: "bachelor", "master", "lehre"
    style: str | None = None     # chosen investment style (option key), None = not decided yet
    turn: int = 0                # station index (0 = start)


# ---------------------------------------------------------------- adjustable values on a card
@dataclass(frozen=True)
class Param:
    label: str
    min: float
    max: float
    step: float
    default: float
    unit: str = "CHF"

    def snap(self, v) -> float | int:
        """Clamp to [min, max] and snap to the step grid (fallback: default)."""
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = float(self.default)
        if not math.isfinite(x):
            x = float(self.default)
        x = min(max(x, self.min), self.max)
        x = min(self.min + math.floor((x - self.min) / self.step + 0.5) * self.step, self.max)   # half up, as ui.js
        return int(round(x)) if float(self.step).is_integer() and float(self.min).is_integer() else float(x)

    def spec(self, value) -> dict:
        return {"label": self.label, "min": self.min, "max": self.max, "step": self.step, "default": self.default,
                "unit": self.unit, "value": value}


# ---------------------------------------------------------------- decision cards
@dataclass(frozen=True)
class Option:
    """A decision card. ``make(t, snap, ctx, values)`` -> events, ``lock(ctx, values)`` -> reason or None,
    ``describe(ctx, values)`` -> card text (default ``text``); ``values`` = chosen param values."""
    key: str
    cat: str
    emoji: str
    title: str
    text: str
    make: Callable[[int, Snapshot, "Ctx | None", dict], list[Event]]
    lock: Callable[[Ctx, dict], str | None] = lambda c, p: None   # None = available, else reason
    once: bool = True
    params: dict = field(default_factory=dict, compare=False, hash=False)   # name -> Param
    describe: Callable[["Ctx | None", dict], str] | None = field(default=None, compare=False, hash=False)

    def values(self, chosen: dict | None = None) -> dict:
        """Param values: chosen (clamped/snapped) else default."""
        chosen = chosen if isinstance(chosen, dict) else {}
        return {n: p.snap(chosen[n]) if n in chosen else p.snap(p.default) for n, p in self.params.items()}

    def events(self, t: int, snap: Snapshot, ctx: "Ctx | None" = None, values: dict | None = None) -> list[Event]:
        return self.make(t, snap, ctx, self.values(values))

    def text_for(self, ctx: "Ctx | None" = None, values: dict | None = None) -> str:
        return self.describe(ctx, self.values(values)) if self.describe else self.text

    def reason(self, ctx: Ctx, values: dict | None = None) -> str | None:
        if self.once and self.key in ctx.done:
            return "Already done"
        return self.lock(ctx, self.values(values))


CATS = ["🎓 Education", "💼 Career", "🏡 Housing", "👨‍👩‍👧 Family", "🏝️ Time off"]   # money/investing: analysis page


def _retired(c: Ctx) -> bool:
    return c.snap.state == RETIRED


def _studying(c: Ctx) -> str | None:
    return "You are studying right now" if c.snap.state == STUDENT and ({"bachelor", "master", "lehre"} & c.done) else None


HOUSE_FAILED = "Down payment not enough this year (prices and markets move)"


def _house_lock(c: Ctx, p: dict) -> str | None:
    if c.snap.state not in (EMPLOYED, SELF_EMPLOYED):
        return "Needs a steady income first"
    # 20 % down payment + 2 % fees on the price at that time: the engine inflates the price (today's CHF on the card)
    # and pays from cash + portfolio after the month's flow – one month of costs as margin, so an unlocked card
    # never ends in a purchase that silently fails in the played life
    level = (1 + INFLATION) ** (c.snap.month / 12)
    need = 0.22 * p["price"] * level + max(c.snap.expenses, 0.0) * level
    return None if c.snap.liquid >= need else f"Down payment missing: {chf(need - c.snap.liquid)}"


def _job_lock(req: str | None) -> Callable[[Ctx, dict], str | None]:
    def f(c: Ctx, p: dict) -> str | None:
        if _retired(c):
            return "You are retired"
        if c.snap.state == EMPLOYED:
            return "You already have a job"
        if _studying(c):
            return _studying(c)
        if req and req not in c.finished and not (req == "abschluss" and c.finished):
            return {"abschluss": "Needs a bachelor or apprenticeship", "master": "Needs a master"}[req]
        return None
    return f


def _edu_lock(base: Callable[[Ctx], str | None]) -> Callable[[Ctx, dict], str | None]:
    return lambda c, p: "You are retired" if _retired(c) else base(c)


def best_degree(finished) -> str | None:
    return next((d for d in GRAD_JOBS if d in finished), None)


def _grad_job_events(t: int, s: Snapshot, c: Ctx | None, p: dict) -> list[Event]:
    sal, exp = GRAD_JOBS[best_degree(c.finished if c else ()) or "bachelor"]
    return [Job(t, sal, exp, "First job")]


def _grad_job_lock(c: Ctx, p: dict) -> str | None:
    if _retired(c):
        return "You are retired"
    if _studying(c):
        return _studying(c)
    if not c.finished:
        return "Finish a degree first"
    if c.snap.state in (EMPLOYED, SELF_EMPLOYED):
        return "You already have a job"
    return None


def _grad_job_text(c: Ctx | None, p: dict) -> str:
    d = best_degree(c.finished) if c else None
    if d is None:
        return "Start with the salary of your degree: bachelor CHF 5'200, master CHF 6'300, apprenticeship CHF 5'000."
    sal, exp = GRAD_JOBS[d]
    return f"Your first job after your {DEGREE_NAME[d]}: {chf(sal)} net, own flat +{chf(exp)}/month."


def _gap_year_events(t: int, s: Snapshot, c: Ctx | None, p: dict) -> list[Event]:
    if s.state == EMPLOYED:                 # same job afterwards
        return [JobChange(t, 0.0, 12, "Gap year")]
    return [Unemployment(t, 12, "Gap year", alv=False)]     # no pay; afterwards as before (e.g. still looking)


def _gap_year_lock(c: Ctx, p: dict) -> str | None:
    if _retired(c):
        return "You are retired"
    return _studying(c)


def _retire_lock(c: Ctx, p: dict) -> str | None:
    if _retired(c):
        return "Already retired"
    return f"From age {RETIRE_FROM}" if c.age < RETIRE_FROM else None


def _costs_lock(c: Ctx, p: dict) -> str | None:
    if p["delta"] == 0:
        return "Pick a change first"
    if c.snap.expenses + p["delta"] < MIN_EXPENSES:
        return f"Costs can't go below {chf(MIN_EXPENSES)}/month"
    return None


def _costs_text(c: Ctx | None, p: dict) -> str:
    d = p["delta"]
    change = f"{'+' if d > 0 else '−' if d < 0 else '±'}{chf(abs(d))} per month from now on"
    if c is not None and c.snap.expenses:
        return f"{change}: CHF {c.snap.expenses:,.0f} → CHF {max(c.snap.expenses + d, 0):,.0f} a month.".replace(",", "'")
    return f"{change}."


OPTIONS: list[Option] = [
    # ---- Education (no automatic job afterwards: "graduated / looking")
    Option("bachelor", CATS[0], "🎓", "Bachelor", "3 years of uni, CHF 1'500 fees/year. Then: first job (CHF 5'200) or a gap year.",
           lambda t, s, c, p: [Study(t, 36, 1500, None, None, 0, "Bachelor", "Bachelor's degree", job_after=False)],
           _edu_lock(lambda c: "Already done" if {"bachelor", "lehre"} & c.done else None)),
    Option("master", CATS[0], "🎓", "Master", "2 years, CHF 1'500/year. Then: first job (CHF 6'300) or a gap year.",
           lambda t, s, c, p: [Study(t, 24, 1500, None, None, 0, "Master", "Master's degree", job_after=False)],
           _edu_lock(lambda c: None if "bachelor" in c.finished and "master" not in c.done else
                     ("Already done" if "master" in c.done else "Finish a bachelor first"))),
    Option("lehre", CATS[0], "🛠️", "Apprenticeship", "3 years, apprentice pay CHF 900. Then: skilled job (CHF 5'000) or a gap year.",
           lambda t, s, c, p: [Study(t, 36, 0, 900, None, 0, "Apprenticeship", "Apprenticeship done", job_after=False)],
           _edu_lock(lambda c: "Already done" if {"bachelor", "lehre"} & c.done else ("Only up to age 25" if c.age > 25 else None))),
    # ---- Career
    Option("grad_job", CATS[1], "💼", "Job after your degree", _grad_job_text(None, {}),
           _grad_job_events, _grad_job_lock, once=False, describe=_grad_job_text),   # again after a master
    Option("job_start", CATS[1], "🛒", "Entry job", "Earn money now: CHF 4'300 net, own flat +CHF 800/month.",
           lambda t, s, c, p: [Job(t, 4300, 800, "Job: entry level")], _job_lock(None)),
    Option("switch", CATS[1], "🚀", "Job change", "+15 % salary, 1 month without income in between.",
           lambda t, s, c, p: [JobChange(t, 0.15, 1, "Job switch")],
           lambda c, p: None if c.snap.state == EMPLOYED else ("You are retired" if _retired(c) else "Only with a job"),
           once=False),
    Option("parttime", CATS[1], "⏳", "Part-time 80 %", "20 % less salary, more free time.",
           lambda t, s, c, p: [JobChange(t, -0.20, 0, "Part-time")],
           lambda c, p: None if c.snap.state == EMPLOYED else ("You are retired" if _retired(c) else "Only with a job")),
    Option("retire", CATS[1], "🪑", "Retire", "AHV + pension fund: about 60 % of your last salary",
           lambda t, s, c, p: [Retirement(t, PENSION_RATE, "Retired")], _retire_lock, once=False),
    # ---- Housing: buy a property (mortgage from UBS), rent a more luxurious flat, adjust the monthly costs
    Option("buy_house", CATS[2], "🏡", "Buy a home", "CHF 850'000 property – 20 % down payment, UBS mortgage at 2 %.",
           lambda t, s, c, p: [HouseBuy(t, p["price"], "Purchase: house")], _house_lock,
           params={"price": Param("Price", 400_000, 2_000_000, 50_000, 850_000)},
           describe=lambda c, p: f"{chf(p['price'])} property – 20 % down payment, UBS mortgage at 2 %."),
    Option("flat", CATS[2], "🛋️", "Rent a luxury flat", "Bigger, nicer, central: +CHF 900 rent per month.",
           lambda t, s, c, p: [ExpenseChange(t, 900, "Luxury flat")],
           lambda c, p: None if c.snap.state in (EMPLOYED, SELF_EMPLOYED) else "Needs a steady income first"),
    Option("costs", CATS[2], "🧾", "Adjust monthly costs", "Spend more or less every month from now on.",
           lambda t, s, c, p: [ExpenseChange(t, p["delta"], "Monthly costs")], _costs_lock, once=False,
           params={"delta": Param("Change per month", -2000, 2000, 100, -300)}, describe=_costs_text),
    # ---- Family
    Option("wedding", CATS[3], "💍", "Get married", "Celebration for CHF 20'000. Your partner joins you on the road.",
           lambda t, s, c, p: [OneOff(t, 20_000, "Wedding")], lambda c, p: None if c.age >= 22 else "From age 22"),
    Option("child", CATS[3], "👶", "Have a child", "CHF 3'000 birth, then +CHF 1'100/month until 18 (after child allowance).",
           lambda t, s, c, p: [OneOff(t, 3000, "Child"),
                               ExpenseChange(t, p["cost"], "Child costs", CHILD_MONTHS, "Child moves out")],
           lambda c, p: "From age 22" if c.age < 22 else ("At most 2 children in the game" if c.kids >= 2 else
                                                            ("Only up to age 50" if c.age > 50 else None)),
           once=False, params={"cost": Param("Cost per month", 300, 3000, 100, 1100)},
           describe=lambda c, p: f"CHF 3'000 birth, then +{chf(p['cost'])}/month until 18 (after child allowance)."),
    # ---- Time off
    Option("gap_year", CATS[4], "🎒", "Gap year", "12 months off without pay",
           _gap_year_events, _gap_year_lock, once=False),
]

# ---- Investing is NOT part of the game (it is adjusted on the analysis page). The game simulates the default
# balanced strategy: 3 months of expenses as emergency fund, the rest invested 60 % stocks / 40 % bonds.
GAME_STRATEGY = STRATEGY_PRESETS["ausgewogen"]
STAY = Option("stay", "", "🛣️", "Drive on", "Change nothing.", lambda t, s, c, p: [], once=False)
OPTION_BY_KEY = {o.key: o for o in OPTIONS + [STAY]}


def available(ctx: Ctx, values: dict | None = None) -> list[tuple[Option, str | None]]:
    """All options with their lock reason (None = selectable). ``values``: {key: {param: value}} chosen so far."""
    values = values or {}
    return [(o, o.reason(ctx, values.get(o.key))) for o in OPTIONS]


# ---------------------------------------------------------------- simulation helpers
def forced_retirement(person: Person, events: list[Event]) -> list[Event]:
    """Retirement at 70 unless the player retired earlier."""
    if any(isinstance(e, Retirement) for e in events):
        return []
    return [Retirement(max(0, 12 * (FORCED_RETIRE_AGE - int(person.age))), PENSION_RATE, "Retirement")]


def play(person: Person, events: list[Event], a: Assumptions, calib: Calibration, seed: int, now_month: int,
         years: int = YEARS, pct_series: tuple[str, ...] | None = None) -> Result:
    events = list(events)
    return simulate(person, events + forced_retirement(person, events), years, a, N_PATHS, seed, calib=calib,
                    fixed_until=now_month, pct_series=pct_series)


ASSUMED_JOB_LABEL = "Degree job (assumed)"     # no animation: only used for the card previews


def assume_degree_jobs(events: list[Event], now: int) -> list[Event]:
    """Preview assumption: a graduate takes the job of their degree as soon as possible – at graduation, at ``now``
    if they are already looking, or right after a gap year that is running then.

    The played life is unchanged (no automatic job, the player picks "Job after your degree" or a gap year). Without
    this, every card preview after a degree would price in "never work again" (decades of credit at 8 %)."""
    evs = sorted(events, key=lambda e: e.start)
    extra: list[Event] = []
    for st in (e for e in evs if isinstance(e, Study) and not e.job_after):
        deg = DEGREE_LABELS.get(st.end_label)
        if deg is None:
            continue
        end = st.start + st.months
        if any(isinstance(e, (Job, SelfEmployment, Study, Retirement)) and e.start >= end for e in evs):
            continue                               # the player already decided what comes next
        t = max(end, now)
        for e in evs:                              # a gap year running at t pushes the job back
            if isinstance(e, Unemployment) and e.start <= t < e.start + e.months:
                t = e.start + e.months
        sal, exp = GRAD_JOBS[deg]
        extra.append(Job(t, sal, exp, ASSUMED_JOB_LABEL))
    return list(events) + extra


def preview(person: Person, events: list[Event], opt: Option, snap: Snapshot, a: Assumptions,
            calib: Calibration, seed: int, years: int = YEARS, ctx: Ctx | None = None,
            values: dict | None = None) -> dict:
    evs = opt.events(snap.month, snap, ctx, values)
    res = play(person, assume_degree_jobs(events + evs, snap.month), a, calib, seed, snap.month, years,
               pct_series=())
    out = {"median": res.metrics["median_net_worth_end"], "p5": res.metrics["p5_net_worth_end"],
           "p95": res.metrics["p95_net_worth_end"], "credit": res.metrics["p_credit_future"]}
    # the played life is path 0 (same draws before and after the choice): a purchase that fails there (the market
    # moved, the money is not enough that month) must not be offered – it would animate a house the twin never owns
    for e in evs:
        if isinstance(e, HouseBuy):
            t = min(e.start + 1, res.plan.months)
            out["house_failed"] = bool(res.path0["house_equity"][t] <= 0)
    return out


# ---------------------------------------------------------------- 3D animations from the plan
ANIM_BY_LABEL = {"First job": ("job", "First job!"), "Gap year": ("gapyear", "Gap year"),
                 "Retired": ("retirement", "Retired!"), "Retirement": ("retirement", "Retirement"),
                 "Child moves out": ("child_leaves", "Your child moves out")}


def anim_for(label: str) -> tuple[str, str] | None:
    """(anim type, label) for a plan label, None = no animation."""
    if label in ANIM_BY_LABEL:
        return ANIM_BY_LABEL[label]
    if label in DEGREE_LABELS:
        return "graduation", label
    if label.startswith("Job:") or label == "Promotion":
        return "job", label
    if label == "Startup":
        return "startup", label
    if label in ("Time off", "World trip"):
        return "vacation", label
    if label.startswith("Purchase"):
        return "house", label
    if label == "Child":
        return "child", label
    if label == "Wedding":
        return "wedding", label
    return None


def animations(plan, m0: int, m1: int, turn: int, played: set | None = None, brief: bool = False) -> list[dict]:
    """Events from the month of the decision up to and including the arrival month.
    ``played`` remembers (month, label) pairs so an event on a station boundary animates only once.
    A finished degree emits only ``graduation`` (no job: the player picks one)."""
    out = []
    played = played if played is not None else set()
    for t, label in plan.labels:
        if not (m0 <= t <= m1) or (t, label) in played:
            continue
        played.add((t, label))
        a = anim_for(label)
        if a is None:
            continue
        item = {"id": f"{turn}-{len(out)}", "type": a[0], "label": a[1]}
        if brief:
            item["brief"] = True
        out.append(item)
    return out


DEGREE_LABELS = {"Bachelor's degree": "bachelor", "Master's degree": "master", "Apprenticeship done": "lehre"}


def finished_degrees(plan, month: int) -> frozenset[str]:
    return frozenset(DEGREE_LABELS[l] for t, l in plan.labels if l in DEGREE_LABELS and t <= month)
