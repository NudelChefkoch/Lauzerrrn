"""Robuste Schätzung der SDE-Parameter pro Profil aus den LauzHack-Challenge-Daten.

Modell (siehe docs/parameter-schaetzung.md):
    NW(t) = C(t) + I(t) - L(t)
    dI = mu_I * I dt + sigma_I * I dW1                (GBM, Depot)
    dC = (r(C) * C + m + s_moy(t) [+ b*t]) dt + sigma_C dW2 (+ Sprünge)
    dL = (r_L * L - p) dt                             (Kredit)

Aus den Daten geschätzt: C0, I0, L0, r_L, m, sigma_C, s_k, Trend b, Sprungrate.
Nicht schätzbar (Annahmen, ASSUMPTIONS): mu_I, sigma_I, Habenzins, Überziehungszins,
Kreditlaufzeit, Korrelation rho.

Aufruf:
    venv/bin/python sde/estimate_params.py [--data DIR] [--out DATEI]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT.parent / "ai-financial-twin-lauzhack-2026" / "Data"
DEFAULT_OUT = ROOT / "output" / "sde_params.csv"

MAD_TO_SD = 1.4826  # Konsistenzfaktor: 1.4826 * MAD = sigma bei Normalverteilung
ALPHA = 0.05

# Parameter ohne Datenbasis -> explizite, illustrative Annahmen (keine Prognosen).
ASSUMPTIONS = {
    "mu_I_annual": 0.04,          # erwartete Depotrendite p.a. (illustrativ, wie Challenge-Docs)
    "sigma_I_annual": 0.10,       # Depotvolatilität p.a. (gemischtes Portfolio, illustrativ)
    "r_cash_annual": 0.005,       # Habenzins auf positives Cash
    "r_overdraft_annual": 0.08,   # Zins auf negatives Cash, falls kein Kredit-Zins vorhanden
    "loan_term_months": 60,       # angenommene Restlaufzeit -> Annuität, da Daten p = 0
    "rho_IC": 0.0,                # Korrelation Depot-/Cashflow-Schocks
}


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------
def load(data_dir: Path) -> dict[str, pd.DataFrame]:
    rd = lambda f: pd.read_csv(data_dir / f)  # noqa: E731
    cb = rd("synthetic-cash-balances.csv")
    cb["moy"] = cb["month"].str[-2:].astype(int)
    cb["t"] = cb.groupby("profile_id").cumcount()  # Monatsindex 0..23
    return {
        "profiles": rd("synthetic-profiles.csv").set_index("profile_id"),
        "assets": rd("synthetic-assets.csv"),
        "liabilities": rd("synthetic-liabilities.csv"),
        "cash": cb,
    }


def mad_sd(x: np.ndarray) -> float:
    return float(MAD_TO_SD * np.median(np.abs(x - np.median(x))))


# ---------------------------------------------------------------------------
# Schritt 1: Saisonmonate gepoolt erkennen
# ---------------------------------------------------------------------------
def detect_seasonal_months(cb: pd.DataFrame) -> tuple[list[int], pd.DataFrame]:
    """Robuste z-Werte je Profil; pro Kalendermonat Wilcoxon-Test über alle Profile.

    Saisonmonat, wenn Bonferroni-signifikant (alpha/12) UND |Median z| >= 0.25
    (Effektgrösse, damit bei n=1200 nicht jeder Mini-Effekt zählt).
    """
    g = cb.groupby("profile_id")["net_transactions_chf"]
    med = g.transform("median")
    scale = g.transform(lambda v: mad_sd(v.values)).replace(0, np.nan)
    z = ((cb["net_transactions_chf"] - med) / scale).rename("z")
    zm = pd.concat([cb[["profile_id", "moy"]], z], axis=1).groupby(["moy", "profile_id"]).z.mean()

    rows = []
    for moy, s in zm.groupby(level=0):
        s = s.dropna()
        p = stats.wilcoxon(s.values).pvalue
        rows.append({"moy": moy, "median_z": float(s.median()), "p_value": float(p)})
    table = pd.DataFrame(rows)
    table["seasonal"] = (table.p_value < ALPHA / 12) & (table.median_z.abs() >= 0.25)
    return table.loc[table.seasonal, "moy"].tolist(), table


# ---------------------------------------------------------------------------
# Schritt 2: Saisoneffekte gepoolt je Beschäftigungsgruppe (relativ zum Einkommen)
# ---------------------------------------------------------------------------
TRIM = 0.1  # getrimmtes Mittel: robust, aber erwartungstreu genug für Summen


def seasonal_ratios(cb, profiles, seasonal: list[int], est: pd.DataFrame
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Saisoneffekt je Gruppe und Monat, relativ zum Referenzeinkommen.

    s_k(Gruppe) = 10%-getrimmtes Mittel von (X - m_hat) / Einkommen.
    k_k(Gruppe) = Std der Rest-Abweichung (X - m_hat - s_k) / sigma_C  -> Streuungsfaktor
                  des Saisonmonats relativ zu einem normalen Monat.

    Pro Profil gibt es nur 2 Beobachtungen je Kalendermonat und die Jahr-zu-Jahr-
    Korrelation ist schwach -> Pooling statt Einzelschätzung.
    """
    d = cb[cb.moy.isin(seasonal)].join(est[["m_chf_month", "sigma_C_chf_month"]], on="profile_id")
    d = d.join(profiles[["employment_status", "reference_monthly_net_income_chf"]], on="profile_id")
    d["inc"] = d["reference_monthly_net_income_chf"].clip(lower=500)  # Schutz vor Mini-Einkommen
    d["ratio"] = (d["net_transactions_chf"] - d["m_chf_month"]) / d["inc"]
    keys = ["employment_status", "moy"]
    ratios = d.groupby(keys).ratio.agg(lambda v: stats.trim_mean(v, TRIM)).unstack("moy")
    d["s"] = [ratios.at[g, k] for g, k in zip(d.employment_status, d.moy)]
    d["zres"] = (d["net_transactions_chf"] - d["m_chf_month"] - d["s"] * d["inc"]) / d["sigma_C_chf_month"]
    k = d.groupby(keys).zres.agg(lambda v: stats.mstats.trimmed_std(v, (TRIM, TRIM))).unstack("moy")
    return ratios, k


