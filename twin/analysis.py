"""Sensitivity analysis (tornado) with common random numbers: every run uses the same seed,
so differences come from the parameter, not from Monte Carlo noise."""
from __future__ import annotations

from dataclasses import replace

from .calibration import Calibration, Person
from .config import Assumptions
from .engine import simulate
from .scenarios import Event


def _variants(a: Assumptions):
    m, mac, sh, sc = a.market, a.macro, a.shortfall, a.shocks
    yield "Equity return", "3 %", "9 %", a.with_(market=replace(m, equity_mu=0.03)), a.with_(market=replace(m, equity_mu=0.09))
    yield "Inflation", "0 %", "2.5 %", a.with_(macro=replace(mac, inflation=0.0)), a.with_(macro=replace(mac, inflation=0.025))
    yield "Salary growth", "0 %", "4 %", a.with_(macro=replace(mac, career_growth=0.0)), a.with_(macro=replace(mac, career_growth=0.04))
    yield "Income", "−10 %", "+10 %", a.with_(macro=replace(mac, income_scale=0.9)), a.with_(macro=replace(mac, income_scale=1.1))
    yield "Equity volatility", "10 %", "25 %", a.with_(market=replace(m, equity_sigma=0.10)), a.with_(market=replace(m, equity_sigma=0.25))
    yield "Loan rate", "4 %", "12 %", a.with_(shortfall=replace(sh, credit_rate=0.04)), a.with_(shortfall=replace(sh, credit_rate=0.12))
    yield "Job loss p.a.", "0 %", "5 %", a.with_(shocks=replace(sc, job_loss_per_year=0.0)), a.with_(shocks=replace(sc, job_loss_per_year=0.05))


def tornado(person: Person, events: list[Event], years: int, a: Assumptions, calib: Calibration,
            n_paths: int = 1000, seed: int = 0, metric: str = "median_net_worth_end") -> tuple[float, list[dict]]:
    base = simulate(person, events, years, a, n_paths, seed, calib=calib).metrics[metric]
    rows = []
    for name, lo_lbl, hi_lbl, lo, hi in _variants(a):
        v_lo = simulate(person, events, years, lo, n_paths, seed, calib=calib).metrics[metric]
        v_hi = simulate(person, events, years, hi, n_paths, seed, calib=calib).metrics[metric]
        rows.append({"parameter": name, "low_label": lo_lbl, "high_label": hi_lbl,
                     "low": v_lo - base, "high": v_hi - base})
    rows.sort(key=lambda r: max(abs(r["low"]), abs(r["high"])))
    return base, rows
