"""Szenario-Bibliothek: alle 120 Szenarien aus scenario-catalog.csv als Baseline -> Intervention.

Jedes Szenario hat einstellbare Parameter (Defaults = illustrative Annahmen, keine Prognosen;
Ausnahme S001-Studiengebühr aus scenario-assumptions.csv) und baut daraus einen Plan
aus Bausteinen (interventions.py). Ohne eigene Baseline ist die Baseline der Status quo
(die Simulation mit den aktuellen Einstellungen). Beträge, die vom Profil abhängen
(Einkommen, Miete, Vermögen), werden beim Profilwechsel neu vorbelegt.

Zeit: s = Startmonat des Szenarios (ab Jan 2025), Dauern in Monaten.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from types import SimpleNamespace
from typing import Callable

import numpy as np
import pandas as pd

from estimate_params import DEFAULT_DATA
from interventions import (DepotDrift, DepotShock, Expense, Income, Inflation, Invest, JobRisk,
                           Loan, OneOff, Plan, Property, PropertyShock, compile_plan)
from simulate import Model, SimConfig, SimResult, simulate_profile


@dataclass
class Param:
    default: float | Callable[[pd.Series], float]
    label: str
    unit: str = ""
    kind: str = "float"        # float | int | pct
    hi: float = 1e8
    lo: float = 0.0


@dataclass
class ScenarioDef:
    id: str
    params: dict[str, Param]
    build: Callable                       # (row, p, s, cfg) -> Plan
    baseline: Callable | None = None      # (row, p, s, cfg) -> Plan, sonst Status quo
    note: str = ""
    # aus dem Katalog:
    name: str = ""
    category: str = ""
    baseline_text: str = ""
    intervention_text: str = ""

    def defaults(self, row: pd.Series) -> dict:
        return {k: (v.default(row) if callable(v.default) else v.default) for k, v in self.params.items()}


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------
def inc(r) -> float:
    return max(float(r.reference_monthly_net_income_chf), 0.0)


def rent(r) -> float:
    return max(float(getattr(r, "reference_monthly_rent_chf", 1500.0)), 0.0)


def ret_month(r, cfg: SimConfig) -> int:
    return int(np.ceil(max(0.0, cfg.retirement_age - r.age_at_start) * 12))


def is_student(r) -> bool:
    return r.employment_status == "student"


def r100(x: float, step: float = 100) -> float:
    return float(round(x / step) * step)


@lru_cache(maxsize=1)
def _tuition_table() -> pd.Series:
    try:
        sa = pd.read_csv(DEFAULT_DATA / "scenario-assumptions.csv")
        t = sa[(sa.scenario_id == "S001") & (sa.parameter == "annual_tuition_chf")]
        return t.set_index("profile_id").value.astype(float)
    except (OSError, ValueError):
        return pd.Series(dtype=float)


def tuition(r) -> float:
    return float(_tuition_table().get(r.name, 8000.0))


def home_price(r) -> float:
    return r100(min(max(5 * 12 * inc(r), 400_000), 1_500_000), 10_000)


def monthly_saving(r, share=0.5) -> float:
    return r100(max(share * float(r.m_chf_month), 100))


P = Param
PCT = dict(kind="pct", hi=5.0, lo=-1.0)
MON = dict(kind="int", unit="Mt.", hi=600)
CHF = dict(unit="CHF", hi=1e8, lo=-1e8)
CHFM = dict(unit="CHF/Mt.", hi=1e6, lo=-1e6)


def plan(*ivs, cfg=None, row=None) -> Plan:
    return Plan(list(ivs), cfg or {}, row or {})


# ---------------------------------------------------------------------------
# Wiederverwendete Bausteine
# ---------------------------------------------------------------------------
def master_plan(r, p, s, cfg) -> Plan:
    """Vollzeit-Master: Studieneinkommen, Studiengebühren, danach Lohnprämie."""
    fees = [OneOff(s + 12 * k, -p.tuition) for k in range(int(np.ceil(p.months / 12)))]
    if is_student(r):
        return plan(*fees, Income(s, s + p.months, set=p.student_income),
                    cfg={"study_years_left": (s + p.months) / 12, "entry_income": cfg.entry_income * (1 + p.premium)})
    return plan(*fees, Income(s, s + p.months, set=p.student_income), Income(s + p.months, None, factor=1 + p.premium))


def start_work_plan(r, p, s, cfg) -> Plan:
    """Sofort arbeiten statt (weiter) studieren."""
    return plan(cfg={"study_years_left": s / 12}) if is_student(r) else plan()


def buy_home(r, p, s, cfg, **kw) -> Property:
    args = dict(month=s, price=p.price, down=p.down, rate=p.rate, rent_saved=p.rent_saved)
    args.update(kw)
    return Property(**args)


HOME = {
    "price": P(home_price, "Kaufpreis", **CHF),
    "down": P(0.20, "Eigenkapital", **PCT),
    "rate": P(0.02, "Hypothekarzins", **PCT),
    "rent_saved": P(rent, "Eingesparte Miete", **CHFM),
}


def startup_plan(r, p, s, cfg, bootstrap=None) -> Plan:
    m = p.bootstrap if bootstrap is None else bootstrap
    return plan(OneOff(s, -p.capital), Income(s, s + m, set=p.founder_income),
                Income(s + m, None, factor=p.later_factor),
                row={"sigma_C_chf_month": r.sigma_C_chf_month * p.vol_mult})


STARTUP = {
    "capital": P(30000, "Eigenkapital ins Startup", **CHF),
    "bootstrap": P(24, "Aufbauphase", **MON),
    "founder_income": P(1500, "Lohn in Aufbauphase", **CHFM),
    "later_factor": P(1.2, "Einkommen danach (× bisher)", hi=10),
    "vol_mult": P(3.0, "Einkommensschwankung ×", hi=20),
}

INVEST_M = {"amount": P(monthly_saving, "Sparplan", **CHFM)}


# ---------------------------------------------------------------------------
# Katalog (Parameter + Plan je Szenario)
# ---------------------------------------------------------------------------
D: dict[str, ScenarioDef] = {}


def S(id_, params=None, build=None, baseline=None, note=""):
    D[id_] = ScenarioDef(id_, params or {}, build, baseline, note)


# Education & skills
S("S001", {"months": P(24, "Studiendauer", **MON), "tuition": P(tuition, "Studiengebühr p.a.", **CHF),
           "student_income": P(1200, "Einkommen im Studium", **CHFM), "premium": P(0.10, "Lohnprämie danach", **PCT)},
  master_plan, start_work_plan, "Studiengebühr aus scenario-assumptions.csv")
S("S002", {"months": P(36, "Dauer", **MON), "share": P(0.6, "Pensum", **PCT), "tuition": P(4000, "Gebühr p.a.", **CHF),
           "premium": P(0.08, "Lohnprämie danach", **PCT)},
  lambda r, p, s, c: plan(*[OneOff(s + 12 * k, -p.tuition) for k in range(int(np.ceil(p.months / 12)))],
                          Income(s, s + p.months, factor=p.share), Income(s + p.months, None, factor=1 + p.premium)))
S("S003", {"grant": P(8000, "Stipendium p.a.", **CHF), "years": P(2, "Jahre", kind="int", hi=10)},
  lambda r, p, s, c: plan(*[OneOff(s + 12 * k, p.grant) for k in range(int(p.years))]))
S("S004", {"extra": P(2000, "Mehrkosten p.a.", **CHF), "years": P(2, "Jahre", kind="int", hi=10)},
  lambda r, p, s, c: plan(*[OneOff(s + 12 * k, -p.extra) for k in range(int(p.years))]))
S("S005", {"months": P(12, "Dauer", **MON), "intern_income": P(2500, "Praktikumslohn", **CHFM)},
  lambda r, p, s, c: plan(Income(s, s + p.months, set=p.intern_income),
                          cfg={"study_years_left": c.study_years_left + p.months / 12} if is_student(r) else None))
S("S006", {"cost": P(12000, "Bootcamp-Kosten", **CHF), "unpaid": P(0, "Unbezahlte Monate", **MON),
           "premium": P(0.10, "Lohnprämie danach", **PCT)},
  lambda r, p, s, c: plan(OneOff(s, -p.cost), Income(s, s + p.unpaid, factor=0.0),
                          Income(s + p.unpaid + 3, None, factor=1 + p.premium)))
S("S007", {"months": P(48, "Dauer", **MON), "phd_income": P(4200, "Doktorandenlohn", **CHFM),
           "premium": P(0.15, "Lohnprämie danach", **PCT)},
  lambda r, p, s, c: plan(Income(s, s + p.months, set=p.phd_income), Income(s + p.months, None, factor=1 + p.premium),
                          cfg={"study_years_left": s / 12} if is_student(r) else None))
S("S008", {"months": P(6, "Dauer", **MON), "extra": P(1500, "Mehrkosten", **CHFM)},
  lambda r, p, s, c: plan(Expense(s, s + p.months, add=p.extra)))
S("S009", {"amount": P(16000, "Darlehen", **CHF), "rate": P(0.03, "Zins", **PCT), "term": P(120, "Laufzeit", **MON)},
  lambda r, p, s, c: plan(Loan(s, p.amount, p.rate, int(p.term))),
  note="Baseline: Gebühren aus Ersparnissen (Status quo)")
S("S010", {"extra_months": P(12, "Verzögerung", **MON), "tuition": P(tuition, "Gebühr p.a.", **CHF)},
  lambda r, p, s, c: plan(OneOff(s + 12, -p.tuition),
                          cfg={"study_years_left": c.study_years_left + p.extra_months / 12} if is_student(r) else None)
  if is_student(r) else plan(OneOff(s, -p.tuition), Income(s, s + p.extra_months, set=1200)))

# Career & employment
S("S011", dict(D["S001"].params), start_work_plan, master_plan, "Umkehrung von S001: Baseline = Master")
S("S012", {"raise_": P(0.05, "Lohnerhöhung", **PCT)}, lambda r, p, s, c: plan(Income(s, None, factor=1 + p.raise_)))
S("S013", {"after": P(24, "Nach", **MON), "raise_": P(0.15, "Lohnerhöhung", **PCT)},
  lambda r, p, s, c: plan(Income(s + p.after, None, factor=1 + p.raise_)))
S("S014", {"months": P(6, "Dauer Lücke", **MON), "benefit": P(0.7, "Taggeld", **PCT)},
  lambda r, p, s, c: plan(Income(s, s + p.months, factor=p.benefit)))
S("S015", {"factor": P(1.2, "Umsatz × Lohn", hi=10), "costs": P(lambda r: r100(0.15 * inc(r)), "Zusatzkosten (AHV, Versich.)", **CHFM),
           "vol": P(2.0, "Einkommensschwankung ×", hi=20)},
  lambda r, p, s, c: plan(Income(s, None, factor=p.factor), Expense(s, None, add=p.costs),
                          row={"sigma_C_chf_month": r.sigma_C_chf_month * p.vol}))
S("S016", {"dip_months": P(24, "Übergangsphase", **MON), "dip": P(0.8, "Lohn in Übergang", **PCT),
           "later": P(1.1, "Lohn danach (×)", hi=10), "cost": P(5000, "Umschulung", **CHF)},
  lambda r, p, s, c: plan(OneOff(s, -p.cost), Income(s, s + p.dip_months, factor=p.dip),
                          Income(s + p.dip_months, None, factor=p.later)))
S("S017", {"share": P(0.8, "Pensum", **PCT)}, lambda r, p, s, c: plan(Income(s, None, factor=p.share)))
S("S018", {"cash_cut": P(0.85, "Barlohn (×)", **PCT), "payout": P(150000, "Equity-Wert bei Erfolg", **CHF),
           "prob": P(0.3, "Erfolgswahrscheinlichkeit", **PCT), "vest": P(48, "Vesting", **MON)},
  lambda r, p, s, c: plan(Income(s, None, factor=p.cash_cut), OneOff(s + p.vest, p.payout, prob=p.prob)))
S("S019", {"premium": P(0.05, "Lohnzuschlag", **PCT), "risk": P(5.0, "Jobverlust-Risiko ×", hi=100)},
  lambda r, p, s, c: plan(Income(s, None, factor=1 + p.premium), JobRisk(s, None, p.risk)))
S("S020", {"add": P(1200, "Nebeneinkommen", **CHFM)}, lambda r, p, s, c: plan(Income(s, None, add=p.add)))


# Relocation & geography
def move(income_f, expense_f, rent_add, cost):
    return {"income_f": P(income_f, "Einkommen (×)", hi=10), "expense_f": P(expense_f, "Ausgaben (×)", hi=10),
            "rent_add": P(rent_add, "Mehrmiete", **CHFM), "cost": P(cost, "Umzugskosten", **CHF)}


def move_plan(r, p, s, c):
    return plan(OneOff(s, -p.cost), Income(s, None, factor=p.income_f),
                Expense(s, None, factor=p.expense_f, add=p.rent_add))


S("S021", move(1.10, 1.0, 500, 5000), move_plan)
S("S022", move(1.05, 1.0, 400, 4000), move_plan)
S("S023", move(0.60, 0.65, 0, 8000), move_plan)
S("S024", move(1.00, 1.15, 0, 10000), move_plan)
S("S025", move(1.15, 1.10, 0, 12000), move_plan)
S("S026", move(1.00, 0.70, 150, 2000), move_plan, note="Mehrmiete = Admin/Steuerberatung")
S("S027", move(1.00, 1.10, 0, 8000), move_plan)
S("S028", {"fx_share": P(0.3, "Ausgaben in Fremdwährung", **PCT), "depr": P(0.15, "CHF-Abwertung", **PCT)},
  lambda r, p, s, c: plan(Expense(s, None, factor=1 + p.fx_share * p.depr)))
S("S029", {"fx_share": P(0.4, "Einkommen in Fremdwährung", **PCT), "fx_vol": P(0.10, "FX-Volatilität p.a.", **PCT)},
  lambda r, p, s, c: plan(row={"sigma_C_chf_month": float(np.hypot(r.sigma_C_chf_month,
                                                                     p.fx_share * p.fx_vol / np.sqrt(12) * inc(r)))}))
S("S030", {"cost": P(15000, "Umzugskosten", **CHF)}, lambda r, p, s, c: plan(OneOff(s, -p.cost)),
  baseline=lambda r, p, s, c: plan(OneOff(s, -5000)), note="Baseline: 5'000 CHF Umzugskosten")

# Housing & property
S("S031", {"add": P(lambda r: r100(0.6 * rent(r)), "Mehrmiete", **CHFM)}, lambda r, p, s, c: plan(Expense(s, None, add=p.add)))
S("S032", {"saving": P(lambda r: r100(0.4 * rent(r)), "Mietersparnis", **CHFM)},
  lambda r, p, s, c: plan(Expense(s, None, add=-p.saving)))
S("S033", dict(HOME), lambda r, p, s, c: plan(buy_home(r, p, s, c)), note="Kauf zum Startmonat")
S("S034", {**HOME, "down_high": P(0.35, "Eigenkapital hoch", **PCT)},
  lambda r, p, s, c: plan(buy_home(r, p, s, c, down=p.down_high)),
  baseline=lambda r, p, s, c: plan(buy_home(r, p, s, c)))
S("S035", {**HOME, "reset_after": P(60, "Zinsbindung", **MON), "new_rate": P(0.04, "Zins nach Reset", **PCT)},
  lambda r, p, s, c: plan(buy_home(r, p, s, c, rate_step_month=s + p.reset_after, new_rate=p.new_rate)),
  baseline=lambda r, p, s, c: plan(buy_home(r, p, s, c)))
S("S036", {"cost": P(40000, "Renovation", **CHF)}, lambda r, p, s, c: plan(OneOff(s, -p.cost)))
S("S037", {"growth": P(0.03, "Mietsteigerung über Inflation p.a.", **PCT)},
  lambda r, p, s, c: plan(Expense(s, None, add=rent(r), add_growth=p.growth), Expense(s, None, add=-rent(r))))
S("S038", {**HOME, "delay": P(60, "Verzögerung", **MON)},
  lambda r, p, s, c: plan(buy_home(r, p, s + p.delay, c)),
  baseline=lambda r, p, s, c: plan(buy_home(r, p, s, c)), note="Baseline: jetzt kaufen")
S("S039", {**HOME, "drop": P(-0.15, "Preisrückgang", kind="pct", lo=-1, hi=1), "when": P(12, "Nach", **MON)},
  lambda r, p, s, c: plan(buy_home(r, p, s, c), PropertyShock(s + p.when, p.drop)),
  baseline=lambda r, p, s, c: plan(buy_home(r, p, s, c)))
S("S040", {**HOME, "repair": P(30000, "Reparatur", **CHF), "when": P(36, "Nach", **MON)},
  lambda r, p, s, c: plan(buy_home(r, p, s, c), OneOff(s + p.when, -p.repair)),
  baseline=lambda r, p, s, c: plan(buy_home(r, p, s, c)))

# Spending & lifestyle
S("S041", {"cut": P(0.10, "Ausgabenkürzung", **PCT)}, lambda r, p, s, c: plan(Expense(s, None, factor=1 - p.cut)))
S("S042", {"price": P(30000, "Autopreis", **CHF), "running": P(520, "Laufende Kosten", **CHFM)},
  lambda r, p, s, c: plan(OneOff(s, -p.price), Expense(s, None, add=p.running)))
S("S043", {"sale": P(15000, "Verkaufserlös", **CHF), "saving": P(500, "Ersparnis", **CHFM)},
  lambda r, p, s, c: plan(OneOff(s, p.sale), Expense(s, None, add=-p.saving)))
S("S044", {"months": P(6, "Dauer", **MON), "travel": P(1000, "Reisekosten", **CHFM)},
  lambda r, p, s, c: plan(Income(s, s + p.months, factor=0.0), Expense(s, s + p.months, add=p.travel)))
S("S045", {"saving": P(80, "Ersparnis", **CHFM)}, lambda r, p, s, c: plan(Expense(s, None, add=-p.saving)))
S("S046", {"growth": P(0.01, "Ausgabenwachstum p.a.", **PCT)},
  lambda r, p, s, c: plan(Expense(s, None, factor_growth=p.growth)))
S("S047", {"price": P(8000, "Anschaffung", **CHF)}, lambda r, p, s, c: plan(OneOff(s, -p.price)))
S("S048", {"amount": P(10000, "Notfallausgabe", **CHF), "when": P(6, "Nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.when, -p.amount)))
S("S049", {"saving": P(lambda r: r100(0.3 * rent(r) + 300), "Ersparnis", **CHFM)},
  lambda r, p, s, c: plan(Expense(s, None, add=-p.saving)))
S("S050", {"extra": P(150, "Mehrkosten Energie", **CHFM), "months": P(24, "Dauer", **MON)},
  lambda r, p, s, c: plan(Expense(s, s + p.months, add=p.extra)))

# Savings & liquidity
S("S051", {"buffer": P(6.0, "Notgroschen (Monatsausgaben)", hi=60), "share": P(0.5, "Anlagequote darüber", **PCT)},
  lambda r, p, s, c: plan(cfg={"buffer_months": p.buffer, "invest_share": p.share}),
  baseline=lambda r, p, s, c: plan(cfg={"buffer_months": 0.0, "invest_share": p.share}),
  note="Trade-off Liquidität vs. Rendite: Baseline investiert ohne Reserve")
S("S052", dict(INVEST_M), lambda r, p, s, c: plan(Invest(s, None, p.amount)))
S("S053", {"cut": P(0.05, "Mehr sparen (Ausgaben −)", **PCT)}, lambda r, p, s, c: plan(Expense(s, None, factor=1 - p.cut)))
S("S054", {"target": P(10000, "Sparziel", **CHF), "when": P(24, "Kauf nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.when, -p.target)))
S("S055", {"share": P(lambda r: r100(0.3 * max(r.C0, 0), 1000), "Gesperrter Betrag", **CHF)},
  lambda r, p, s, c: plan(Invest(s, s + 1, p.share)), note="Gesperrtes Konto modelliert als Depot")
S("S056", {"rate": P(0.015, "Habenzins", **PCT)}, lambda r, p, s, c: plan(cfg={"r_cash": p.rate}),
  baseline=lambda r, p, s, c: plan(cfg={"r_cash": 0.0}))
S("S057", {"amount": P(50000, "Schenkung", **CHF), "when": P(12, "Nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.when, p.amount)))
S("S058", {"months": P(3, "Dauer", **MON)}, lambda r, p, s, c: plan(Income(s, s + p.months, factor=0.0)))
S("S059", {"amount": P(15000, "Dringende Ausgabe", **CHF), "when": P(3, "Nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.when, -p.amount)))
S("S060", {"goal1": P(20000, "Ziel 1", **CHF), "t1": P(36, "Ziel 1 nach", **MON),
           "goal2": P(30000, "Ziel 2", **CHF), "t2": P(72, "Ziel 2 nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.t1, -p.goal1), OneOff(s + p.t2, -p.goal2)),
  baseline=lambda r, p, s, c: plan(OneOff(s + p.t1, -p.goal1)))

# Investments & allocation
S("S061", dict(INVEST_M), lambda r, p, s, c: plan(Invest(s, None, p.amount)))
S("S062", {"mu": P(0.055, "Rendite", **PCT), "sigma": P(0.15, "Volatilität", **PCT)},
  lambda r, p, s, c: plan(cfg={"mu_I": p.mu, "sigma_I": p.sigma}))
S("S063", {"mu": P(0.03, "Rendite mit Bonds", **PCT), "sigma": P(0.06, "Volatilität mit Bonds", **PCT),
           "mu0": P(0.06, "Rendite nur Aktien", **PCT), "sigma0": P(0.16, "Volatilität nur Aktien", **PCT)},
  lambda r, p, s, c: plan(cfg={"mu_I": p.mu, "sigma_I": p.sigma}),
  baseline=lambda r, p, s, c: plan(cfg={"mu_I": p.mu0, "sigma_I": p.sigma0}))
S("S064", {"fee_high": P(0.012, "Gebühr alt", **PCT), "fee_low": P(0.002, "Gebühr neu", **PCT)},
  lambda r, p, s, c: plan(cfg={"mu_I": c.mu_I - p.fee_low}),
  baseline=lambda r, p, s, c: plan(cfg={"mu_I": c.mu_I - p.fee_high}))
S("S065", {"drop": P(-0.30, "Einbruch", kind="pct", lo=-1, hi=1), "when": P(12, "Nach", **MON)},
  lambda r, p, s, c: plan(DepotShock(s + p.when, p.drop)))
S("S066", {"drop": P(-0.30, "Einbruch", kind="pct", lo=-1, hi=1), "flat": P(36, "Seitwärtsphase", **MON)},
  lambda r, p, s, c: plan(DepotShock(s + 12, p.drop), DepotDrift(s + 13, s + 13 + p.flat, -c.mu_I)),
  baseline=lambda r, p, s, c: plan(DepotShock(s + 12, p.drop), DepotShock(s + 13, 1 / (1 + p.drop) - 1)))
S("S067", {**INVEST_M, "pause_from": P(12, "Pause ab", **MON), "pause": P(12, "Pausendauer", **MON)},
  lambda r, p, s, c: plan(Invest(s, s + p.pause_from, p.amount), Invest(s + p.pause_from + p.pause, None, p.amount)),
  baseline=lambda r, p, s, c: plan(Invest(s, None, p.amount)))
S("S068", {"sigma_mult": P(0.9, "Volatilität (×)", hi=2)},
  lambda r, p, s, c: plan(cfg={"sigma_I": c.sigma_I * p.sigma_mult}), note="Rebalancing grob als geringere Volatilität")
S("S069", {"sigma": P(0.30, "Volatilität Einzeltitel", **PCT)}, lambda r, p, s, c: plan(cfg={"sigma_I": p.sigma}))
S("S070", {"sigma_add": P(0.04, "Zusatz-Volatilität FX", **PCT), "drag": P(0.005, "Renditeabzug", **PCT)},
  lambda r, p, s, c: plan(cfg={"sigma_I": c.sigma_I + p.sigma_add, "mu_I": c.mu_I - p.drag}))

# Debt & credit
S("S071", {"debt": P(20000, "Studienschuld", **CHF), "rate": P(0.02, "Zins", **PCT), "term": P(120, "Laufzeit", **MON)},
  lambda r, p, s, c: plan(Loan(s, p.debt, p.rate, int(p.term), disburse=False)))
S("S072", {"balance": P(5000, "Saldo", **CHF), "rate": P(0.12, "Kartenzins", **PCT), "term": P(36, "Abzahlung", **MON)},
  lambda r, p, s, c: plan(OneOff(s, -p.balance), Loan(s, p.balance, p.rate, int(p.term))),
  baseline=lambda r, p, s, c: plan(OneOff(s, -p.balance)))
S("S073", {"cut": P(0.01, "Zinssenkung", **PCT)},
  lambda r, p, s, c: plan(row={"r_L_annual": max(r.r_L_annual - p.cut, 0.0)}), note="wirkt nur bei Profilen mit Kredit")
S("S074", {"term": P(36, "Neue Laufzeit", **MON)}, lambda r, p, s, c: plan(cfg={"loan_term_months": int(p.term)}),
  note="wirkt nur bei Profilen mit Kredit")
S("S075", {"add": P(0.02, "Zinsanstieg", **PCT)},
  lambda r, p, s, c: plan(row={"r_L_annual": r.r_L_annual + p.add} if r.L0 > 0 else {}, cfg={"r_overdraft": c.r_overdraft + p.add}))
S("S076", {"cut": P(0.005, "Zinsvorteil", **PCT), "term": P(84, "Laufzeit", **MON)},
  lambda r, p, s, c: plan(row={"r_L_annual": max(r.r_L_annual - p.cut, 0.0)}, cfg={"loan_term_months": int(p.term)}))
S("S077", {"amount": P(15000, "Ausgabe", **CHF), "rate": P(0.06, "Kreditzins", **PCT), "term": P(48, "Laufzeit", **MON)},
  lambda r, p, s, c: plan(OneOff(s, -p.amount), Loan(s, p.amount, p.rate, int(p.term))),
  baseline=lambda r, p, s, c: plan(OneOff(s, -p.amount)))
S("S078", {"fee": P(300, "Mahngebühr + Zins", **CHF)}, lambda r, p, s, c: plan(OneOff(s, -p.fee)))
S("S079", {"rate": P(0.12, "Strafzins bei Überzug", **PCT)}, lambda r, p, s, c: plan(cfg={"r_overdraft": p.rate}),
  note="Kreditlimit grob als höherer Überziehungszins")
S("S080", {"term": P(120, "Längere Laufzeit", **MON)}, lambda r, p, s, c: plan(cfg={"loan_term_months": int(p.term)}))

# Family & life events
S("S081", {"saving": P(lambda r: r100(0.35 * rent(r) + 400), "Ersparnis", **CHFM)},
  lambda r, p, s, c: plan(Expense(s, None, add=-p.saving)))
S("S082", {"cost": P(1800, "Kinderbetreuung", **CHFM), "months": P(48, "Dauer", **MON)},
  lambda r, p, s, c: plan(Expense(s, s + p.months, add=p.cost)))
S("S083", {"paid": P(4, "Bezahlt (80 %)", **MON), "unpaid": P(2, "Unbezahlt", **MON)},
  lambda r, p, s, c: plan(Income(s, s + p.paid, factor=0.8), Income(s + p.paid, s + p.paid + p.unpaid, factor=0.0)))
S("S084", {"amount": P(500, "Unterstützung", **CHFM)}, lambda r, p, s, c: plan(Expense(s, None, add=p.amount)))
S("S085", {"cost": P(25000, "Hochzeit", **CHF)}, lambda r, p, s, c: plan(OneOff(s, -p.cost)))
S("S086", {"share": P(0.6, "Pensum", **PCT), "months": P(24, "Dauer", **MON)},
  lambda r, p, s, c: plan(Income(s, s + p.months, factor=p.share)))
S("S087", {"split": P(0.5, "Vermögensteilung", **PCT), "legal": P(10000, "Anwaltskosten", **CHF),
           "extra_rent": P(lambda r: r100(0.5 * rent(r)), "Mehrkosten Haushalt", **CHFM)},
  lambda r, p, s, c: plan(OneOff(s, -p.split * max(r.C0, 0) - p.legal), DepotShock(s, -p.split),
                          Expense(s, None, add=p.extra_rent)))
S("S088", {"cost": P(1000, "Ausbildungskosten", **CHFM), "start": P(60, "Ab", **MON), "months": P(48, "Dauer", **MON)},
  lambda r, p, s, c: plan(Expense(s + p.start, s + p.start + p.months, add=p.cost)))
S("S089", {"deductible": P(2500, "Selbstbehalt", **CHF)}, lambda r, p, s, c: plan(OneOff(s, -p.deductible)))
S("S090", {"months": P(12, "Dauer", **MON), "cover": P(0.8, "Versicherte Leistung", **PCT)},
  lambda r, p, s, c: plan(Income(s, s + p.months, factor=p.cover)))

# Retirement & pensions
S("S091", {"age": P(60, "Rentenalter", hi=80), "rate": P(0.40, "Rente / Lohn", **PCT)},
  lambda r, p, s, c: plan(cfg={"retirement_age": p.age, "replacement_rate": p.rate}))
S("S092", {"age": P(67, "Rentenalter", hi=80), "rate": P(0.55, "Rente / Lohn", **PCT)},
  lambda r, p, s, c: plan(cfg={"retirement_age": p.age, "replacement_rate": p.rate}))
S("S093", {"amount": P(605, "Säule 3a", **CHFM), "tax": P(150, "Steuerersparnis", **CHFM)},
  lambda r, p, s, c: plan(Invest(s, ret_month(r, c), p.amount), Income(s, ret_month(r, c), add=p.tax)),
  note="3a als Depot; Steuerersparnis grob als Zusatzeinkommen")
S("S094", {"months": P(12, "Lücke", **MON), "rate_cut": P(0.02, "Rentenkürzung", **PCT)},
  lambda r, p, s, c: plan(Income(s, s + p.months, factor=0.0), cfg={"replacement_rate": c.replacement_rate - p.rate_cut}))
S("S095", {"factor": P(0.7, "Ausgaben im Ausland (×)", hi=5)},
  lambda r, p, s, c: plan(Expense(ret_month(r, c), None, factor=p.factor)))
S("S096", {"add": P(0.02, "Zusatzinflation", **PCT)}, lambda r, p, s, c: plan(Inflation(ret_month(r, c), None, p.add)))
S("S097", {"factor": P(0.95, "Ausgaben (×)", hi=2)},
  lambda r, p, s, c: plan(Expense(ret_month(r, c), None, factor=p.factor)), note="Dynamische Entnahme grob als Ausgabenkürzung")
S("S098", {"years": P(10, "Zusätzliche Jahre", kind="int", hi=50)},
  lambda r, p, s, c: plan(), note="Verlängert nur den Horizont (Δ = 0)")
S("S099", {"lump": P(lambda r: r100(30 * inc(r), 1000), "Kapitalbezug", **CHF), "rate": P(0.30, "Rente danach / Lohn", **PCT)},
  lambda r, p, s, c: plan() if r.employment_status == "retired"
  else plan(OneOff(ret_month(r, c), p.lump), cfg={"replacement_rate": p.rate}),
  note="nur vor der Pensionierung wählbar")
S("S100", {"extra": P(400, "Gesundheitskosten", **CHFM)},
  lambda r, p, s, c: plan(Expense(ret_month(r, c), None, add=p.extra)))

# Macroeconomic & systemic shocks
S("S101", {"add": P(0.04, "Zusatzinflation", **PCT), "months": P(24, "Dauer", **MON)},
  lambda r, p, s, c: plan(Inflation(s, s + p.months, p.add)))
S("S102", {"add": P(-0.02, "Inflation", kind="pct", lo=-1, hi=1), "months": P(24, "Dauer", **MON)},
  lambda r, p, s, c: plan(Inflation(s, s + p.months, p.add)))
S("S103", {"add": P(0.02, "Zinsanstieg", **PCT), "drop": P(-0.05, "Bewertungsrückgang Depot", kind="pct", lo=-1, hi=1)},
  lambda r, p, s, c: plan(DepotShock(s, p.drop),
                          cfg={"r_cash": c.r_cash + p.add / 2, "r_overdraft": c.r_overdraft + p.add},
                          row={"r_L_annual": r.r_L_annual + p.add} if r.L0 > 0 else None))
S("S104", {"months": P(24, "Dauer", **MON), "risk": P(3.0, "Jobverlust-Risiko ×", hi=100),
           "income": P(0.97, "Einkommen (×)", hi=2), "drop": P(-0.15, "Depot", kind="pct", lo=-1, hi=1)},
  lambda r, p, s, c: plan(JobRisk(s, s + p.months, p.risk), Income(s, s + p.months, factor=p.income), DepotShock(s, p.drop)))
S("S105", {"sigma_mult": P(1.3, "Cashflow-Schwankung ×", hi=10), "sigma_add": P(0.03, "Depot-Volatilität +", **PCT)},
  lambda r, p, s, c: plan(cfg={"sigma_I": c.sigma_I + p.sigma_add},
                          row={"sigma_C_chf_month": r.sigma_C_chf_month * p.sigma_mult}))
S("S106", {"extra": P(200, "Energiekosten", **CHFM), "months": P(24, "Dauer", **MON)},
  lambda r, p, s, c: plan(Expense(s, s + p.months, add=p.extra)))
S("S107", {"tax": P(0.04, "Mehrsteuer (vom Einkommen)", **PCT)},
  lambda r, p, s, c: plan(Income(s, None, factor=1 - p.tax)))
S("S108", {**HOME, "drop": P(-0.20, "Preisrückgang", kind="pct", lo=-1, hi=1), "when": P(24, "Nach", **MON)},
  lambda r, p, s, c: plan(buy_home(r, p, s, c), PropertyShock(s + p.when, p.drop)),
  baseline=lambda r, p, s, c: plan(buy_home(r, p, s, c)))
S("S109", {"friction": P(-0.03, "Verlust beim Verkauf", kind="pct", lo=-1, hi=1), "when": P(12, "Nach", **MON)},
  lambda r, p, s, c: plan(DepotShock(s + p.when, p.friction)))
S("S110", {"risk": P(5.0, "Jobverlust-Risiko ×", hi=100), "months": P(12, "Dauer", **MON),
           "drop": P(-0.30, "Depot", kind="pct", lo=-1, hi=1)},
  lambda r, p, s, c: plan(JobRisk(s, s + p.months, p.risk), DepotShock(s, p.drop)))

# Entrepreneurship & innovation
S("S111", dict(STARTUP), startup_plan)
S("S112", {"add": P(500, "Nebeneinnahmen", **CHFM), "start_cost": P(2000, "Startkosten", **CHF), "after": P(6, "Einnahmen ab", **MON)},
  lambda r, p, s, c: plan(OneOff(s, -p.start_cost), Income(s + p.after, None, add=p.add)))
S("S113", {**STARTUP, "funded_income": P(5000, "Lohn mit Funding", **CHFM)},
  lambda r, p, s, c: replace(startup_plan(r, p, s, c), interventions=[
      OneOff(s, -p.capital), Income(s, s + p.bootstrap, set=p.funded_income),
      Income(s + p.bootstrap, None, factor=p.later_factor)]),
  baseline=startup_plan)
S("S114", {**STARTUP, "fail_at": P(24, "Scheitern nach", **MON), "loss": P(20000, "Zusatzverlust", **CHF),
           "search": P(6, "Jobsuche", **MON)},
  lambda r, p, s, c: plan(OneOff(s, -p.capital), Income(s, s + p.fail_at, set=p.founder_income),
                          OneOff(s + p.fail_at, -p.loss), Income(s + p.fail_at, s + p.fail_at + p.search, factor=0.0),
                          Income(s + p.fail_at + p.search, None, factor=0.9)),
  baseline=startup_plan)
S("S115", {**STARTUP, "delay": P(12, "Verzögerung", **MON)},
  lambda r, p, s, c: startup_plan(r, p, s, c, bootstrap=p.bootstrap + p.delay), baseline=startup_plan)
S("S116", {**STARTUP, "cut": P(0.85, "Einkommen während Aufbau Team (×)", hi=2), "boost": P(1.1, "danach (×)", hi=10)},
  lambda r, p, s, c: replace(startup_plan(r, p, s, c), interventions=startup_plan(r, p, s, c).interventions + [
      Income(s + p.bootstrap, s + p.bootstrap + 24, factor=p.cut), Income(s + p.bootstrap + 24, None, factor=p.boost)]),
  baseline=startup_plan)
S("S117", {"exit": P(300000, "Exit-Erlös ohne Verwässerung", **CHF), "dilution": P(0.33, "Verwässerung", **PCT),
           "prob": P(0.25, "Exit-Wahrscheinlichkeit", **PCT), "when": P(60, "Exit nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.when, p.exit * (1 - p.dilution), prob=p.prob)),
  baseline=lambda r, p, s, c: plan(OneOff(s + p.when, p.exit, prob=p.prob)))
S("S118", {"factor": P(0.6, "Gründerlohn (×)", **PCT), "months": P(36, "Dauer", **MON)},
  lambda r, p, s, c: plan(Income(s, s + p.months, factor=p.factor)))
S("S119", {"amount": P(50000, "Geschäftskredit", **CHF), "rate": P(0.05, "Zins", **PCT), "term": P(60, "Laufzeit", **MON)},
  lambda r, p, s, c: plan(Loan(s, p.amount, p.rate, int(p.term)), OneOff(s, -p.amount)),
  note="Kredit wird ins Geschäft investiert (privat kein Gegenwert)")
S("S120", {"exit": P(300000, "Exit-Erlös", **CHF), "prob": P(0.25, "Wahrscheinlichkeit", **PCT), "when": P(60, "Nach", **MON)},
  lambda r, p, s, c: plan(OneOff(s + p.when, p.exit, prob=p.prob)))


def _load_catalog() -> None:
    try:
        cat = pd.read_csv(DEFAULT_DATA / "scenario-catalog.csv").set_index("id")
    except OSError:
        return
    for sid, d in D.items():
        if sid in cat.index:
            c = cat.loc[sid]
            d.name, d.category = c.scenario, c.category
            d.baseline_text, d.intervention_text = c.baseline, c.intervention


_load_catalog()
SCENARIOS = D


# ---------------------------------------------------------------------------
# Ausführen
# ---------------------------------------------------------------------------
def apply_plan(row: pd.Series, cfg: SimConfig, pl: Plan) -> tuple[pd.Series, SimConfig]:
    r = row.copy()
    for k, v in pl.row.items():
        r[k] = v
    r["NW0"] = r.C0 + r.I0 - r.L0
    return r, replace(cfg, **pl.cfg)


@dataclass
class Comparison:
    baseline: SimResult
    scenario: SimResult
    baseline_plan: Plan
    scenario_plan: Plan
    cfg: SimConfig

    def delta(self) -> np.ndarray:
        return self.scenario.NW - self.baseline.NW


def run_comparison(row: pd.Series, model: Model, cfg: SimConfig, sid: str,
                   params: dict | None = None, start: int = 0) -> Comparison:
    d = SCENARIOS[sid]
    p = SimpleNamespace(**{**d.defaults(row), **(params or {})})
    for k, v in d.params.items():
        if v.kind == "int":
            setattr(p, k, int(round(getattr(p, k))))
    if sid == "S098":
        cfg = replace(cfg, months=cfg.months + 12 * int(p.years))
    pl_i = d.build(row, p, start, cfg)
    pl_b = d.baseline(row, p, start, cfg) if d.baseline else Plan()
    out = []
    for pl in (pl_b, pl_i):
        r, c = apply_plan(row, cfg, pl)
        out.append(simulate_profile(r, model, c, plan=compile_plan(pl, c.months)))
    return Comparison(out[0], out[1], pl_b, pl_i, cfg)