# ---------------------------------------------------------------------------
# Schritt 3: Parameter + Kriterien pro Profil
# ---------------------------------------------------------------------------
def estimate_profile(x: np.ndarray, t: np.ndarray, is_season: np.ndarray) -> dict:
    """x: monatliche Netto-Cashflows, nur Nicht-Saisonmonate für m und sigma."""
    xn, tn = x[~is_season], t[~is_season]
    n = len(xn)

    m_median = float(np.median(xn))
    m_mean = float(np.mean(xn))
    sigma_mad = mad_sd(xn)
    sigma_std = float(np.std(xn, ddof=1))
    sigma_robust = sigma_mad if sigma_mad > 0 else sigma_std

    resid = xn - m_median
    # Zweistufig: (1) Sprünge robust erkennen: |Residuum| > 3 * MAD-sigma
    jumps = np.abs(resid) > 3 * sigma_robust
    n_years = len(x) / 12
    # (2) Diffusions-sigma = Std der Nicht-Sprung-Monate. Die MAD allein unterschätzt
    #     bei schweren Rändern die Varianz von Summen (Backtest: Bänder zu eng).
    core_x = xn[~jumps]
    sigma = float(np.std(core_x, ddof=1)) if len(core_x) >= 3 else sigma_std

    # Trend: Theil-Sen-Steigung, Signifikanz via Mann-Kendall (Kendall tau gegen Zeit)
    ts_slope = float(stats.theilslopes(xn, tn).slope)
    mk_p = float(stats.kendalltau(tn, xn).pvalue)

    # Unabhängigkeit der Inkremente: Lag-1-Autokorrelation (Ljung-Box-Grenze ~ 2/sqrt(n))
    ac1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if n > 2 else np.nan

    # Normalität der Residuen ohne Sprünge: Shapiro-Wilk (gut für kleine n)
    core = resid[~jumps]
    sw_p = float(stats.shapiro(core).pvalue) if len(core) >= 3 and np.ptp(core) > 0 else np.nan

    return {
        "n_months": len(x),
        "n_used": n,
        "m_chf_month": m_median,
        "m_mean_chf_month": m_mean,
        "sigma_C_chf_month": sigma,
        "sigma_C_mad_chf_month": sigma_robust,
        "sigma_C_std_chf_month": sigma_std,
        "trend_chf_month2": ts_slope,
        "trend_p": mk_p,
        "ac1": ac1,
        "shapiro_p": sw_p,
        "jump_count": int(jumps.sum()),
        "jump_rate_per_year": float(jumps.sum() / n_years),
        "jump_mean_chf": float(resid[jumps].mean()) if jumps.any() else 0.0,
        # --- Kriterien (True = PASS) ---
        "crit_data_ok": len(x) >= 24 and n >= 12,
        "crit_independent": bool(abs(ac1) < 2 / np.sqrt(n)) if n > 2 else False,
        "crit_no_trend": mk_p >= ALPHA,
        "crit_normal": bool(sw_p >= ALPHA) if not np.isnan(sw_p) else False,
        "crit_robust_eq_classic": abs(m_mean - m_median) < 0.5 * sigma,
        "crit_few_jumps": jumps.sum() <= 1,
    }


