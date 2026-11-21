"""Markov-Regime für den Dezember (Bonus / 13. Monatslohn).

Zustände je Dezember:  B = 0 (kein Bonus)  |  B = 1 (Bonus)
    P = [[1 - p01, p01],
         [p10,     1 - p10]]

Klassifikation eines beobachteten Dezembers:
    z = (X_dez - m_hat) / sigma_hat  >  3   ->  B = 1
(gleiche 3-sigma-Schwelle wie für Sprünge; ein normaler Monat liegt fast nie darüber).

Schätzung je Beschäftigungsgruppe aus den Übergängen Dez 2025 -> Dez 2026, mit
Laplace-Glättung (Beta(1,1)-Prior), weil manche Gruppen kaum Bonusfälle haben.
Bonushöhe: Anteil am Monatseinkommen, Mittel und Std der Bonus-Dezember je Gruppe
(Fallback: alle Gruppen gepoolt, wenn < MIN_BONUS_OBS Beobachtungen).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

Z_THRESHOLD = 3.0
MIN_BONUS_OBS = 5
INCOME_FLOOR = 500.0


@dataclass
class RegimeParams:
    p01: float            # P(Bonus nächstes Jahr | kein Bonus)
    p10: float            # P(kein Bonus nächstes Jahr | Bonus)
    bonus_ratio_mean: float
    bonus_ratio_sd: float
    n_transitions: int
    n_bonus_obs: int
    persistence_p: float  # Fisher-Test: hängt B_2026 von B_2025 ab?

    @property
    def stationary_bonus(self) -> float:
        s = self.p01 + self.p10
        return self.p01 / s if s > 0 else 0.0

    @property
    def matrix(self) -> np.ndarray:
        return np.array([[1 - self.p01, self.p01], [self.p10, 1 - self.p10]])


def classify_decembers(cash: pd.DataFrame, est: pd.DataFrame) -> pd.DataFrame:
    """Gibt je Profil und Jahr den Dezember-Zustand B und die Bonusquote zurück."""
    d = cash[cash["month"].str.endswith("-12")].copy()
    d["year"] = d["month"].str[:4].astype(int)
    d = d.join(est[["m_chf_month", "sigma_C_chf_month", "employment_status",
                    "reference_monthly_net_income_chf"]], on="profile_id")
    exc = d["net_transactions_chf"] - d["m_chf_month"]
    d["z"] = exc / d["sigma_C_chf_month"].replace(0, np.nan)
    d["B"] = (d["z"] > Z_THRESHOLD).astype(int)
    d["bonus_ratio"] = exc / d["reference_monthly_net_income_chf"].clip(lower=INCOME_FLOOR)
    return d[["profile_id", "year", "employment_status", "B", "z", "bonus_ratio"]]


def estimate_regimes(dec: pd.DataFrame) -> dict[str, RegimeParams]:
    years = sorted(dec["year"].unique())
    pooled_bonus = dec.loc[dec.B == 1, "bonus_ratio"]

    out: dict[str, RegimeParams] = {}
    for grp, g in dec.groupby("employment_status"):
        w = g.pivot(index="profile_id", columns="year", values="B")
        n00 = n01 = n10 = n11 = 0
        for y0, y1 in zip(years[:-1], years[1:]):
            a, b = w[y0], w[y1]
            n00 += int(((a == 0) & (b == 0)).sum())
            n01 += int(((a == 0) & (b == 1)).sum())
            n10 += int(((a == 1) & (b == 0)).sum())
            n11 += int(((a == 1) & (b == 1)).sum())
        # Laplace-Glättung
        p01 = (n01 + 1) / (n00 + n01 + 2)
        p10 = (n10 + 1) / (n10 + n11 + 2)
        persistence_p = float(stats.fisher_exact([[n00, n01], [n10, n11]]).pvalue)

        bonus = g.loc[g.B == 1, "bonus_ratio"]
        src = bonus if len(bonus) >= MIN_BONUS_OBS else pooled_bonus
        out[grp] = RegimeParams(
            p01=p01,
            p10=p10,
            bonus_ratio_mean=float(src.mean()),
            bonus_ratio_sd=float(src.std(ddof=1)),
            n_transitions=n00 + n01 + n10 + n11,
            n_bonus_obs=len(bonus),
            persistence_p=persistence_p,
        )
    return out


def regime_table(regimes: dict[str, RegimeParams]) -> pd.DataFrame:
    return pd.DataFrame({
        g: {
            "P(N->B)": r.p01,
            "P(B->B)": 1 - r.p10,
            "pi(Bonus)": r.stationary_bonus,
            "Bonus/Einkommen": r.bonus_ratio_mean,
            "Bonus sd": r.bonus_ratio_sd,
            "n Übergänge": r.n_transitions,
            "n Bonus": r.n_bonus_obs,
            "Persistenz p": r.persistence_p,
        }
        for g, r in regimes.items()
    }).T
