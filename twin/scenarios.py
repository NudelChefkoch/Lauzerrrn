"""Life events and the deterministic plan they produce.

A scenario is a list of events. ``build_plan`` turns it into month-by-month
arrays (state, income, extra costs, ...) that the engine then simulates with
noise, market returns and optional random shocks on top.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .calibration import Calibration, Person
from .config import Assumptions, STUDENT, EMPLOYED, UNEMPLOYED, SELF_EMPLOYED, STATE_NAMES


@dataclass(frozen=True)
class Study:
    """Study for ``months`` months; afterwards employed with ``salary_after``."""
    start: int
    months: int
    tuition_per_year: float = 8000.0       # S001 assumption
    side_income: float | None = None       # net side-job income while studying (default: current or 1000)
    salary_after: float | None = None      # default: median young employed salary from the data
    expenses_after: float = 0.0            # lifestyle change per month once working
    label: str = "Studium"
    end_label: str = "Berufseinstieg"


@dataclass(frozen=True)
class Job:
    start: int
    salary: float | None = None            # net per month; default: median young employed salary
    extra_expenses: float = 0.0            # lifestyle change per month
    label: str = "Job"


@dataclass(frozen=True)
class JobChange:
    start: int
    raise_pct: float = 0.10
    gap_months: int = 0                    # months without income between jobs (no ALV when quitting)
    label: str = "Jobwechsel"


@dataclass(frozen=True)
class Unemployment:
    start: int
    months: int                            # afterwards back to the previous salary
    label: str = "Arbeitslos"


@dataclass(frozen=True)
class SelfEmployment:
    start: int
    income: float | None = None            # mean net per month; default: median self-employed group
    startup_cost: float = 10_000.0
    label: str = "Selbststaendig"


@dataclass(frozen=True)
class HouseBuy:
    start: int
    price: float
    label: str = "Hauskauf"


@dataclass(frozen=True)
class OneOff:
    start: int
    amount: float                          # positive = cost, negative = windfall
    label: str = "Einmalig"


@dataclass(frozen=True)
class ExpenseChange:
    start: int
    amount: float                          # change of monthly expenses from this month on (+ = more)
    label: str = "Ausgaben"


@dataclass(frozen=True)
class MarketCrash:
    start: int
    size: float = -0.30                    # equity drop in that month, on top of normal returns
    label: str = "Boersencrash"


@dataclass(frozen=True)
class StrategyChange:
    start: int
    equity_share: float                    # new share of equities in the portfolio from this month on
    label: str = "Strategie"


Event = (Study | Job | JobChange | Unemployment | SelfEmployment | HouseBuy | OneOff
         | ExpenseChange | MarketCrash | StrategyChange)


@dataclass
class Plan:
    months: int
    state: np.ndarray            # planned life state per month
    income: np.ndarray           # planned net income per month in month-0 prices (before inflation)
    alv_applies: np.ndarray      # True where unemployment benefits are capped by alv_max_months
    alv_base: np.ndarray         # salary that a random job loss would refer to
    extra_cost: np.ndarray       # tuition, one-offs, startup cost (month-0 prices)
    extra_expenses: np.ndarray   # lifestyle changes (month-0 prices)
    houses: list[HouseBuy] = field(default_factory=list)
    labels: list[tuple[int, str]] = field(default_factory=list)
    crashes: list[MarketCrash] = field(default_factory=list)
    equity_share: np.ndarray | None = None   # equity share per month


def build_plan(person: Person, events: list[Event], months: int,
               calib: Calibration, a: Assumptions) -> Plan:
    T = months
    state = np.full(T, person.state, dtype=int)
    income = np.full(T, person.income, dtype=float)
    alv_applies = np.zeros(T, dtype=bool)
    extra_cost = np.zeros(T)
    extra_exp = np.zeros(T)
    houses: list[HouseBuy] = []
    crashes: list[MarketCrash] = []
    equity = np.full(T, a.strategy.equity_share)
    labels: list[tuple[int, str]] = []
    g = a.macro.career_growth

    def career(t0: int, salary: float) -> np.ndarray:
        years = np.arange(T - t0) / 12.0
        return salary * (1 + g) ** years

    def set_from(t0: int, s: int, inc: np.ndarray | float) -> None:
        state[t0:] = s
        income[t0:] = inc
        alv_applies[t0:] = False

    for ev in sorted(events, key=lambda e: e.start):
        t0 = max(0, min(ev.start, T))
        if t0 >= T:
            continue
        labels.append((t0, ev.label))
        if isinstance(ev, Study):
            side = ev.side_income if ev.side_income is not None else (
                person.income if person.state == STUDENT else 1000.0)
            t1 = min(T, t0 + ev.months)
            set_from(t0, STUDENT, side * (1 + a.macro.student_income_growth) ** (np.arange(T - t0) / 12))
            extra_cost[t0:t1] += ev.tuition_per_year / 12
            if t1 < T:
                sal = ev.salary_after if ev.salary_after is not None else calib.young_salary
                set_from(t1, EMPLOYED, career(t1, sal))
                extra_exp[t1:] += ev.expenses_after
                labels.append((t1, ev.end_label))
        elif isinstance(ev, Job):
            sal = ev.salary if ev.salary is not None else calib.young_salary
            set_from(t0, EMPLOYED, career(t0, sal))
            extra_exp[t0:] += ev.extra_expenses
        elif isinstance(ev, JobChange):
            prev = income[t0 - 1] if t0 > 0 else income[0]
            t1 = min(T, t0 + ev.gap_months)
            if t1 > t0:
                state[t0:t1] = UNEMPLOYED
                income[t0:t1] = 0.0
                alv_applies[t0:t1] = False
            if t1 < T:
                set_from(t1, EMPLOYED, career(t1, prev * (1 + ev.raise_pct)))
        elif isinstance(ev, Unemployment):
            prev_state = state[t0 - 1] if t0 > 0 else person.state
            prev_income = income[t0:].copy()
            t1 = min(T, t0 + ev.months)
            last = income[t0 - 1] if t0 > 0 else person.income
            state[t0:t1] = UNEMPLOYED
            income[t0:t1] = a.social.alv_rate * last
            alv_applies[t0:t1] = True
            if t1 < T:
                state[t1:] = prev_state
                income[t1:] = prev_income[t1 - t0:]
        elif isinstance(ev, SelfEmployment):
            inc = ev.income if ev.income is not None else calib.states[SELF_EMPLOYED].income
            set_from(t0, SELF_EMPLOYED, inc)
            extra_cost[t0] += ev.startup_cost
        elif isinstance(ev, HouseBuy):
            houses.append(ev)
        elif isinstance(ev, OneOff):
            extra_cost[t0] += ev.amount
        elif isinstance(ev, ExpenseChange):
            extra_exp[t0:] += ev.amount
        elif isinstance(ev, MarketCrash):
            crashes.append(ev)
        elif isinstance(ev, StrategyChange):
            equity[t0:] = ev.equity_share
        else:  # pragma: no cover
            raise TypeError(f"unknown event {ev!r}")

    alv_base = np.where(state == EMPLOYED, income, 0.0)
    return Plan(T, state, income, alv_applies, alv_base, extra_cost, extra_exp, houses, labels, crashes, equity)


# ---------------------------------------------------------------- presets
def preset(name: str, person: Person) -> list[Event]:
    """A few ready-made scenarios (all starting in month 0 unless noted)."""
    if name == "basis":
        return []
    if name == "berufseinstieg":
        return [Job(start=0, salary=4200, extra_expenses=800)]
    if name == "master":
        # S001: 8000 CHF tuition p.a., 2 years; then a first job
        return [Study(start=0, months=24, tuition_per_year=8000, salary_after=5500, expenses_after=1000)]
    if name == "master_dann_wechsel":
        return [Study(start=0, months=24, tuition_per_year=8000, salary_after=5500, expenses_after=1000),
                JobChange(start=60, raise_pct=0.15, gap_months=1)]
    if name == "jobverlust":
        return [Job(start=0, salary=4200), Unemployment(start=24, months=6)]
    if name == "startup":
        return [SelfEmployment(start=0, startup_cost=15_000)]
    if name == "hauskauf":
        return [Job(start=0, salary=6000), HouseBuy(start=96, price=750_000)]
    raise KeyError(f"unknown preset {name!r}; choose from {PRESETS}")


PRESETS = ["basis", "berufseinstieg", "master", "master_dann_wechsel", "jobverlust", "startup", "hauskauf"]


def describe(plan: Plan) -> list[str]:
    out = []
    for t, label in plan.labels:
        out.append(f"Monat {t:3d}: {label} -> {STATE_NAMES[int(plan.state[t])]}, "
                   f"Einkommen {plan.income[t]:,.0f} CHF")
    return out