def annuity(principal: float, r_annual: float, months: int) -> float:
    r = r_annual / 12
    if principal <= 0:
        return 0.0
    return principal / months if r == 0 else principal * r / (1 - (1 + r) ** -months)


def estimate(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    d = load(data_dir)
    cb, profiles = d["cash"], d["profiles"]

    seasonal, season_table = detect_seasonal_months(cb)
    cb["is_season"] = cb.moy.isin(seasonal)

    rows = {}
    for pid, g in cb.groupby("profile_id"):
        g = g.sort_values("t")
        rows[pid] = estimate_profile(
            g.net_transactions_chf.values, g.t.values, g.is_season.values
        )
    est = pd.DataFrame.from_dict(rows, orient="index")
    est.index.name = "profile_id"

    ratios, season_k = seasonal_ratios(cb, profiles, seasonal, est)

    # Startzustand
    a = d["assets"].pivot_table(index="profile_id", columns="asset_type", values="value_chf", aggfunc="sum")
    l = d["liabilities"].groupby("profile_id").agg(
        L0=("opening_principal_chf", "sum"),
        r_L_annual=("annual_interest_rate", "mean"),
    )
    out = profiles[["display_name", "age_at_start", "employment_status", "household_type",
                    "reference_monthly_net_income_chf", "reference_monthly_rent_chf"]].copy()
    out["C0"] = a.get("cash", 0.0)
    out["I0"] = a.get("investment_portfolio", 0.0)
    out = out.join(l).fillna({"I0": 0.0, "L0": 0.0, "r_L_annual": 0.0})
    out["NW0"] = out.C0 + out.I0 - out.L0
    out = out.join(est)

    # Saisoneffekte in CHF: Gruppenquote * eigenes Einkommen
    inc = out.reference_monthly_net_income_chf.clip(lower=500)
    # plus Zusatzstreuung, damit Saisonmonat insgesamt k * sigma_C streut
    for k in seasonal:
        q = out.employment_status.map(ratios[k])
        out[f"s_{k:02d}_chf"] = q * inc
        kk = out.employment_status.map(season_k[k]).clip(lower=1.0)
        out[f"s_{k:02d}_extra_sd_chf"] = np.sqrt(kk**2 - 1) * out.sigma_C_chf_month

    # Trend nur verwenden, wenn signifikant
    out["trend_used_chf_month2"] = np.where(out.crit_no_trend, 0.0, out.trend_chf_month2)

    # Annahmen
    out["mu_I_annual"] = ASSUMPTIONS["mu_I_annual"]
    out["sigma_I_annual"] = ASSUMPTIONS["sigma_I_annual"]
    out["r_cash_annual"] = ASSUMPTIONS["r_cash_annual"]
    out["r_overdraft_annual"] = np.where(out.r_L_annual > 0, out.r_L_annual, ASSUMPTIONS["r_overdraft_annual"])
    out["loan_payment_chf_month"] = [
        annuity(L, r, ASSUMPTIONS["loan_term_months"]) for L, r in zip(out.L0, out.r_L_annual)
    ]
    out["rho_IC"] = ASSUMPTIONS["rho_IC"]

    # Jährliche Skalierung für SDE in Jahren.
    # Erwarteter Jahres-Cashflow = Diffusionsdrift + Saison + Sprung-Kompensator (lambda * E[J]).
    out["mu_C_annual_chf"] = (
        12 * out.m_chf_month
        + sum(out[f"s_{k:02d}_chf"] for k in seasonal)
        + out.jump_rate_per_year * out.jump_mean_chf
    )
    out["sigma_C_annual_chf"] = np.sqrt(12) * out.sigma_C_chf_month

    # Backtest: erwarteter Jahres-Cashflow vs. beobachteter Durchschnitt (2025/26).
    # PASS, wenn Abweichung < 2 Standardfehler des beobachteten Jahresmittels.
    obs = cb.groupby("profile_id").net_transactions_chf.agg(["sum", "std", "size"])
    years = obs["size"] / 12
    out["obs_annual_chf"] = obs["sum"] / years
    se = np.sqrt(12) * obs["std"] / np.sqrt(years)
    out["backtest_z"] = (out.mu_C_annual_chf - out.obs_annual_chf) / se
    out["crit_backtest"] = out.backtest_z.abs() < 2

    crit_cols = [c for c in out.columns if c.startswith("crit_")]
    out["crit_all_pass"] = out[crit_cols].all(axis=1)
    return out, season_table, ratios, season_k


def criteria_summary(out: pd.DataFrame) -> pd.DataFrame:
    labels = {
        "crit_data_ok": "Datenmenge ausreichend (24 Monate, >=12 ohne Saison)",
        "crit_independent": "Unabhängige Inkremente (|rho1| < 2/sqrt(n))",
        "crit_no_trend": "Kein Trend (Mann-Kendall p >= 0.05)",
        "crit_normal": "Residuen normal (Shapiro-Wilk p >= 0.05)",
        "crit_robust_eq_classic": "Median ~ Mittelwert (|diff| < 0.5 sigma)",
        "crit_few_jumps": "Max. 1 Sprung (|Res.| > 3 sigma)",
        "crit_backtest": "Backtest Jahres-Cashflow (|z| < 2)",
        "crit_all_pass": "Alle Kriterien erfüllt",
    }
    return pd.DataFrame({
        "Kriterium": [labels[c] for c in labels],
        "PASS-Quote": [f"{out[c].mean():.1%}" for c in labels],
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    out, season_table, ratios, _ = estimate(args.data)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.round(4).to_csv(args.out)

    pd.set_option("display.width", 160)
    print("Saisonmonate (gepoolt):")
    print(season_table.round(4).to_string(index=False))
    print("\nSaisonquoten (Anteil Monatseinkommen) je Gruppe:")
    print(ratios.round(3).to_string())
    print("\nKriterien über alle Profile:")
    print(criteria_summary(out).to_string(index=False))
    print(f"\n{len(out)} Profile -> {args.out}")


if __name__ == "__main__":
    main()
