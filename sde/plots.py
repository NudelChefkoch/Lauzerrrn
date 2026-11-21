"""Grafiken zur SDE-Simulation mit Dezember-Markov-Regime.

Erzeugt in output/plots/:
  fan_<profil>.png       Backtest Cash 2025-26 + Fan-Chart Net Worth über 10 Jahre
  december_regime.png    Klassifikation, Übergangswahrscheinlichkeiten, simulierte Boni
  overview.png           Backtest-Kalibrierung + Net Worth je Beschäftigungsgruppe

Aufruf:
    venv/bin/python sde/plots.py [--profiles P00001 P00002 P00003] [--paths 2000]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

from december_regime import Z_THRESHOLD  # noqa: E402
from dataclasses import replace  # noqa: E402

from simulate import (ROOT, Model, SimConfig, SimResult, backtest, prepare,  # noqa: E402
                      quantile_frame, simulate_profile, summarize_all)

OUT = ROOT / "output" / "plots"

# Farben (Referenzpalette, Light Mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"        # Simulation / Serie 1
BLUE_LIGHT = "#cfe0f6"  # 5-95 %-Band
BLUE_MID = "#8db7ea"    # 25-75 %-Band
ORANGE = "#eb6834"      # Beobachtung / Serie 2
AQUA = "#1baf7a"        # Serie 3
NEUTRAL = "#b5b3ad"

plt.rcParams.update({
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": INK_2,
    "ytick.color": INK_2,
    "font.size": 10,
    "legend.frameon": False,
    "legend.labelcolor": INK_2,
    "savefig.dpi": 160,
    "savefig.bbox": "tight",
})

CHF_K = mtick.FuncFormatter(lambda v, _: f"{v / 1000:,.0f}k".replace(",", "'"))


def kchf(v: float) -> str:
    return f"{v / 1000:,.0f}k".replace(",", "'")


def lifecycle_events(row: pd.Series, cfg: SimConfig, dates: pd.DatetimeIndex) -> list[tuple]:
    """(Datum, Beschriftung) der deterministischen Lebenszyklus-Ereignisse im Horizont."""
    if not cfg.lifecycle:
        return []
    ev = []
    if row.employment_status == "student":
        ev.append((dates[0] + pd.DateOffset(months=int(round(cfg.study_years_left * 12))), "Berufseinstieg"))
    if row.employment_status != "retired":
        m = int(np.ceil(max(0.0, cfg.retirement_age - row.age_at_start) * 12))
        ev.append((dates[0] + pd.DateOffset(months=m), f"Rente mit {cfg.retirement_age:g}"))
    return [(d, s) for d, s in ev if dates[0] <= d <= dates[-1]]


def draw_backtest(ax, row: pd.Series, model: Model, cfg: SimConfig, cash_obs: pd.Series) -> None:
    """Cash 2025-26: Simulation ohne Lebenszyklus vs. beobachtetes Ledger."""
    n_obs = len(cash_obs)
    bcfg = replace(cfg, lifecycle=False, invest_share=0.0, months=n_obs)
    res = simulate_profile(row, model, bcfg)
    cum = np.column_stack([np.full(bcfg.n_paths, row.C0), row.C0 + np.cumsum(res.X, axis=1)])
    cq = quantile_frame(cum, res.dates)
    obs_path = np.concatenate([[row.C0], row.C0 + cash_obs.values.cumsum()])

    ax.fill_between(cq.index, cq.p05, cq.p95, color=BLUE_LIGHT, lw=0, label="Simulation 5–95 %")
    ax.fill_between(cq.index, cq.p25, cq.p75, color=BLUE_MID, lw=0, label="Simulation 25–75 %")
    ax.plot(cq.index, cq.p50, color=BLUE, lw=2, label="Simulation Median")
    ax.plot(cq.index, obs_path, color=ORANGE, lw=2, marker="o", ms=3.5, label="Beobachtet")
    for d in cq.index[cq.index.month == 12]:
        ax.axvline(d, color=NEUTRAL, lw=0.8, ls=":", zorder=0)
    ax.set_title("Backtest Cash 2025–2026")
    ax.set_ylabel("CHF")
    ax.yaxis.set_major_formatter(CHF_K)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%y"))
    ax.legend(loc="best", fontsize=8.5)


def draw_nw_fan(ax, res: SimResult, row: pd.Series, cfg: SimConfig, real: bool = False,
                n_sample_paths: int = 5) -> None:
    """Fan-Chart Net Worth mit Lebenszyklus-Ereignissen; real = inflationsbereinigt."""
    nw = res.NW * res.deflator() if real else res.NW
    nwq = quantile_frame(nw, res.dates)
    ax.fill_between(nwq.index, nwq.p05, nwq.p95, color=BLUE_LIGHT, lw=0, label="5–95 %")
    ax.fill_between(nwq.index, nwq.p25, nwq.p75, color=BLUE_MID, lw=0, label="25–75 %")
    for k in range(min(n_sample_paths, len(nw))):
        ax.plot(res.dates, nw[k], color=BLUE, lw=0.6, alpha=0.35)
    ax.plot(nwq.index, nwq.p50, color=BLUE, lw=2, label="Median")
    ax.axhline(row.NW0, color=INK_2, lw=1, ls="--", label=f"Start {kchf(row.NW0)}")
    if (nwq.p05 < 0).any():
        ax.axhline(0, color=INK, lw=0.8)
    for d, label in lifecycle_events(row, cfg, res.dates):
        ax.axvline(d, color=ORANGE, lw=1.2, ls="-.", zorder=1)
        ax.annotate(label, (d, 1), xycoords=("data", "axes fraction"), xytext=(4, -4),
                    textcoords="offset points", va="top", fontsize=8.5, color=INK_2)
    end = nwq.iloc[-1]
    for col in ("p05", "p50", "p95"):
        ax.annotate(kchf(end[col]), (nwq.index[-1], end[col]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=9, color=INK_2)
    p_neg = (nw[:, -1] < 0).mean()
    years = cfg.months / 12
    ax.set_title(f"Net Worth{' real' if real else ''} über {years:g} Jahre · "
                 f"P(NW < 0 am Ende) = {p_neg:.0%}")
    ax.yaxis.set_major_formatter(CHF_K)
    ax.legend(loc="upper left" if end.p50 >= row.NW0 else "lower left", fontsize=8.5)


def fan_chart(pid: str, row: pd.Series, model: Model, cfg: SimConfig, cash_obs: pd.Series) -> Path:
    res = simulate_profile(row, model, cfg, seed=42)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.6]})
    title = f"{row.display_name} ({pid}) · {row.employment_status}, {int(row.age_at_start)} J."
    fig.suptitle(title, x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)
    draw_backtest(a1, row, model, cfg, cash_obs)
    draw_nw_fan(a2, res, row, cfg)
    fig.tight_layout()
    path = OUT / f"fan_{pid}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def december_plot(model: Model, cfg: SimConfig, example_row: pd.Series) -> Path:
    dec, regimes = model.december, model.regimes
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(15, 4.4))
    fig.suptitle("Dezember als Markov-Regime: Bonus / kein Bonus", x=0.01, ha="left",
                 fontsize=14, fontweight="bold", color=INK)

    # Panel 1: Klassifikation (Angestellte + Selbständige)
    d = dec[dec.employment_status.isin(["employed", "self_employed"])]
    z = d.z.clip(-5, 40)
    bins = np.arange(-5, 41, 1)
    a1.hist(z[d.B == 0], bins=bins, color=NEUTRAL, label="kein Bonus", edgecolor=SURFACE, lw=1)
    a1.hist(z[d.B == 1], bins=bins, color=BLUE, label="Bonus", edgecolor=SURFACE, lw=1)
    a1.axvline(Z_THRESHOLD, color=INK, lw=1, ls="--")
    a1.annotate(f"Schwelle z = {Z_THRESHOLD:g}", (Z_THRESHOLD, a1.get_ylim()[1] * 0.92),
                xytext=(5, 0), textcoords="offset points", fontsize=9, color=INK_2)
    a1.set_title("Klassifikation beobachteter Dezember")
    a1.set_xlabel("z = (X_Dez − m) / σ   (Angestellte + Selbständige, 2025–26)")
    a1.set_ylabel("Anzahl")
    a1.legend(fontsize=8.5)

    # Panel 2: Übergangswahrscheinlichkeiten je Gruppe
    groups = list(regimes)
    x = np.arange(len(groups))
    w = 0.38
    p_nb = [regimes[g].p01 for g in groups]
    p_bb = [1 - regimes[g].p10 for g in groups]
    a2.bar(x - w / 2 - 0.01, p_nb, w, color=BLUE, label="P(Bonus | Vorjahr kein Bonus)")
    a2.bar(x + w / 2 + 0.01, p_bb, w, color=ORANGE, label="P(Bonus | Vorjahr Bonus)")
    for i, g in enumerate(groups):
        if regimes[g].n_bonus_obs < 5:
            a2.annotate("wenig\nDaten", (i + w / 2, p_bb[i]), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=7.5, color=INK_2)
    a2.set_xticks(x, [g.replace("_", "\n") for g in groups], fontsize=8.5)
    a2.yaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=0))
    a2.set_ylim(0, 1)
    a2.set_title("Übergangswahrscheinlichkeiten je Gruppe")
    a2.legend(fontsize=8.5, loc="upper right")

    # Panel 3: simulierte Boni eines Beispielprofils
    reg = regimes[example_row.employment_status]
    # ohne Lebenszyklus, damit nur das Regime sichtbar ist (keine Pensionierung)
    res = simulate_profile(example_row, model, replace(cfg, lifecycle=False, months=120), seed=7)
    dec_idx = np.where(res.dates[:-1].month == 12)[0]
    years = res.dates[dec_idx].year
    for k, (c, off) in enumerate(zip([BLUE, ORANGE, AQUA], [-0.18, 0, 0.18])):
        vals = res.bonus[k, dec_idx]
        a3.vlines(years + off, 0, vals, color=c, lw=2)
        a3.scatter(years + off, vals, color=c, s=28, zorder=3, edgecolor=SURFACE, lw=1.5,
                   label=f"Pfad {k + 1}")
    a3.set_title(f"Simulierte Dezember-Boni · {example_row.display_name}")
    a3.set_ylabel("Bonus CHF")
    a3.yaxis.set_major_formatter(CHF_K)
    a3.set_xticks(years[::2])
    a3.legend(fontsize=8.5, loc="upper left")
    a3.annotate(f"P(N→B) = {reg.p01:.0%}, P(B→B) = {1 - reg.p10:.0%}\n"
                f"Bonus ≈ {reg.bonus_ratio_mean:.2f} × Monatseinkommen",
                (0.99, 0.98), xycoords="axes fraction", ha="right", va="top", fontsize=8.5, color=INK_2)

    fig.tight_layout()
    path = OUT / "december_regime.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def overview_plot(bt: pd.DataFrame, summary: pd.DataFrame) -> Path:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.3]})
    fig.suptitle("Validierung und Ergebnis über alle 1'200 Profile", x=0.01, ha="left",
                 fontsize=14, fontweight="bold", color=INK)

    # Panel 1: Kalibrierung
    z = bt.z.clip(-5, 5)
    a1.hist(z, bins=np.arange(-5, 5.01, 0.4), density=True, color=BLUE_MID, edgecolor=SURFACE, lw=1,
            label="Backtest-z der Profile")
    g = np.linspace(-5, 5, 200)
    a1.plot(g, stats.norm.pdf(g), color=INK, lw=2, label="N(0, 1) = perfekt kalibriert")
    a1.set_title("Backtest 2025–26: ist die Streuung richtig?")
    a1.set_xlabel("z = (beobachtet − Simulationsmittel) / Simulations-Std")
    a1.set_ylabel("Dichte")
    a1.legend(fontsize=8.5, loc="upper left")
    a1.annotate(f"im 90 %-Band: {bt.in_90.mean():.0%}\nim 50 %-Band: {bt.in_50.mean():.0%}\n"
                f"z: Mittel {bt.z.mean():+.2f}, Std {bt.z.std():.2f}",
                (0.98, 0.97), xycoords="axes fraction", ha="right", va="top", fontsize=9, color=INK_2)

    # Panel 2: Start vs. 10 Jahre je Gruppe (Median über Profile)
    s = summary.groupby("employment_status")[["NW0", "NW_T_p05", "NW_T_p50", "NW_T_p95"]].median()
    s = s.sort_values("NW_T_p50")
    y = np.arange(len(s))
    a2.hlines(y, s.NW_T_p05, s.NW_T_p95, color=BLUE_MID, lw=6, label="10 J.: 5–95 % (Median-Profil)")
    a2.scatter(s.NW0, y, color=NEUTRAL, s=60, zorder=3, edgecolor=SURFACE, lw=1.5, label="Start 2025")
    a2.scatter(s.NW_T_p50, y, color=BLUE, s=60, zorder=4, edgecolor=SURFACE, lw=1.5, label="10 J.: Median")
    for i, v in enumerate(s.NW_T_p50):
        a2.annotate(f"{v / 1000:,.0f}k".replace(",", "'"), (v, i), xytext=(0, 9),
                    textcoords="offset points", ha="center", fontsize=8.5, color=INK_2)
    a2.axvline(0, color=INK, lw=0.8)
    a2.set_yticks(y, s.index)
    a2.xaxis.set_major_formatter(CHF_K)
    a2.set_title("Net Worth je Gruppe: Start vs. nach 10 Jahren")
    a2.legend(fontsize=8.5, loc="lower right")

    fig.tight_layout()
    path = OUT / "overview.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", nargs="+", default=["P00001", "P00002", "P00003"])
    ap.add_argument("--paths", type=int, default=2000)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    model = prepare()
    params = model.params
    cfg = replace(model.defaults, n_paths=args.paths)
    cash = model.data["cash"].pivot(index="profile_id", columns="month", values="net_transactions_chf")

    paths = []
    for pid in args.profiles:
        paths.append(fan_chart(pid, params.loc[pid], model, cfg, cash.loc[pid]))

    emp = params[params.employment_status == "employed"]
    example = next((params.loc[p] for p in args.profiles if p in emp.index), emp.iloc[0])
    paths.append(december_plot(model, cfg, example))

    bt = backtest(model, cfg, n_paths=500)
    summary = summarize_all(model, replace(cfg, n_paths=500))
    paths.append(overview_plot(bt, summary))

    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
