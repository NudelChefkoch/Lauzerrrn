"""Ist-Zustand: die Startwerte, die der Spieler zu Beginn selbst angibt, als ``Person`` für die Engine.

Zu Beginn wird nicht mehr nur ein synthetisches Profil gewählt, sondern der aktuelle Stand abgefragt
(Alter, Situation, Einkommen, Ausgaben, Miete, Konto, Anlagen, Schulden). Ein Beispielprofil aus den
Challenge-Daten kann das Formular vorbefüllen (``basis``); bleiben dessen Zahlen unverändert, wird die
kalibrierte Person 1:1 verwendet.

Was nicht abgefragt wird, kommt aus den Gruppenwerten der Kalibrierung (Annahmen):
* Schwankung ``sigma``: Median der Statusgruppe, skaliert mit Einkommen / Gruppeneinkommen (0.5–2)
* Unsicherheit ``mu_se``: wie ein Jahr eigene Daten (sigma / sqrt(12))
* Schuldzins: 5 % p.a., falls Schulden angegeben
* Ziel: Notgroschen von 3 Monatsausgaben in 3 Jahren
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from .calibration import Calibration, Person
from .config import OTHER, STATUS_TO_STATE

# Situationen, die das Start-Formular anbietet (Schlüssel = employment_status der Challenge-Daten)
STATUS_OPTIONS = {"student": "in Ausbildung", "employed": "angestellt", "part_time": "Teilzeit",
                  "self_employed": "selbstständig", "unemployed": "ohne Job"}
FIELDS = ("age", "status", "income", "expenses", "rent", "cash", "portfolio", "debt")
DEFAULT_DEBT_RATE = 0.05
AGE_MIN, AGE_MAX = 15, 70


def _num(v, default: float = 0.0, lo: float = 0.0, hi: float = 1e8) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return float(np.clip(x, lo, hi)) if np.isfinite(x) else default


def ist_from_person(p: Person) -> dict:
    """Formularwerte eines (Beispiel-)Profils – zum Vorbefüllen des Start-Formulars."""
    return {"basis": p.profile_id, "age": p.age, "status": p.status if p.status in STATUS_OPTIONS else "employed",
            "income": round(p.income), "expenses": round(p.expenses), "rent": round(p.rent),
            "cash": round(p.cash), "portfolio": round(p.portfolio), "debt": round(p.debt)}


def clean_ist(ist: dict | None) -> dict:
    """Plausible, begrenzte Werte (fehlende Angaben werden 0 bzw. Standardwerte)."""
    ist = ist if isinstance(ist, dict) else {}
    status = ist.get("status") if ist.get("status") in STATUS_OPTIONS else "employed"
    income = _num(ist.get("income"), 0.0, 0.0, 1e6)
    expenses = _num(ist.get("expenses"), 0.0, 0.0, 1e6)
    rent = min(_num(ist.get("rent"), 0.0, 0.0, 1e6), expenses) if expenses else _num(ist.get("rent"), 0.0, 0.0, 1e6)
    return {"basis": str(ist.get("basis") or "") or None,
            "age": int(round(_num(ist.get("age"), 20, AGE_MIN, AGE_MAX))), "status": status,
            "income": income, "expenses": max(expenses, rent), "rent": rent,
            "cash": _num(ist.get("cash"), 0.0, 0.0, 1e9), "portfolio": _num(ist.get("portfolio"), 0.0, 0.0, 1e9),
            "debt": _num(ist.get("debt"), 0.0, 0.0, 1e9)}


def _same(a: dict, b: dict) -> bool:
    return all(a[k] == b[k] if k == "status" else abs(float(a[k]) - float(b[k])) < 1.0 for k in FIELDS)


def person_from_ist(calib: Calibration, ist: dict | None, name: str | None = None) -> Person:
    """Baue die Person für die Simulation aus dem abgefragten Ist-Zustand."""
    v = clean_ist(ist)
    base = calib.persons.get(v["basis"]) if v["basis"] else None
    if base is not None and _same(v, clean_ist(ist_from_person(base))):
        return replace(base, name=name or base.name)          # unverändertes Beispiel: kalibrierte Werte

    state = STATUS_TO_STATE.get(v["status"], OTHER)
    sp = calib.states[state]
    if base is not None and base.state == state and np.isfinite(base.sigma):
        sigma = base.sigma                                      # Schwankung des Beispiels übernehmen
    else:
        scale = v["income"] / sp.income if sp.income > 0 and v["income"] > 0 else 1.0
        sigma = sp.sigma * float(np.clip(scale, 0.5, 2.0))
    mu = v["income"] - v["expenses"]
    goal = (("Emergency savings", round(3 * v["expenses"], -2), 36),) if v["expenses"] > 0 else ()
    return Person(profile_id="IST", name=name or "Du", age=v["age"], status=v["status"], state=state,
                  income=v["income"], rent=v["rent"], expenses=v["expenses"], mu=mu,
                  mu_se=float(sigma / np.sqrt(12)), sigma=float(sigma), cash=v["cash"], portfolio=v["portfolio"],
                  debt=v["debt"], debt_rate=DEFAULT_DEBT_RATE if v["debt"] > 0 else 0.0, goals=goal)
