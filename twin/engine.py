"""Monte Carlo engine: accounting core + regime-switching cash-flow SDE + Merton portfolio.

Per path and month t (calendar month m):
  1. portfolio return   (equities: Merton jump-diffusion, bonds: diffusion; monthly rebalanced)
  2. interest           (cash +, credit -, loan -, mortgage -)
  3. net flow           X = income(state) - expenses*(1-cut) - costs + a_{s,m} + sigma_s*k_{s,m}*eps
  4. house purchase / housing costs
  5. shortfall rule     cash<0: sell portfolio -> cut spending -> credit
  6. repay debt, then invest cash above the emergency buffer

Net worth N = cash + portfolio + house - mortgage - credit - loan.
Every CHF that changes N is booked in ``booked``; ``identity_error`` checks
N_T - N_0 == sum(booked) on every path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .calibration import Calibration, Person, calibrate
from .config import Assumptions, EMPLOYED, UNEMPLOYED
from .scenarios import Event, Plan, build_plan

PCTS = (5, 25, 50, 75, 95)
SERIES = ("cash", "portfolio", "debt", "house_equity", "net_worth", "liquid")


@dataclass
class Result:
    person: Person
    plan: Plan
    assumptions: Assumptions
    n_paths: int
    percentiles: dict[str, np.ndarray]     # series -> (len(PCTS), T+1)
    samples: np.ndarray                    # (n_samples, T+1) net worth paths
    metrics: dict[str, float]
    goals: list[dict]
    identity_error: float
    mean: dict[str, np.ndarray] = field(default_factory=dict)
    path0: dict[str, np.ndarray] = field(default_factory=dict)   # the first simulated life (game uses it)


def _market_draws(rng, a: Assumptions, shape, stochastic: bool):
    """Monthly log returns of equities and bonds."""
    m, dt = a.market, 1 / 12
    mu_e, mu_b = np.log1p(m.equity_mu), np.log1p(m.bond_mu)
    if not stochastic:
        return np.full(shape, mu_e * dt), np.full(shape, mu_b * dt)
    jump_var = m.jump_lambda * (m.jump_mean ** 2 + m.jump_sd ** 2)
    sig_d = np.sqrt(max(m.equity_sigma ** 2 - jump_var, 1e-6))
    kappa = np.expm1(m.jump_mean + 0.5 * m.jump_sd ** 2)
    n_j = rng.poisson(m.jump_lambda * dt, shape)
    jumps = n_j * m.jump_mean + np.sqrt(n_j) * m.jump_sd * rng.standard_normal(shape)
    eq = (mu_e - m.jump_lambda * kappa - 0.5 * sig_d ** 2) * dt + sig_d * np.sqrt(dt) * rng.standard_normal(shape) + jumps
    bd = (mu_b - 0.5 * m.bond_sigma ** 2) * dt + m.bond_sigma * np.sqrt(dt) * rng.standard_normal(shape)
    return eq, bd


def simulate(person: Person | str, events: list[Event] | None = None, years: int = 10,
             a: Assumptions | None = None, n_paths: int = 5000, seed: int = 0,
             stochastic: bool = True, calib: Calibration | None = None, n_samples: int = 20,
             fixed_until: int = 0) -> Result:
    """fixed_until: all paths share path 0's random draws before this month (= the realised past),
    so the fan shows futures *conditional* on what already happened."""
    calib = calib or calibrate()
    if isinstance(person, str):
        person = calib.persons[person]
    a = a or Assumptions()
    if not 1 <= years <= 25:
        raise ValueError("years must be between 1 and 25")
    T, N = 12 * years, (n_paths if stochastic else 1)
    plan = build_plan(person, events or [], T, calib, a)
    rng = np.random.default_rng(seed)
    st, sh, so, sc = a.strategy, a.shortfall, a.social, a.shocks
    buf = plan.buffer_months if plan.buffer_months is not None else np.full(T, st.buffer_months)
    inv = plan.invest_rate if plan.invest_rate is not None else np.full(T, st.invest_rate)

    # ----- state per path
    cash = np.full(N, person.cash, dtype=float)
    port = np.full(N, person.portfolio, dtype=float)
    loan = np.full(N, person.debt, dtype=float)
    credit = np.zeros(N)
    house = np.zeros(N)
    mortgage = np.zeros(N)
    amort = np.zeros(N)                 # monthly amortisation (month-0 CHF, fixed nominal)
    owns = np.zeros(N, bool)
    austerity = np.zeros(N, bool)
    rand_unemp = np.zeros(N, bool)
    unemp_months = np.zeros(N, int)

    def nw():
        return cash + port + house - mortgage - credit - loan

    nw0 = nw().copy()
    booked = np.zeros(N)
    # flags
    ever_credit = np.zeros(N, bool)
    credit_future = np.zeros(N, bool)
    ever_sold = np.zeros(N, bool)
    aust_months = np.zeros(N)
    alv_exhausted = np.zeros(N, bool)
    house_failed = np.zeros(N, bool)
    house_unaffordable = np.zeros(N, bool)
    min_liquid = np.full(N, np.inf)

    store = {s: np.empty((N, T + 1)) for s in SERIES}

    def record(t):
        store["cash"][:, t] = cash
        store["portfolio"][:, t] = port
        store["debt"][:, t] = credit + loan + mortgage
        store["house_equity"][:, t] = house - mortgage
        store["net_worth"][:, t] = nw()
        store["liquid"][:, t] = cash + port - credit

    record(0)
    eq, bd = _market_draws(rng, a, (T, N), stochastic)
    for cr in plan.crashes:                      # injected crash ("Apollo-13 mode")
        if 0 <= cr.start < T:
            eq[cr.start] += np.log1p(cr.size)
    eps = rng.standard_normal((T, N)) if stochastic else np.zeros((T, N))
    p_loss = 1 - (1 - sc.job_loss_per_year) ** (1 / 12) if stochastic else 0.0
    p_back = 1 / max(sc.reemployment_months, 1e-9)
    u_loss = rng.random((T, N))
    u_back = rng.random((T, N))
    if fixed_until > 0:
        for arr in (eq, bd, eps, u_loss, u_back):
            arr[:fixed_until] = arr[:fixed_until, :1]
    state_path0 = np.full(T + 1, person.state)
    infl_m = (1 + a.macro.inflation) ** (1 / 12)

    for t in range(T):
        m = t % 12
        P = (1 + a.macro.inflation) ** (t / 12)        # price level

        # 1. portfolio return
        w = plan.equity_share[t]
        r = w * np.expm1(eq[t]) + (1 - w) * np.expm1(bd[t])
        gain = port * r
        port += gain
        booked += gain

        # 2. interest
        ci = np.where(cash > 0, cash * a.market.cash_rate / 12, 0.0)
        di = credit * sh.credit_rate / 12 + loan * person.debt_rate / 12
        mi = mortgage * so.mortgage_rate / 12
        cash += ci - mi
        credit += credit * sh.credit_rate / 12
        loan += loan * person.debt_rate / 12
        booked += ci - di - mi

        # 3. life state (plan + random job loss)
        s_plan = plan.state[t]
        if s_plan == EMPLOYED and p_loss > 0:
            rand_unemp = np.where(rand_unemp, u_back[t] >= p_back, u_loss[t] < p_loss)
        else:
            rand_unemp[:] = False
        state = np.where(rand_unemp, UNEMPLOYED, s_plan)
        state_path0[t + 1] = state[0]
        unemp_months = np.where(state == UNEMPLOYED, unemp_months + 1, 0)

        income = np.where(rand_unemp, so.alv_rate * plan.alv_base[t], plan.income[t]) * P * a.macro.income_scale
        capped = (rand_unemp | plan.alv_applies[t]) & (unemp_months > so.alv_max_months)
        alv_exhausted |= capped
        income = np.where(capped, 0.0, income)

        expenses = (person.expenses + plan.extra_expenses[t]) * P
        expenses = np.where(owns, expenses - person.rent * P, expenses)
        spend = expenses * np.where(austerity, 1 - sh.spending_cut, 1.0)

        seas = np.zeros(N)
        sig = np.zeros(N)
        for s in np.unique(state):
            idx = state == s
            sp = calib.states[int(s)]
            seas[idx] = sp.seasonal[m]
            sig[idx] = (person.sigma if s == person.state else sp.sigma) * sp.sigma_mult[m]
        flow = income - spend - plan.extra_cost[t] * P + (seas + sig * eps[t]) * P
        cash += flow
        booked += flow

        # 4. housing
        for hb in plan.houses:
            if hb.start == t:
                price = hb.price * P
                need = price * (so.min_equity + so.purchase_fees)
                ok = ~owns & (cash + port >= need)
                house_failed |= ~owns & ~ok
                # pay with cash above the emergency buffer, then portfolio, then the buffer itself
                free = np.clip(cash - buf[t] * expenses, 0, None)
                from_free = np.minimum(free, need)
                from_port = np.minimum(port, need - from_free)
                from_cash = need - from_port
                cash = np.where(ok, cash - from_cash, cash)
                port = np.where(ok, port - from_port, port)
                mortgage = np.where(ok, price * (1 - so.min_equity), mortgage)
                house = np.where(ok, price, house)
                second = np.maximum(price * (1 - so.min_equity) - price * 2 / 3, 0)
                amort = np.where(ok, second / (12 * so.second_mortgage_years), amort)
                fees = np.where(ok, price * so.purchase_fees, 0.0)
                booked -= fees
                gross_year = np.maximum(income, 1.0) * 12 * so.net_to_gross
                burden = (price * (1 - so.min_equity) * so.affordability_rate + price * so.maintenance
                          + second / so.second_mortgage_years)
                house_unaffordable |= ok & (burden > gross_year / 3)
                owns |= ok
        if owns.any():
            maint = np.where(owns, house * so.maintenance / 12, 0.0)
            pay = np.minimum(amort, mortgage)
            cash -= maint + pay
            mortgage -= pay
            appr = house * (infl_m - 1)
            house += appr
            booked += appr - maint

        # 5. shortfall: sell -> cut spending -> credit
        short = cash < 0
        sell = np.where(short, np.minimum(port, -cash), 0.0)
        port -= sell
        cash += sell
        ever_sold |= sell > 0
        austerity |= short
        borrow = np.where(cash < 0, -cash, 0.0)
        credit += borrow
        cash += borrow
        ever_credit |= borrow > 0
        if t >= fixed_until:
            credit_future |= borrow > 0

        # 6. repay (credit first, then loan) above the floor, invest above the buffer
        floor = sh.floor_months * expenses
        for debt in (credit, loan):
            rep = np.clip(np.minimum(debt, cash - floor), 0, None)
            debt -= rep
            cash -= rep
        austerity &= ~((cash >= floor) & (credit <= 0))
        aust_months += austerity
        # only invest while the expected monthly flow is positive (no invest-then-sell while burning cash)
        saving_phase = (income - spend - plan.extra_cost[t] * P + seas * P) > 0
        invest = np.where((credit <= 0) & (loan <= 0) & saving_phase,
                          np.clip(cash - buf[t] * expenses, 0, None) * inv[t], 0.0)
        cash -= invest
        port += invest

        record(t + 1)
        min_liquid = np.minimum(min_liquid, store["liquid"][:, t + 1])

    ident = float(np.max(np.abs(nw() - nw0 - booked)))
    pct = {s: np.percentile(v, PCTS, axis=0) for s, v in store.items()}
    mean = {s: v.mean(axis=0) for s, v in store.items()}
    final = store["net_worth"][:, -1]
    metrics = {
        "median_net_worth_end": float(np.median(final)),
        "p5_net_worth_end": float(np.percentile(final, 5)),
        "p95_net_worth_end": float(np.percentile(final, 95)),
        "p_ever_credit": float(ever_credit.mean()),
        "p_credit_end": float((credit > 0).mean()),
        "p_credit_future": float(credit_future.mean()),
        "p5_lowest_liquid": float(np.percentile(min_liquid, 5)),
        "p_ever_sold_portfolio": float(ever_sold.mean()),
        "avg_austerity_months": float(aust_months.mean()),
        "p_alv_exhausted": float(alv_exhausted.mean()),
        "p_negative_net_worth_end": float((final < 0).mean()),
    }
    if plan.houses:
        metrics["p_house_failed"] = float(house_failed.mean())
        metrics["p_house_unaffordable"] = float(house_unaffordable.mean())
    goals = []
    for name, target, month in person.goals:
        if 0 < month <= T:
            liq = store["liquid"][:, month]
            goals.append({"goal": name, "target": target, "month": month,
                          "p_reached": float((liq >= target).mean()),
                          "median_liquid": float(np.median(liq))})
    k = min(n_samples, N)
    return Result(person, plan, a, N, pct, store["net_worth"][:k].copy(), metrics, goals, ident, mean,
                  {**{s: v[0].copy() for s, v in store.items()}, "state": state_path0})
