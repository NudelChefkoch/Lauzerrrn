"""Monte-Carlo-Simulation des Net Worth: SDE + Dezember-Markov-Regime + Lebenszyklus.

Monatliche Diskretisierung (dt = 1/12), Start 2025-01-01 (Stichtag der Daten).

  Depot   I_{t+1} = I_t * exp((mu_I - sigma_I^2/2) dt + sigma_I sqrt(dt) Z1)     exakt (GBM)
  Kredit  L_{t+1} = max(0, L_t (1 + r_L dt) - p)                                   Annuität
  Cash    C_{t+1} = C_t (1 + r(C_t) dt) + X_{t+1} - p - Investition
          X = Einkommen(Zustand) - Ausgaben + Saison(Gruppe, Monat) + sigma_C Z2 + J
              + Dezember: B * Bonus * Einkommen,  B ~ Markov-Kette der Gruppe
  NW = C + I + H - L   (H = Immobilie, nur in Szenarien)

Lebenszyklus (Zustand je Pfad, Markov-Kette auf Monatsbasis):
  Studium  --(nach study_years_left)-->         Arbeit (Einstiegslohn)
  Arbeit   --(Jobverlust, Rate job_loss)-->     arbeitslos (benefit_rate * Lohn, max. benefit_months)
  arbeitslos --(Wiedereinstieg, Rate reemp)-->  Arbeit (letzter Lohn bzw. reemployment_income)
  alle     --(Alter >= retirement_age)-->       Rente (replacement_rate * letzter Lohn)
  Löhne wachsen mit wage_growth, Ausgaben und Renten mit inflation.

Ohne Lebenszyklus (cfg.lifecycle = False) bleibt alles wie in den Daten (für den Backtest).

Aufruf:
    venv/bin/python sde/simulate.py [--paths 1000] [--months 120] [--no-lifecycle]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

import numpy as np
import pandas as pd

from december_regime import RegimeParams, classify_decembers, estimate_regimes, regime_table
from estimate_params import DEFAULT_DATA, annuity, estimate, load
from interventions import Compiled

ROOT = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2025-01-01")
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)

WORK, UNEMP, RET, STUD = 0, 1, 2, 3
STATE_NAMES = {WORK: "Arbeit", UNEMP: "arbeitslos", RET: "Rente", STUD: "Studium"}
WORK_GROUPS = ("employed", "self_employed", "part_time")
INITIAL_STATE = {"employed": WORK, "self_employed": WORK, "part_time": WORK,
                 "unemployed": UNEMP, "retired": RET, "student": STUD}


@dataclass
class SimConfig:
    """Alle anpassbaren Annahmen. Defaults: 'Daten' = aus den Challenge-Daten abgeleitet,
    sonst illustrative Annahme (keine Prognose)."""
    # Markt
    mu_I: float = 0.04                  # Depotrendite p.a.
    sigma_I: float = 0.10               # Depotvolatilität p.a.
    rho: float = 0.0                    # Korrelation Depot-/Cashflow-Schock
    r_cash: float = 0.005               # Habenzins p.a.
    r_overdraft: float = 0.08           # Sollzins p.a. (falls Profil keinen Kreditzins hat)
    inflation: float = 0.01             # p.a., Ausgaben und Renten
    mu_H: float = 0.015                 # Immobilien-Wertsteigerung p.a. (nur bei Kauf im Szenario)
    sigma_H: float = 0.05               # Immobilien-Volatilität p.a.
    loan_term_months: int = 60          # Kreditlaufzeit -> Annuität
    # Lebenszyklus
    lifecycle: bool = True
    retirement_age: float = 65.0
    replacement_rate: float = 0.50      # Daten: Median Rente / Median Lohn 55-64
    study_years_left: float = 2.0       # Daten: scenario-assumptions S001
    entry_income: float = 8163.0        # Daten: Median Lohn Angestellte <= 27 J.
    savings_rate_work: float = 0.547    # Daten: Median m / Lohn der Angestellten
    wage_growth: float = 0.01           # p.a.
    job_loss_rate: float = 0.02         # p.a.
    reemployment_rate: float = 0.12     # pro Monat (Ø ~8 Monate Arbeitslosigkeit)
    benefit_rate: float = 0.70          # Arbeitslosengeld / letzter Lohn
    benefit_months: int = 18
    reemployment_income: float = 7738.0  # Daten: Median Lohn Angestellte
    # Sparen
    invest_share: float = 0.0           # Anteil des Cash über Puffer, der monatlich ins Depot geht
    buffer_months: float = 3.0          # Puffer = x Monatsausgaben
    # Dezember / Saison
    december_regime: bool = True
    seasonality: bool = True
    jumps: bool = True
    # Simulation
    n_paths: int = 2000
    months: int = 120
    seed: int = 0


@dataclass
class Model:
    """Alles, was aus den Daten geschätzt wurde."""
    data: dict
    params: pd.DataFrame
    december: pd.DataFrame
    regimes: dict[str, RegimeParams]
    groups: list[str]
    season_ratio: np.ndarray            # (n_groups, 13) Anteil Monatseinkommen, Index = Monat
    season_k: np.ndarray                # (n_groups, 13) Streuungsfaktor relativ zu sigma_C
    goals: pd.DataFrame
    defaults: SimConfig = field(default_factory=SimConfig)

    def gidx(self, group: str) -> int:
        return self.groups.index(group)


@dataclass
class SimResult:
    dates: pd.DatetimeIndex     # Länge T+1, Monatsanfang
    C: np.ndarray               # (n_paths, T+1)
    I: np.ndarray
    L: np.ndarray
    B: np.ndarray               # (n_paths, n_decembers) Bonus-Zustände
    bonus: np.ndarray           # (n_paths, T) ausgezahlter Bonus je Monat
    X: np.ndarray               # (n_paths, T) Netto-Cashflow wie im Ledger (ohne Zins/Kredit)
    state_share: np.ndarray     # (T+1, 4) Anteil Pfade je Lebenszyklus-Zustand
    inflation: float
    H: np.ndarray               # (n_paths, T+1) Immobilienwert

    @property
    def NW(self) -> np.ndarray:
        return self.C + self.I + self.H - self.L

    def deflator(self) -> np.ndarray:
        t = np.arange(len(self.dates)) / 12
        return (1 + self.inflation) ** -t


def data_defaults(params: pd.DataFrame, data_dir: Path = DEFAULT_DATA) -> SimConfig:
    """Leitet die mit 'Daten' markierten Defaults aus den Profilen ab."""
    inc = params.reference_monthly_net_income_chf
    emp = params[params.employment_status == "employed"]
    young = emp[emp.age_at_start <= 27]
    older = emp[emp.age_at_start.between(55, 64)]
    ret = params[params.employment_status == "retired"]
    cfg = SimConfig()
    try:
        sa = pd.read_csv(data_dir / "scenario-assumptions.csv")
        cfg.study_years_left = float(sa.loc[sa.parameter == "study_duration_years", "value"].median())
    except (OSError, ValueError):
        pass
    cfg.entry_income = round(float(young.reference_monthly_net_income_chf.median()))
    cfg.reemployment_income = round(float(emp.reference_monthly_net_income_chf.median()))
    cfg.replacement_rate = round(float(ret.reference_monthly_net_income_chf.median()
                                       / older.reference_monthly_net_income_chf.median()), 2)
    cfg.savings_rate_work = round(float((emp.m_chf_month / inc[emp.index].clip(lower=500)).median()), 3)
    return cfg


def prepare(data_dir: Path = DEFAULT_DATA) -> Model:
    data = load(data_dir)
    params, _, ratios, k = estimate(data_dir)
    dec = classify_decembers(data["cash"], params)
    regimes = estimate_regimes(dec)
    groups = sorted(regimes)
    ratio_tab = np.zeros((len(groups), 13))
    k_tab = np.ones((len(groups), 13))
    for gi, g in enumerate(groups):
        for moy in ratios.columns:
            ratio_tab[gi, moy] = ratios.at[g, moy]
            k_tab[gi, moy] = max(1.0, k.at[g, moy])
    goals = pd.read_csv(data_dir / "synthetic-goals.csv", parse_dates=["target_date"])
    return Model(data, params, dec, regimes, groups, ratio_tab, k_tab, goals,
                 data_defaults(params, data_dir))


def simulate_profile(row: pd.Series, model: Model, cfg: SimConfig,
                     seed: int | None = None, plan: Compiled | None = None) -> SimResult:
    """Simuliert ein Profil. plan = kompilierte Szenario-Interventionen (optional).

    Jede Zufallsquelle hat einen eigenen RNG-Stream (SeedSequence.spawn). Gleicher Seed
    => Baseline und Szenario sehen dieselben Schocks (common random numbers), die
    Differenz zeigt den Effekt der Entscheidung, nicht unterschiedliches Rauschen.
    """
    ss = np.random.SeedSequence(cfg.seed if seed is None else seed)
    r_dep, r_cash, r_jump, r_life, r_dec, r_season, r_prop, r_event = (
        np.random.default_rng(s) for s in ss.spawn(8))
    dt = 1 / 12
    n, T = cfg.n_paths, cfg.months
    ext = plan if plan is not None and plan.T == T else Compiled.empty(T)
    groups = model.groups

    # Regime-Tabellen je Gruppe
    p01 = np.array([model.regimes[g].p01 for g in groups])
    p10 = np.array([model.regimes[g].p10 for g in groups])
    pi_b = np.array([model.regimes[g].stationary_bonus for g in groups])
    b_mean = np.array([model.regimes[g].bonus_ratio_mean for g in groups])
    b_sd = np.array([model.regimes[g].bonus_ratio_sd for g in groups])
    g_unemp, g_ret, g_stud, g_emp = (model.gidx(g) for g in ("unemployed", "retired", "student", "employed"))

    # Startzustand je Pfad
    grp0 = row.employment_status
    state = np.full(n, INITIAL_STATE[grp0])
    work_g = np.full(n, model.gidx(grp0) if grp0 in WORK_GROUPS else g_emp)
    income = np.full(n, max(float(row.reference_monthly_net_income_chf), 0.0))
    expenses = income - row.m_chf_month                     # so dass Einkommen - Ausgaben = m
    last_work = np.where(state == WORK, income,
                         np.where(state == STUD, cfg.entry_income, cfg.reemployment_income)).astype(float)
    benefit_left = np.full(n, -1)                           # -1 = kein befristetes Taggeld

    def group_of_state() -> np.ndarray:
        return np.select([state == WORK, state == UNEMP, state == RET], [work_g, g_unemp, g_ret], g_stud)

    C = np.empty((n, T + 1)); I = np.empty_like(C); Lp = np.empty_like(C); H = np.zeros_like(C)
    C[:, 0], I[:, 0], Lp[:, 0] = row.C0, row.I0, row.L0
    bonus_paid = np.zeros((n, T))
    X = np.zeros((n, T))
    share = np.zeros((T + 1, 4))
    share[0] = np.bincount(state, minlength=4) / n

    r_L = row.r_L_annual
    r_od = r_L if r_L > 0 else cfg.r_overdraft
    p_loan = annuity(row.L0, r_L, cfg.loan_term_months)
    sig_C = row.sigma_C_chf_month
    lam_m = row.jump_rate_per_year / 12 if cfg.jumps else 0.0
    jump = row.jump_mean_chf
    g_wage = (1 + cfg.wage_growth) ** dt
    infl_idx = 1.0

    b = (r_dec.random(n) < pi_b[group_of_state()]).astype(int)   # Zustand vor dem 1. Dezember
    first_dec = True
    B_hist = []

    for t in range(T):
        moy = (START.month - 1 + t) % 12 + 1
        age = row.age_at_start + t / 12
        g_infl = (1 + cfg.inflation + ext.infl_add[t]) ** dt

        # --- Lebenszyklus-Übergänge ---
        u_loss, u_back = r_life.random(n), r_life.random(n)
        if cfg.lifecycle:
            income = np.where(state == WORK, income * g_wage, np.where(state == RET, income * g_infl, income))
            expenses = expenses * g_infl
            last_work = last_work * g_wage
            infl_idx *= g_infl

            grad = (state == STUD) & (t >= cfg.study_years_left * 12)
            if grad.any():
                state[grad] = WORK
                income[grad] = last_work[grad]
                expenses[grad] = np.maximum(expenses[grad], last_work[grad] * (1 - cfg.savings_rate_work))
                work_g[grad] = g_emp

            p_loss = 1 - (1 - min(cfg.job_loss_rate * ext.hz_mult[t], 0.999)) ** dt
            loss = (state == WORK) & (u_loss < p_loss)
            if loss.any():
                last_work[loss] = income[loss]
                state[loss] = UNEMP
                income[loss] = cfg.benefit_rate * last_work[loss]
                benefit_left[loss] = cfg.benefit_months

            unemp = state == UNEMP
            expired = unemp & (benefit_left == 0)
            income[expired] = 0.0
            benefit_left[unemp & (benefit_left > 0)] -= 1
            back = unemp & ~loss & (u_back < cfg.reemployment_rate)
            if back.any():
                state[back] = WORK
                income[back] = last_work[back]
                benefit_left[back] = -1

            if age >= cfg.retirement_age:
                retire = state != RET
                if retire.any():
                    base = np.where(state == WORK, income, last_work)
                    income[retire] = cfg.replacement_rate * base[retire]
                    state[retire] = RET

        gs = group_of_state()
        inc_eff = (np.full(n, ext.inc_set[t]) if not np.isnan(ext.inc_set[t]) else income * ext.inc_factor[t]) \
            + ext.inc_add[t]
        exp_eff = expenses * ext.exp_factor[t] + ext.exp_add[t] * infl_idx

        # --- Depot (GBM exakt) und Immobilie ---
        z1 = r_dep.standard_normal(n)
        z2 = cfg.rho * z1 + np.sqrt(1 - cfg.rho**2) * r_cash.standard_normal(n)
        mu = cfg.mu_I + ext.mu_add[t]
        I[:, t + 1] = I[:, t] * np.exp((mu - 0.5 * cfg.sigma_I**2) * dt + cfg.sigma_I * np.sqrt(dt) * z1) \
            * (1 + ext.depot_shock[t])
        z3 = r_prop.standard_normal(n)
        H[:, t + 1] = H[:, t] * np.exp((cfg.mu_H - 0.5 * cfg.sigma_H**2) * dt + cfg.sigma_H * np.sqrt(dt) * z3) \
            * (1 + ext.prop_shock[t]) + ext.prop_buy[t]

        # --- Profilkredit ---
        L_int = Lp[:, t] * (1 + r_L * dt)
        pay = np.minimum(p_loan, L_int)
        Lp[:, t + 1] = L_int - pay
        pay = pay + ext.loan_pay[t]

        # --- Netto-Cashflow ---
        inc_floor = np.maximum(inc_eff, 500.0)
        x = inc_eff - exp_eff + sig_C * z2
        u_jump = r_jump.random(n)
        if lam_m > 0:
            x += (u_jump < lam_m) * jump
        u_bonus, z_bonus = r_dec.random(n), r_dec.standard_normal(n)
        z_season = r_season.standard_normal(n)
        if moy == 12 and cfg.december_regime:
            if not first_dec:
                p_to_b = np.where(b == 1, 1 - p10[gs], p01[gs])
                b = (u_bonus < p_to_b).astype(int)
            first_dec = False
            B_hist.append(b.copy())
            ratio = np.maximum(0.0, b_mean[gs] + b_sd[gs] * z_bonus)
            bonus_paid[:, t] = b * (state == WORK) * ratio * inc_floor
            x += bonus_paid[:, t]
        elif cfg.seasonality and model.season_ratio[:, moy].any():
            k = model.season_k[gs, moy]
            x += model.season_ratio[gs, moy] * inc_floor + np.sqrt(k**2 - 1) * sig_C * z_season
        X[:, t] = x

        # --- Szenario-Einmalbeträge und Kredite ---
        events = ext.oneoff[t] + ext.loan_disb[t]
        for (m, amount, prob) in ext.stoch_oneoffs:
            if m == t:
                events = events + amount * (r_event.random(n) < prob)

        # --- Cash ---
        r = np.where(C[:, t] >= 0, cfg.r_cash, r_od)
        c_new = C[:, t] * (1 + r * dt) + x + events - pay
        if ext.invest_amt[t] > 0:
            move = np.minimum(ext.invest_amt[t], np.maximum(c_new, 0.0))
            c_new -= move
            I[:, t + 1] += move
        if cfg.invest_share > 0:
            move = cfg.invest_share * np.maximum(c_new - cfg.buffer_months * exp_eff, 0.0)
            c_new -= move
            I[:, t + 1] += move
        C[:, t + 1] = c_new
        share[t + 1] = np.bincount(state, minlength=4) / n

    dates = pd.date_range(START, periods=T + 1, freq="MS")
    B = np.column_stack(B_hist) if B_hist else np.zeros((n, 0), dtype=int)
    L = Lp + ext.loan_L[None, :]
    return SimResult(dates, C, I, L, B, bonus_paid, X, share, cfg.inflation, H)


def quantile_frame(x: np.ndarray, dates: pd.DatetimeIndex) -> pd.DataFrame:
    q = np.quantile(x, QUANTILES, axis=0).T
    return pd.DataFrame(q, index=dates, columns=[f"p{int(100 * a):02d}" for a in QUANTILES])


def goal_probabilities(res: SimResult, goals: pd.DataFrame) -> pd.DataFrame:
    """P(NW zum Zieldatum >= Zielbetrag) je Ziel des Profils (nominal)."""
    out = []
    for _, g in goals.iterrows():
        t = int(np.searchsorted(res.dates, g.target_date))
        t = min(t, len(res.dates) - 1)
        p = float((res.NW[:, t] >= g.target_amount_chf).mean())
        out.append({"Ziel": g.goal_name, "Betrag": g.target_amount_chf,
                    "Datum": g.target_date.date(), "Priorität": g.priority, "P(erreicht)": p})
    return pd.DataFrame(out)


def backtest(model: Model, cfg: SimConfig | None = None, n_paths: int = 1000) -> pd.DataFrame:
    """Simuliert 2025-2026 ohne Lebenszyklus und vergleicht mit dem beobachteten Ledger.

    Verglichen wird C0 + Summe X (ohne Zinsen/Kreditraten, die das Ledger nicht enthält).
    Hinweis: in-sample, die Parameter stammen aus denselben 24 Monaten.
    """
    obs = model.data["cash"].pivot(index="profile_id", columns="month", values="net_transactions_chf")
    cfg = replace(cfg or model.defaults, lifecycle=False, invest_share=0.0,
                  n_paths=n_paths, months=obs.shape[1])
    rows = {}
    for i, (pid, row) in enumerate(model.params.iterrows()):
        r = simulate_profile(row, model, cfg, seed=i)
        end = row.C0 + r.X.sum(axis=1)
        o = row.C0 + obs.loc[pid].sum()
        q05, q25, q75, q95 = np.quantile(end, [0.05, 0.25, 0.75, 0.95])
        rows[pid] = {"employment_status": row.employment_status,
                     "z": (o - end.mean()) / end.std(),
                     "in_90": q05 <= o <= q95, "in_50": q25 <= o <= q75}
    return pd.DataFrame.from_dict(rows, orient="index")


def summarize_all(model: Model, cfg: SimConfig) -> pd.DataFrame:
    rows = {}
    for i, (pid, row) in enumerate(model.params.iterrows()):
        res = simulate_profile(row, model, cfg, seed=i)
        nw = res.NW[:, -1]
        rows[pid] = {
            "employment_status": row.employment_status,
            "age_at_start": row.age_at_start,
            "NW0": row.NW0,
            **{f"NW_T_p{int(100 * a):02d}": float(np.quantile(nw, a)) for a in QUANTILES},
            "P_NW_T_negative": float((nw < 0).mean()),
            "P_cash_ever_negative": float((res.C.min(axis=1) < 0).mean()),
        }
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "profile_id"
    return out


def config_table(cfg: SimConfig) -> pd.Series:
    return pd.Series({f.name: getattr(cfg, f.name) for f in fields(cfg)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=1000)
    ap.add_argument("--months", type=int, default=120)
    ap.add_argument("--no-lifecycle", action="store_true")
    args = ap.parse_args()

    model = prepare()
    cfg = replace(model.defaults, n_paths=args.paths, months=args.months,
                  lifecycle=not args.no_lifecycle)
    pd.set_option("display.width", 160)
    print("Konfiguration:")
    print(config_table(cfg).to_string())
    print("\nDezember-Markov-Regime je Gruppe:")
    print(regime_table(model.regimes).round(3).to_string())

    summary = summarize_all(model, cfg)
    out = ROOT / "output" / "simulation_summary.csv"
    summary.round(2).to_csv(out)
    print(f"\nNW nach {args.months} Monaten (Median der Profil-Mediane) je Gruppe:")
    print(summary.groupby("employment_status")[["NW0", "NW_T_p05", "NW_T_p50", "NW_T_p95",
                                                "P_NW_T_negative"]].median().round(2).to_string())
    print(f"\n{len(summary)} Profile -> {out}")


if __name__ == "__main__":
    main()
