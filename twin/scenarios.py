"""Life events and the deterministic plan they produce.

A scenario is a list of events. ``build_plan`` turns it into month-by-month
arrays (state, income, extra costs, ...) that the engine then simulates with
noise, market returns and optional random shocks on top.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .calibration import Calibration, Person
from .config import Assumptions, STUDENT, EMPLOYED, UNEMPLOYED, SELF_EMPLOYED, RETIRED, STATE_NAMES


@dataclass(frozen=True)
class Study:
    """Study for ``months`` months; afterwards employed with ``salary_after`` – or, with ``job_after=False``,
    "graduated / looking": without a job, income 0 and no unemployment benefits (the game lets the player pick
    the first job or a gap year)."""
    start: int
    months: int
    tuition_per_year: float = 8000.0       # S001 assumption
    side_income: float | None = None       # net side-job income while studying (default: current or 1000)
    salary_after: float | None = None      # default: median young employed salary from the data
    expenses_after: float = 0.0            # lifestyle change per month once working
    label: str = "Study"
    end_label: str = "First job"
    job_after: bool = True                 # False: no automatic job after the degree (graduated / looking)


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
    label: str = "Job change"


@dataclass(frozen=True)
class Unemployment:
    start: int
    months: int                            # afterwards back to the previous state and salary
    label: str = "Unemployed"
    alv: bool = True                       # False: no unemployment benefits (gap year: income 0)


@dataclass(frozen=True)
class SelfEmployment:
    start: int
    income: float | None = None            # mean net per month; default: median self-employed group
    startup_cost: float = 10_000.0
    label: str = "Self-employed"


@dataclass(frozen=True)
class HouseBuy:
    start: int
    price: float
    label: str = "House purchase"


@dataclass(frozen=True)
class OneOff:
    start: int
    amount: float                          # positive = cost, negative = windfall
    label: str = "One-off"


@dataclass(frozen=True)
class ExpenseChange:
    start: int
    amount: float                          # change of monthly expenses from this month on (+ = more)
    label: str = "Expenses"
    months: int | None = None              # None = for good; else the change ends after this many months
    end_label: str | None = None           # label at the end month (e.g. "Child moves out")


@dataclass(frozen=True)
class Retirement:
    """Retire: from this month on the state is RETIRED and the income is ``rate`` x the last salary
    (AHV + pension fund, simplified), at least ``minimum`` (AHV minimum pension). Expenses stay unchanged."""
    start: int
    rate: float = 0.60
    label: str = "Retired"
    minimum: float = 1260.0


@dataclass(frozen=True)
class MarketCrash:
    start: int
    size: float = -0.30                    # equity drop in that month, on top of normal returns
    label: str = "Market crash"


@dataclass(frozen=True)
class StrategyChange:
    start: int
    equity_share: float                    # new share of equities in the portfolio from this month on
    label: str = "Strategy"
    buffer_months: float | None = None     # new emergency buffer in months of expenses (None = unchanged)
    invest_rate: float | None = None       # new share of cash above the buffer invested monthly (None = unchanged)


Event = (Study | Job | JobChange | Unemployment | SelfEmployment | HouseBuy | OneOff
         | ExpenseChange | MarketCrash | StrategyChange | Retirement)


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
    buffer_months: np.ndarray | None = None  # emergency buffer (months of expenses) per month
    invest_rate: np.ndarray | None = None    # share of cash above the buffer invested, per month


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
    buffer = np.full(T, a.strategy.buffer_months, dtype=float)
    invest = np.full(T, a.strategy.invest_rate, dtype=float)
    labels: list[tuple[int, str]] = []
    g = a.macro.career_growth

    def career(t0: int, salary: float) -> np.ndarray:
        years = np.arange(T - t0) / 12.0
        return salary * (1 + g) ** years

    if person.state == EMPLOYED:          # someone already employed gets the same career growth as a new job
        income[:] = career(0, person.income)

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
                if ev.job_after:
                    sal = ev.salary_after if ev.salary_after is not None else calib.young_salary
                    set_from(t1, EMPLOYED, career(t1, sal))
                    extra_exp[t1:] += ev.expenses_after
                else:                              # graduated / looking: no job, no ALV, side income ends
                    set_from(t1, UNEMPLOYED, 0.0)
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
            prev_state = state[t0:].copy()
            prev_income = income[t0:].copy()
            t1 = min(T, t0 + ev.months)
            last = income[t0 - 1] if t0 > 0 else person.income
            state[t0:t1] = UNEMPLOYED
            income[t0:t1] = a.social.alv_rate * last if ev.alv else 0.0
            alv_applies[t0:t1] = ev.alv
            if t1 < T:
                state[t1:] = prev_state[t1 - t0:]
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
            t1 = T if ev.months is None else min(T, t0 + max(0, int(ev.months)))
            extra_exp[t0:t1] += ev.amount
            if ev.months is not None and ev.end_label and t1 < T:
                labels.append((t1, ev.end_label))
        elif isinstance(ev, Retirement):
            worked = np.nonzero(np.isin(state[:t0], (EMPLOYED, SELF_EMPLOYED)) & (income[:t0] > 0))[0]
            if len(worked):
                base = float(income[worked[-1]])
            else:
                base = person.income if person.state in (EMPLOYED, SELF_EMPLOYED) else 0.0
            set_from(t0, RETIRED, max(ev.rate * base, ev.minimum))
        elif isinstance(ev, MarketCrash):
            crashes.append(ev)
        elif isinstance(ev, StrategyChange):
            equity[t0:] = ev.equity_share
            if ev.buffer_months is not None:
                buffer[t0:] = ev.buffer_months
            if ev.invest_rate is not None:
                invest[t0:] = ev.invest_rate
        else:  # pragma: no cover
            raise TypeError(f"unknown event {ev!r}")

    alv_base = np.where(state == EMPLOYED, income, 0.0)
    return Plan(T, state, income, alv_applies, alv_base, extra_cost, extra_exp, houses, labels, crashes, equity,
                buffer, invest)


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
PRESET_LABELS = {"basis": "No events", "berufseinstieg": "First job", "master": "Master's degree",
                 "master_dann_wechsel": "Master, then job switch", "jobverlust": "Job loss",
                 "startup": "Startup", "hauskauf": "House purchase"}


def describe(plan: Plan) -> list[str]:
    out = []
    for t, label in plan.labels:
        out.append(f"Month {t:3d}: {label} -> {STATE_NAMES[int(plan.state[t])]}, "
                   f"income {plan.income[t]:,.0f} CHF")
    return out
