"""All tunable assumptions of the twin in one place.

Every number here is an *assumption* (not learned from the challenge data)
unless the comment says "calibrated". The UI should expose these and label
them as assumptions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# Life states
STUDENT, EMPLOYED, UNEMPLOYED, SELF_EMPLOYED, OTHER = 0, 1, 2, 3, 4
RETIRED = OTHER          # retirement uses the "other" state (calibrated from the "retired" group of the data)
STATE_NAMES = {
    STUDENT: "student",
    EMPLOYED: "employed",
    UNEMPLOYED: "unemployed",
    SELF_EMPLOYED: "self_employed",
    OTHER: "other",
}
# Parameter groups for the seasonal pattern a_{s,m} and the noise multiplier k_{s,m}: one per life state, plus
# PART_TIME. Part-timers live in the EMPLOYED state (same game rules, job cards, ALV, random job loss) but use the
# seasonality pooled over the part_time profiles (their December is about +115 CHF instead of the +2,431 of
# full-time employees). Group keys are only used to look up ``Calibration.states``; plan states never take PART_TIME.
PART_TIME = 5
GROUP_NAMES = {**STATE_NAMES, PART_TIME: "part_time"}
STATUS_TO_STATE = {
    "student": STUDENT,
    "employed": EMPLOYED,
    "part_time": EMPLOYED,
    "unemployed": UNEMPLOYED,
    "self_employed": SELF_EMPLOYED,
    "retired": OTHER,
}


def param_group(status: str, state: int) -> int:
    """Parameter group (key of ``Calibration.states``) of a person with this employment status in this state."""
    return PART_TIME if status == "part_time" and state == EMPLOYED else state


@dataclass(frozen=True)
class Market:
    """Merton jump-diffusion for equities, plain diffusion for bonds (annual units)."""

    equity_mu: float = 0.06        # expected equity return p.a. (incl. jumps)
    equity_sigma: float = 0.16     # total equity volatility p.a. (diffusion + jumps)
    jump_lambda: float = 0.10      # crashes per year (1 every 10 years)
    jump_mean: float = -0.25       # mean log jump size (~ -22 %)
    jump_sd: float = 0.10          # sd of log jump size
    bond_mu: float = 0.015
    bond_sigma: float = 0.05
    cash_rate: float = 0.005       # interest on cash account


MARKET_PRESETS: dict[str, Market] = {
    "pessimistisch": Market(equity_mu=0.04, equity_sigma=0.18, jump_lambda=1 / 7, jump_mean=-0.30),
    "standard": Market(),
    "optimistisch": Market(equity_mu=0.08, equity_sigma=0.15, jump_lambda=1 / 12, jump_mean=-0.20),
    "ohne_crash": Market(jump_lambda=0.0, jump_mean=0.0, jump_sd=0.0),
}


@dataclass(frozen=True)
class Strategy:
    """How the person saves and invests."""

    equity_share: float = 0.6      # share of the portfolio in equities (rest bonds), rebalanced monthly
    buffer_months: float = 3.0     # emergency fund in months of expenses kept as cash
    invest_rate: float = 1.0       # share of cash above the buffer invested each month


STRATEGY_PRESETS: dict[str, Strategy] = {
    "konservativ": Strategy(equity_share=0.25, buffer_months=6.0),
    "ausgewogen": Strategy(equity_share=0.6, buffer_months=3.0),
    "risky": Strategy(equity_share=1.0, buffer_months=1.0),
}


@dataclass(frozen=True)
class Macro:
    inflation: float = 0.01        # p.a., applied from month 1 to expenses, rent, house value
    # p.a. real salary growth while employed. Default 0: the challenge data shows flat employed income by age
    # (median net income of employed profiles per age band stays at ~7,300-8,200 CHF from 17 to 66, slope ~ -8 CHF
    # per year), so a built-in career ladder is not supported. Promotions / job changes in the game still raise pay.
    career_growth: float = 0.0
    student_income_growth: float = 0.0  # p.a. real growth of side-job income while studying
    income_scale: float = 1.0           # multiplies all planned income (for sensitivity analysis)
    # parameter uncertainty: every Monte Carlo path draws its own mean flow mu_path ~ N(mu, mu_se) once (calibrated
    # standard error of the person's mean); path 0 (the played life) keeps the point estimate. False = point estimate
    # on every path (tests, sensitivity tool). The backtest shows the 90 % band is too narrow without it.
    param_uncertainty: bool = True


@dataclass(frozen=True)
class Shortfall:
    """Order when cash < 0: 1) sell portfolio, 2) cut spending, 3) credit."""

    spending_cut: float = 0.15     # expenses are cut by this share while in austerity
    credit_rate: float = 0.08      # p.a. on consumer credit / overdraft
    floor_months: float = 1.0      # austerity ends once cash >= this many months of expenses and no debt


@dataclass(frozen=True)
class Shocks:
    """Optional random life events on top of the scenario plan."""

    job_loss_per_year: float = 0.0     # 0 = off; e.g. 0.025 for 2.5 % p.a.
    reemployment_months: float = 4.0   # mean search time (young adults find jobs faster)


@dataclass(frozen=True)
class Social:
    """Swiss rules (simplified)."""

    alv_rate: float = 0.70             # unemployment benefit share of last salary
    alv_max_months: int = 9            # ~200 daily allowances (<25, no kids); 18 for older
    net_to_gross: float = 1 / 0.87     # rough factor net -> gross salary
    mortgage_rate: float = 0.02        # p.a. actual mortgage interest
    affordability_rate: float = 0.05   # imputed rate in the bank's affordability check
    maintenance: float = 0.01          # p.a. of house price
    purchase_fees: float = 0.02        # notary, land registry, ...
    min_equity: float = 0.20           # down payment share
    second_mortgage_years: int = 15    # amortise the part above 2/3 within this many years


@dataclass(frozen=True)
class Assumptions:
    market: Market = field(default_factory=Market)
    strategy: Strategy = field(default_factory=Strategy)
    macro: Macro = field(default_factory=Macro)
    shortfall: Shortfall = field(default_factory=Shortfall)
    shocks: Shocks = field(default_factory=Shocks)
    social: Social = field(default_factory=Social)

    def with_(self, **kw) -> "Assumptions":
        return replace(self, **kw)
