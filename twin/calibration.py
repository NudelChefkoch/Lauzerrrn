"""Estimate the cash-flow parameters from the challenge data.

Model per person j, month t (calendar month m):
    X_jt = mu_j + a_{s,m} + sigma_j * k_{s,m} * eps_jt,   eps ~ iid N(0,1)

* mu_j           person's mean monthly net flow                (own data)
* a_{s,m}        seasonal effect of status group s, sum_m a = 0 (pooled within group)
* sigma_j        person's noise in "normal" months             (own data)
* k_{s,m}        noise multiplier per month (Dec/Feb/Aug are wider, pooled within group)

Validated earlier: no autocorrelation, no trend, no variance change between
years; grouping by employment_status beats data-driven clusters out of sample.

The challenge data is NOT copied into this repo; point TWIN_DATA_DIR at it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import STATUS_TO_STATE, STUDENT, EMPLOYED, UNEMPLOYED, SELF_EMPLOYED, OTHER, PART_TIME, param_group

SPECIAL_MONTHS = (2, 8, 12)
_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "ai-financial-twin-lauzhack-2026" / "Data"


def data_dir() -> Path:
    return Path(os.environ.get("TWIN_DATA_DIR", _DEFAULT_DIR))


@dataclass(frozen=True)
class StateParams:
    """Group-level parameters for one life state (used when a person switches state) or parameter group
    (``config.PART_TIME``: seasonality / noise of part-time employees)."""

    seasonal: np.ndarray       # shape (12,), CHF, index 0 = January
    sigma_mult: np.ndarray     # shape (12,), multiplier on sigma
    sigma: float               # median normal-month noise of the group, CHF
    income: float              # median reference net income of the group, CHF


@dataclass(frozen=True)
class Person:
    profile_id: str
    name: str
    age: int
    status: str
    state: int
    income: float              # reference net monthly income (CHF)
    rent: float
    expenses: float            # implied monthly expenses = income - mu (CHF, month 0 prices)
    mu: float                  # calibrated mean net flow
    mu_se: float               # standard error of mu
    sigma: float               # calibrated normal-month noise
    cash: float
    portfolio: float
    debt: float
    debt_rate: float
    goals: tuple[tuple[str, float, int], ...]  # (name, target CHF, months from start)

    @property
    def group(self) -> int:
        """Key of ``Calibration.states`` for the person's own seasonality / noise (PART_TIME for part-timers)."""
        return param_group(self.status, self.state)


@dataclass(frozen=True)
class Calibration:
    persons: dict[str, Person]
    states: dict[int, StateParams]     # life states + parameter group PART_TIME
    young_salary: float        # median net income of employed profiles aged <= 30


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(data_dir() / name)


@lru_cache(maxsize=4)
def calibrate(months: int | None = None) -> Calibration:
    """Calibrate on all months of the data (default) or only on each profile's first ``months`` months
    (out-of-sample backtest, see ``twin.backtest``). Balances (cash, portfolio, debt) are always the opening ones."""
    prof = _read("synthetic-profiles.csv").set_index("profile_id")
    cb = _read("synthetic-cash-balances.csv")
    if months is not None:
        if months < 12:
            raise ValueError("need at least 12 months to calibrate the seasonal pattern")
        cb = cb.sort_values(["profile_id", "month"], kind="stable")
        cb = cb[cb.groupby("profile_id").cumcount() < months].reset_index(drop=True)
    assets = _read("synthetic-assets.csv")
    liab = _read("synthetic-liabilities.csv")
    goals = _read("synthetic-goals.csv")

    cb["m"] = cb["month"].str[5:7].astype(int)
    cb["status"] = cb["profile_id"].map(prof["employment_status"])
    x = cb["net_transactions_chf"]
    cb["mu"] = x.groupby(cb["profile_id"]).transform("mean")
    cb["dev"] = x - cb["mu"]

    seasonal = cb.groupby(["status", "m"])["dev"].mean().unstack()           # status x 12
    seasonal = seasonal.sub(seasonal.mean(axis=1), axis=0)                   # enforce sum = 0
    rows = seasonal.index.get_indexer(cb["status"])
    cb["r"] = cb["dev"].to_numpy() - seasonal.to_numpy()[rows, cb["m"].to_numpy() - 1]
    normal = ~cb["m"].isin(SPECIAL_MONTHS)
    sigma = cb[normal].groupby("profile_id")["r"].std()
    cb["z"] = cb["r"] / cb["profile_id"].map(sigma)
    mult = cb.groupby(["status", "m"])["z"].std().unstack()
    mult = mult.div(mult.loc[:, [m for m in range(1, 13) if m not in SPECIAL_MONTHS]].mean(axis=1), axis=0)

    mu = cb.groupby("profile_id")["net_transactions_chf"].agg(["mean", "std", "count"])
    port = assets[assets.asset_type == "investment_portfolio"].groupby("profile_id")["value_chf"].sum()
    debt = liab.groupby("profile_id").agg(principal=("opening_principal_chf", "sum"),
                                          rate=("annual_interest_rate", "mean"))
    start = pd.Timestamp("2025-01-01")
    goals["months"] = ((pd.to_datetime(goals["target_date"]) - start).dt.days / 30.4375).round().astype(int)

    persons: dict[str, Person] = {}
    for pid, p in prof.iterrows():
        status = p["employment_status"]
        income = float(p["reference_monthly_net_income_chf"])
        m = float(mu.at[pid, "mean"])
        persons[pid] = Person(
            profile_id=pid,
            name=p["display_name"],
            age=int(p["age_at_start"]),
            status=status,
            state=STATUS_TO_STATE.get(status, OTHER),
            income=income,
            rent=float(p["reference_monthly_rent_chf"]),
            expenses=max(income - m, float(p["reference_monthly_rent_chf"])),
            mu=m,
            mu_se=float(mu.at[pid, "std"] / np.sqrt(mu.at[pid, "count"])),
            sigma=float(sigma.get(pid, np.nan)),
            cash=float(p["opening_cash_chf"]),
            portfolio=float(port.get(pid, 0.0)),
            debt=float(debt["principal"].get(pid, 0.0)),
            debt_rate=float(debt["rate"].get(pid, 0.0)),
            goals=tuple((g.goal_name, float(g.target_amount_chf), int(g.months))
                        for g in goals[goals.profile_id == pid].itertuples()),
        )

    prof["sigma"] = sigma
    states: dict[int, StateParams] = {}
    for state, status in [(STUDENT, "student"), (EMPLOYED, "employed"), (UNEMPLOYED, "unemployed"),
                          (SELF_EMPLOYED, "self_employed"), (OTHER, "retired"), (PART_TIME, "part_time")]:
        grp = prof[prof.employment_status == status]
        if grp.empty or status not in seasonal.index:
            continue
        states[state] = StateParams(
            seasonal=seasonal.loc[status].to_numpy(dtype=float),
            sigma_mult=mult.loc[status].to_numpy(dtype=float),
            sigma=float(grp["sigma"].median()),
            income=float(grp["reference_monthly_net_income_chf"].median()),
        )

    young = prof[(prof.employment_status == "employed") & (prof.age_at_start <= 30)]
    return Calibration(persons=persons, states=states,
                       young_salary=float(young["reference_monthly_net_income_chf"].median()))
