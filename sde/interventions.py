"""Bausteine für Szenarien (Entscheidungen und externe Ereignisse).

Ein Szenario ist ein Plan aus Interventionen plus optionalen Overrides von SimConfig
und Profilwerten. compile_plan() übersetzt ihn in deterministische Monatsreihen, die
simulate_profile() Monat für Monat anwendet. Monate zählen ab Simulationsstart (0 = Jan 2025).
Beträge: + = Zufluss, − = Abfluss (CHF).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Income:
    """Einkommen im Fenster [start, end): set ersetzt, sonst * factor, dann + add (CHF/Mt.)."""
    start: int
    end: int | None = None
    factor: float = 1.0
    set: float | None = None
    add: float = 0.0


@dataclass
class Expense:
    """Ausgaben im Fenster: * factor * (1+factor_growth)^Jahre + add * (1+add_growth)^Jahre.
    add ist real (wird mit der Inflation indexiert)."""
    start: int
    end: int | None = None
    factor: float = 1.0
    add: float = 0.0
    factor_growth: float = 0.0
    add_growth: float = 0.0


@dataclass
class OneOff:
    """Einmalbetrag; prob < 1 -> tritt nur in diesem Anteil der Pfade ein."""
    month: int
    amount: float
    prob: float = 1.0


@dataclass
class Loan:
    """Annuitätenkredit ab month. disburse: Betrag fliesst ins Cash (sonst z. B. Hypothek
    oder bestehende Schuld). Optional Zinsstufe ab rate_step_month."""
    month: int
    principal: float
    rate: float
    term: int
    disburse: bool = True
    rate_step_month: int | None = None
    new_rate: float | None = None


@dataclass
class Property:
    """Immobilienkauf: Eigenkapital + Gebühren aus Cash, Hypothek als Kredit,
    Unterhalt als Ausgabe, eingesparte Miete. Wert folgt GBM (cfg.mu_H, cfg.sigma_H)."""
    month: int
    price: float
    down: float = 0.20
    fees: float = 0.03
    rate: float = 0.02
    term: int = 360
    maintenance: float = 0.01      # p.a. vom Kaufpreis
    rent_saved: float = 0.0        # CHF/Mt. eingesparte Miete
    rate_step_month: int | None = None
    new_rate: float | None = None


@dataclass
class DepotShock:
    month: int
    ret: float                      # einmalige Rendite, z. B. -0.3


@dataclass
class PropertyShock:
    month: int
    ret: float


@dataclass
class DepotDrift:
    start: int
    end: int | None
    add: float                      # Zusatz zur Depotrendite p.a.


@dataclass
class Inflation:
    start: int
    end: int | None
    add: float                      # Zusatz zur Inflation p.a.


@dataclass
class Invest:
    """Monatlicher Transfer Cash -> Depot (höchstens vorhandenes positives Cash)."""
    start: int
    end: int | None
    amount: float


@dataclass
class JobRisk:
    start: int
    end: int | None
    mult: float                     # Multiplikator auf die Jobverlust-Rate


@dataclass
class Plan:
    interventions: list = field(default_factory=list)
    cfg: dict = field(default_factory=dict)       # SimConfig-Overrides
    row: dict = field(default_factory=dict)       # Profil-Overrides


@dataclass
class Compiled:
    T: int
    inc_factor: np.ndarray
    inc_set: np.ndarray
    inc_add: np.ndarray
    exp_factor: np.ndarray
    exp_add: np.ndarray
    oneoff: np.ndarray
    stoch_oneoffs: list
    mu_add: np.ndarray
    infl_add: np.ndarray
    invest_amt: np.ndarray
    hz_mult: np.ndarray
    depot_shock: np.ndarray
    prop_shock: np.ndarray
    prop_buy: np.ndarray
    loan_L: np.ndarray              # (T+1) zusätzliche Schulden
    loan_pay: np.ndarray
    loan_disb: np.ndarray

    @classmethod
    def empty(cls, T: int) -> "Compiled":
        z = lambda: np.zeros(T)  # noqa: E731
        return cls(T, np.ones(T), np.full(T, np.nan), z(), np.ones(T), z(), z(), [], z(), z(), z(),
                   np.ones(T), z(), z(), z(), np.zeros(T + 1), z(), z())


def _window(T: int, start: int, end: int | None) -> slice:
    s = max(0, int(start))
    e = T if end is None else min(T, int(end))
    return slice(s, max(s, e))


def _years(T: int, start: int) -> np.ndarray:
    return np.maximum(np.arange(T) - start, 0) / 12


def _annuity(principal: float, rate: float, months: int) -> float:
    r = rate / 12
    if months <= 0:
        return principal
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** -months)


def _add_loan(c: Compiled, ln: Loan) -> None:
    T = c.T
    if not 0 <= ln.month < T or ln.principal <= 0:
        return
    rate, remaining = ln.rate, ln.term
    pay = _annuity(ln.principal, rate, remaining)
    bal = ln.principal
    if ln.disburse:
        c.loan_disb[ln.month] += ln.principal
    c.loan_L[ln.month + 1] += bal
    for t in range(ln.month + 1, T):
        if ln.rate_step_month is not None and t == ln.rate_step_month:
            rate = ln.new_rate
            pay = _annuity(bal, rate, max(remaining, 1))
        bal *= 1 + rate / 12
        p = min(pay, bal)
        bal -= p
        remaining -= 1
        c.loan_pay[t] += p
        c.loan_L[t + 1] += bal


def compile_plan(plan: Plan | None, T: int) -> Compiled:
    c = Compiled.empty(T)
    if plan is None:
        return c
    for iv in plan.interventions:
        if isinstance(iv, Income):
            w = _window(T, iv.start, iv.end)
            if iv.set is not None:
                c.inc_set[w] = iv.set
            c.inc_factor[w] *= iv.factor
            c.inc_add[w] += iv.add
        elif isinstance(iv, Expense):
            w = _window(T, iv.start, iv.end)
            y = _years(T, iv.start)[w]
            c.exp_factor[w] *= iv.factor * (1 + iv.factor_growth) ** y
            c.exp_add[w] += iv.add * (1 + iv.add_growth) ** y
        elif isinstance(iv, OneOff):
            if 0 <= iv.month < T:
                if iv.prob >= 1:
                    c.oneoff[iv.month] += iv.amount
                else:
                    c.stoch_oneoffs.append((iv.month, iv.amount, iv.prob))
        elif isinstance(iv, Loan):
            _add_loan(c, iv)
        elif isinstance(iv, Property):
            if 0 <= iv.month < T:
                c.oneoff[iv.month] -= iv.price * (iv.down + iv.fees)
                c.prop_buy[iv.month] += iv.price
                w = _window(T, iv.month + 1, None)
                c.exp_add[w] += iv.price * iv.maintenance / 12 - iv.rent_saved
                _add_loan(c, Loan(iv.month, iv.price * (1 - iv.down), iv.rate, iv.term, disburse=False,
                                  rate_step_month=iv.rate_step_month, new_rate=iv.new_rate))
        elif isinstance(iv, DepotShock):
            if 0 <= iv.month < T:
                c.depot_shock[iv.month] = (1 + c.depot_shock[iv.month]) * (1 + iv.ret) - 1
        elif isinstance(iv, PropertyShock):
            if 0 <= iv.month < T:
                c.prop_shock[iv.month] = (1 + c.prop_shock[iv.month]) * (1 + iv.ret) - 1
        elif isinstance(iv, DepotDrift):
            c.mu_add[_window(T, iv.start, iv.end)] += iv.add
        elif isinstance(iv, Inflation):
            c.infl_add[_window(T, iv.start, iv.end)] += iv.add
        elif isinstance(iv, Invest):
            c.invest_amt[_window(T, iv.start, iv.end)] += iv.amount
        elif isinstance(iv, JobRisk):
            c.hz_mult[_window(T, iv.start, iv.end)] *= iv.mult
        else:
            raise TypeError(f"Unbekannte Intervention: {iv!r}")
    return c
