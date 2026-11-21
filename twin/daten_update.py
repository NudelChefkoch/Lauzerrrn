"""Später entstandene Daten einlesen und die Aussagen des Zwillings aktualisieren.

Noch nirgends aufgerufen – Einstiegspunkt für später: :func:`aktualisiere_aus_daten`
(bzw. ``GameSession.aktualisiere_mit_daten``).

Eingabe: CSV-Pfad oder DataFrame mit einer Zeile pro Monat, im Format von ``synthetic-cash-balances.csv``.
Pflicht:   ``month`` (YYYY-MM), ``net_transactions_chf``
Optional:  ``profile_id`` (wird gefiltert), ``closing_cash_chf`` (Kontostand Monatsende),
           ``portfolio_chf``, ``debt_chf``, ``income_chf`` (Netto-Einkommen), ``employment_status``

Vorgehen (gleiches Modell wie ``calibration.py``: X = mu + a_{s,m} + sigma * k_{s,m} * eps):
1. Saisoneffekt der Statusgruppe abziehen.
2. ``mu`` bayesianisch nachführen: bisheriges mu (Unsicherheit mu_se) als Prior, jeder neue Monat mit
   Varianz (sigma * k_m)^2 gewichtet -> Posterior-mu und kleineres mu_se.
3. ``sigma`` gepoolt: alte Schätzung mit dem Gewicht ihrer bisherigen Datenmenge, neue Residuen dazu.
4. Stand (Konto, Portfolio, Schulden, Alter, Ziele) auf den letzten Datenmonat setzen.
5. Simulation mit alter und neuer Person -> Kennzahlen und lesbare Aussagen (alt -> neu).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from .calibration import Calibration, Person, calibrate
from .config import Assumptions, OTHER, STATUS_TO_STATE
from .engine import simulate

GOAL_DE = {"Emergency savings": "Notgroschen", "Career transition": "Polster für den Jobwechsel",
           "Education flexibility": "Bildungsreserve", "Housing deposit": "Eigenkapital fürs Zuhause",
           "Long-term financial resilience": "Langfristige Reserve", "Retirement reserve": "Altersvorsorge"}
_ALIASES = {"portfolio_chf": ("portfolio_chf", "portfolio_value_chf", "investment_portfolio_chf"),
            "debt_chf": ("debt_chf", "debt_principal_chf", "liabilities_chf"),
            "income_chf": ("income_chf", "monthly_net_income_chf", "net_income_chf")}


@dataclass(frozen=True)
class Aktualisierung:
    person: Person            # nachkalibriert, Stand = Ende des letzten Datenmonats
    vorher: dict              # Kennzahlen mit der alten Person
    nachher: dict             # Kennzahlen mit der neuen Person
    aussagen: list[str]       # lesbare Aussagen "alt -> neu"
    ist: dict                 # neuer Ist-Zustand (Formularwerte, siehe ist_zustand.py)
    monate: int               # Anzahl eingelesener Monate


# ---------------------------------------------------------------- 1. einlesen
def lese_neue_daten(quelle: str | Path | pd.DataFrame, profile_id: str | None = None) -> pd.DataFrame:
    """CSV/DataFrame einlesen, prüfen, nach Monat sortieren; optional auf ``profile_id`` filtern."""
    df = quelle.copy() if isinstance(quelle, pd.DataFrame) else pd.read_csv(quelle)
    missing = {"month", "net_transactions_chf"} - set(df.columns)
    if missing:
        raise ValueError(f"Spalten fehlen: {sorted(missing)}")
    for name, alts in _ALIASES.items():
        for a in alts:
            if a in df.columns and name not in df.columns:
                df = df.rename(columns={a: name})
    if "profile_id" in df.columns:
        ids = df["profile_id"].dropna().unique()
        if profile_id is not None and profile_id in ids:
            df = df[df["profile_id"] == profile_id]
        elif len(ids) > 1:
            raise ValueError(f"Daten enthalten mehrere Profile {list(ids)[:5]} – bitte profile_id angeben")
    df = df.dropna(subset=["net_transactions_chf"])
    df["month"] = df["month"].astype(str).str[:7]
    df["m"] = pd.to_datetime(df["month"] + "-01", errors="raise").dt.month
    df = df.sort_values("month").drop_duplicates("month", keep="last").reset_index(drop=True)
    if df.empty:
        raise ValueError("keine neuen Monatsdaten gefunden")
    return df


# ---------------------------------------------------------------- 2.–4. nachkalibrieren
def nachkalibrieren(person: Person, df: pd.DataFrame, calib: Calibration) -> Person:
    """Neue Person mit aktualisiertem mu/sigma und dem Stand am Ende der Daten."""
    status = str(df["employment_status"].iloc[-1]) if "employment_status" in df.columns else person.status
    state = STATUS_TO_STATE.get(status, person.state if status == person.status else OTHER)
    sp = calib.states[state]
    m = df["m"].to_numpy() - 1
    x = df["net_transactions_chf"].to_numpy(dtype=float) - sp.seasonal[m]
    mult = np.where(np.isfinite(sp.sigma_mult[m]) & (sp.sigma_mult[m] > 0), sp.sigma_mult[m], 1.0)

    sigma0 = person.sigma if np.isfinite(person.sigma) and person.sigma > 0 else sp.sigma
    se0 = person.mu_se if np.isfinite(person.mu_se) and person.mu_se > 0 else sigma0 / np.sqrt(12)
    # ein Statuswechsel macht das alte mu wenig aussagekräftig: Prior stark aufweichen
    if state != person.state:
        se0 = max(se0, 3 * sigma0)

    var = (sigma0 * mult) ** 2
    prec = 1 / se0 ** 2 + np.sum(1 / var)
    mu = float((person.mu / se0 ** 2 + np.sum(x / var)) / prec)
    mu_se = float(np.sqrt(1 / prec))

    n0 = float(np.clip((sigma0 / se0) ** 2, 6, 120))      # Datenmenge hinter der alten sigma-Schätzung
    r = (x - mu) / mult
    sigma = float(np.sqrt((n0 * sigma0 ** 2 + np.sum(r ** 2)) / (n0 + len(r))))

    last = df.iloc[-1]
    income = float(df["income_chf"].tail(3).mean()) if "income_chf" in df.columns else person.income
    cash = float(last["closing_cash_chf"]) if "closing_cash_chf" in df.columns and pd.notna(last["closing_cash_chf"]) \
        else person.cash + float(df["net_transactions_chf"].sum())
    portfolio = float(last["portfolio_chf"]) if "portfolio_chf" in df.columns and pd.notna(last["portfolio_chf"]) \
        else person.portfolio
    debt = float(last["debt_chf"]) if "debt_chf" in df.columns and pd.notna(last["debt_chf"]) else person.debt
    n = len(df)
    goals = tuple((g, t, mo - n) for g, t, mo in person.goals if mo - n > 0)
    return replace(person, status=status, state=state, income=income, mu=mu, mu_se=mu_se, sigma=sigma,
                   expenses=max(income - mu, person.rent), cash=cash, portfolio=portfolio, debt=debt,
                   age=person.age + n // 12, goals=goals)


# ---------------------------------------------------------------- 5. Aussagen
def kennzahlen(person: Person, calib: Calibration, assumptions: Assumptions | None = None, years: int = 15,
               n_paths: int = 2000, seed: int = 0) -> dict:
    """Die Zahlen, auf denen die Aussagen des Zwillings beruhen."""
    res = simulate(person, [], years, assumptions or Assumptions(), n_paths, seed, calib=calib)
    mt = res.metrics
    return {"typischer_monat": person.mu, "schwankung": person.sigma, "netto_jetzt": person.cash + person.portfolio - person.debt,
            "notgroschen_monate": person.cash / person.expenses if person.expenses > 0 else None,
            "median_ende": mt["median_net_worth_end"], "p5_ende": mt["p5_net_worth_end"],
            "p95_ende": mt["p95_net_worth_end"], "p_kredit": mt["p_ever_credit"],
            "p_minus_ende": mt["p_negative_net_worth_end"], "jahre": years, "alter_ende": person.age + years,
            "ziele": {g["goal"]: g["p_reached"] for g in res.goals}}


def _chf(v: float) -> str:
    return ("CHF −" if v < -0.5 else "CHF ") + f"{abs(v):,.0f}".replace(",", "'")


def _pct(v: float) -> str:
    return f"{100 * v:.0f} %"


def _trend(old: float, new: float, good_up: bool = True, tol: float = 1e-9) -> str:
    if abs(new - old) <= tol * max(1.0, abs(old)):
        return "unverändert"
    return "besser" if (new > old) == good_up else "schlechter"


def formuliere_aussagen(vorher: dict, nachher: dict, monate: int) -> list[str]:
    """Kennzahlen alt/neu -> kurze, lesbare Aussagen."""
    a, b = vorher, nachher
    out = [f"Typischer Monat: {_chf(a['typischer_monat'])} → {_chf(b['typischer_monat'])} "
           f"({_trend(a['typischer_monat'], b['typischer_monat'])}, aus {monate} neuen Monaten)",
           f"Schwankung pro Monat: {_chf(a['schwankung'])} → {_chf(b['schwankung'])}",
           f"Nettovermögen heute: {_chf(a['netto_jetzt'])} → {_chf(b['netto_jetzt'])}",
           f"Vermögen mit {b['alter_ende']} (Median): {_chf(a['median_ende'])} → {_chf(b['median_ende'])} "
           f"({_trend(a['median_ende'], b['median_ende'], tol=0.005)})",
           f"Spanne p5–p95: {_chf(b['p5_ende'])} bis {_chf(b['p95_ende'])}",
           f"Wahrscheinlichkeit, einen Kredit zu brauchen: {_pct(a['p_kredit'])} → {_pct(b['p_kredit'])} "
           f"({_trend(a['p_kredit'], b['p_kredit'], good_up=False, tol=0.01)})"]
    if a["notgroschen_monate"] is not None and b["notgroschen_monate"] is not None:
        out.append(f"Notgroschen: {a['notgroschen_monate']:.1f} → {b['notgroschen_monate']:.1f} Monatsausgaben")
    for goal, p in b["ziele"].items():
        before = a["ziele"].get(goal)
        name = GOAL_DE.get(goal, goal)
        out.append(f"Ziel {name}: {_pct(before)} → {_pct(p)} Chance" if before is not None
                   else f"Ziel {name}: {_pct(p)} Chance")
    return out


def aktualisiere_aus_daten(person: Person, quelle: str | Path | pd.DataFrame, *, calib: Calibration | None = None,
                           assumptions: Assumptions | None = None, years: int = 15, n_paths: int = 2000,
                           seed: int = 0, profile_id: str | None = None) -> Aktualisierung:
    """Neue Monatsdaten einlesen, Person nachkalibrieren, Aussagen alt -> neu neu berechnen."""
    calib = calib or calibrate()
    df = lese_neue_daten(quelle, profile_id if profile_id is not None else person.profile_id)
    neu = nachkalibrieren(person, df, calib)
    vorher = kennzahlen(person, calib, assumptions, years, n_paths, seed)
    nachher = kennzahlen(neu, calib, assumptions, years, n_paths, seed)
    ist = {"basis": None, "age": neu.age, "status": neu.status, "income": round(neu.income),
           "expenses": round(neu.expenses), "rent": round(neu.rent), "cash": round(neu.cash),
           "portfolio": round(neu.portfolio), "debt": round(neu.debt)}
    return Aktualisierung(neu, vorher, nachher, formuliere_aussagen(vorher, nachher, len(df)), ist, len(df))
