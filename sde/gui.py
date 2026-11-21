"""PySide6-GUI: Net-Worth-Simulation mit anpassbaren Parametern.

Links alle Annahmen (Profilwerte aus den Daten geschätzt, überschreibbar), rechts
Fan-Chart, Komponenten, Lebenszyklus-Zustände und Zielerreichung. Jede Änderung
simuliert nach kurzer Verzögerung automatisch neu.

Start:
    venv/bin/python sde/gui.py
    venv/bin/python sde/gui.py --profile P00003 --screenshot output/gui.png   (Test, offscreen)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, fields, replace

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from plots import (AQUA, BLUE, BLUE_LIGHT, BLUE_MID, CHF_K, GRID, INK, INK_2, NEUTRAL, ORANGE,
                   SURFACE, draw_nw_fan, kchf, lifecycle_events)
from scenarios import SCENARIOS, Param, run_comparison
from simulate import (QUANTILES, RET, STATE_NAMES, STUD, UNEMP, WORK, Model, SimConfig, SimResult,
                      goal_probabilities, prepare, quantile_frame, simulate_profile)

YELLOW = "#eda100"   # Serie 4: Immobilie
NO_SCENARIO = "— kein Szenario (Status quo) —"


def param_spec(key: str, p: Param) -> Spec:
    if p.kind == "pct":
        return Spec(key, p.label, lo=p.lo, hi=p.hi, **PCT)
    if p.kind == "int":
        return Spec(key, p.label, kind="int", lo=p.lo, hi=p.hi, suffix=f" {p.unit}" if p.unit else "")
    dec = 0 if p.unit.startswith("CHF") else 2
    step = 100 if p.unit.startswith("CHF") else 0.05
    return Spec(key, p.label, lo=p.lo, hi=p.hi, step=step, decimals=dec, suffix=f" {p.unit}" if p.unit else "")


@dataclass
class Spec:
    key: str
    label: str
    kind: str = "float"         # float | int | bool
    lo: float = 0.0
    hi: float = 1e9
    step: float = 1.0
    decimals: int = 0
    scale: float = 1.0          # Anzeige = Wert * scale (100 für Prozent)
    suffix: str = ""
    tip: str = ""


PCT = dict(scale=100.0, decimals=1, step=0.5, suffix=" %")

PROFILE_SPECS = [
    Spec("C0", "Cash Start", lo=-1e7, hi=1e8, step=1000, suffix=" CHF"),
    Spec("I0", "Depot Start", hi=1e8, step=1000, suffix=" CHF"),
    Spec("L0", "Kredit Start", hi=1e8, step=1000, suffix=" CHF"),
    Spec("reference_monthly_net_income_chf", "Nettoeinkommen", hi=1e6, step=100, suffix=" CHF/Mt."),
    Spec("m_chf_month", "Netto-Cashflow m", lo=-1e6, hi=1e6, step=100, suffix=" CHF/Mt.",
         tip="Median der Nicht-Saisonmonate; Ausgaben = Einkommen − m"),
    Spec("sigma_C_chf_month", "Streuung σ_C", hi=1e6, step=50, suffix=" CHF/Mt."),
    Spec("jump_rate_per_year", "Sprungrate λ", hi=12, step=0.5, decimals=1, suffix=" /Jahr"),
    Spec("jump_mean_chf", "Sprunghöhe", lo=-1e6, hi=1e6, step=100, suffix=" CHF"),
    Spec("r_L_annual", "Kreditzins", hi=1, **PCT),
    Spec("age_at_start", "Alter", lo=16, hi=100, step=1, kind="int", suffix=" J."),
]

CONFIG_GROUPS = {
    "Markt": [
        Spec("mu_I", "Depotrendite μ_I", lo=-0.5, hi=0.5, **PCT),
        Spec("sigma_I", "Depotvolatilität σ_I", hi=1, **PCT),
        Spec("rho", "Korrelation ρ", lo=-1, hi=1, step=0.1, decimals=2),
        Spec("r_cash", "Habenzins", hi=0.2, **PCT),
        Spec("r_overdraft", "Sollzins (ohne Kredit)", hi=0.5, **PCT),
        Spec("inflation", "Inflation", lo=-0.05, hi=0.2, **PCT),
        Spec("loan_term_months", "Kreditlaufzeit", kind="int", lo=1, hi=600, suffix=" Mt."),
    ],
    "Lebenszyklus": [
        Spec("lifecycle", "Lebenszyklus aktiv", kind="bool"),
        Spec("retirement_age", "Rentenalter", lo=50, hi=80, step=1, decimals=0, suffix=" J."),
        Spec("replacement_rate", "Rente / letzter Lohn", hi=1.5, **PCT),
        Spec("study_years_left", "Rest-Studienzeit", hi=10, step=0.5, decimals=1, suffix=" J."),
        Spec("entry_income", "Einstiegslohn", hi=1e6, step=100, suffix=" CHF/Mt."),
        Spec("savings_rate_work", "Sparquote bei Einstieg", lo=-1, hi=1, **PCT),
        Spec("wage_growth", "Lohnwachstum", lo=-0.1, hi=0.2, **PCT),
        Spec("job_loss_rate", "Jobverlust-Rate", hi=1, **PCT, tip="Wahrscheinlichkeit pro Jahr"),
        Spec("reemployment_rate", "Wiedereinstieg-Rate", hi=1, **PCT, tip="Wahrscheinlichkeit pro Monat"),
        Spec("benefit_rate", "Taggeld / letzter Lohn", hi=1.5, **PCT),
        Spec("benefit_months", "Taggeld-Dauer", kind="int", hi=120, suffix=" Mt."),
        Spec("reemployment_income", "Lohn Wiedereinstieg", hi=1e6, step=100, suffix=" CHF/Mt.",
             tip="für Profile, die arbeitslos starten"),
    ],
    "Sparen": [
        Spec("invest_share", "Anlagequote über Puffer", hi=1, **PCT,
             tip="Anteil des Cash über dem Puffer, der monatlich ins Depot geht"),
        Spec("buffer_months", "Cash-Puffer", hi=60, step=1, decimals=1, suffix=" Monatsausgaben"),
    ],
    "Modell": [
        Spec("december_regime", "Dezember-Markov-Regime", kind="bool"),
        Spec("seasonality", "Saison Feb/Aug", kind="bool"),
        Spec("jumps", "Sprünge", kind="bool"),
    ],
    "Simulation": [
        Spec("n_paths", "Pfade", kind="int", lo=100, hi=20000, step=500),
        Spec("months", "Horizont", kind="int", lo=12, hi=600, step=12, suffix=" Mt."),
        Spec("seed", "Zufalls-Seed", kind="int", hi=10**6),
    ],
}


def make_widget(spec: Spec):
    if spec.kind == "bool":
        w = QCheckBox()
    elif spec.kind == "int":
        w = QSpinBox()
        w.setRange(int(spec.lo), int(min(spec.hi, 2**31 - 1)))
        w.setSingleStep(int(spec.step))
        w.setSuffix(spec.suffix)
    else:
        w = QDoubleSpinBox()
        w.setDecimals(spec.decimals)
        w.setRange(spec.lo * spec.scale, spec.hi * spec.scale)
        w.setSingleStep(spec.step)
        w.setSuffix(spec.suffix)
        w.setGroupSeparatorShown(True)
    if spec.tip:
        w.setToolTip(spec.tip)
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    return w


def set_value(w, spec: Spec, value) -> None:
    w.blockSignals(True)
    if spec.kind == "bool":
        w.setChecked(bool(value))
    elif spec.kind == "int":
        w.setValue(int(round(float(value))))
    else:
        w.setValue(float(value) * spec.scale)
    w.blockSignals(False)


def get_value(w, spec: Spec):
    if spec.kind == "bool":
        return w.isChecked()
    if spec.kind == "int":
        return int(w.value())
    return float(w.value()) / spec.scale


def connect(w, spec: Spec, slot) -> None:
    (w.toggled if spec.kind == "bool" else w.valueChanged).connect(slot)


class MainWindow(QMainWindow):
    def __init__(self, model: Model, profile: str | None = None):
        super().__init__()
        self.model = model
        self.setWindowTitle("Lauzerrrn · Net-Worth-Simulator")
        self.resize(1500, 950)

        self.timer = QTimer(self, singleShot=True, interval=250)
        self.timer.timeout.connect(self.run)

        # --- linke Seite: Parameter ---
        left = QWidget()
        lv = QVBoxLayout(left)

        self.profile_box = QComboBox()
        self.profile_box.setEditable(True)
        self.profile_box.setInsertPolicy(QComboBox.NoInsert)
        p = model.params
        for pid, r in p.iterrows():
            self.profile_box.addItem(
                f"{pid} · {r.display_name} · {r.employment_status}, {int(r.age_at_start)} J.", pid)
        self.profile_box.currentIndexChanged.connect(self.load_profile)
        lv.addWidget(QLabel("<b>Profil</b>"))
        lv.addWidget(self.profile_box)

        btns = QHBoxLayout()
        b1 = QPushButton("Profilwerte zurücksetzen")
        b1.clicked.connect(self.load_profile)
        b2 = QPushButton("Annahmen zurücksetzen")
        b2.clicked.connect(self.reset_config)
        btns.addWidget(b1)
        btns.addWidget(b2)
        lv.addLayout(btns)

        # --- Szenario ---
        sbox = QGroupBox("Szenario (scenario-catalog.csv)")
        sv = QVBoxLayout(sbox)
        self.cat_box = QComboBox()
        self.cat_box.addItem("Alle Kategorien")
        for c in dict.fromkeys(d.category for d in SCENARIOS.values()):
            self.cat_box.addItem(c)
        self.cat_box.currentIndexChanged.connect(self.fill_scenarios)
        self.scen_box = QComboBox()
        self.scen_box.currentIndexChanged.connect(self.load_scenario)
        self.scen_desc = QLabel()
        self.scen_desc.setWordWrap(True)
        self.scen_desc.setStyleSheet(f"color: {INK_2};")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 600)
        self.start_spin.setSuffix(" Mt. ab Jan 2025")
        self.start_spin.valueChanged.connect(self.schedule)
        sv.addWidget(self.cat_box)
        sv.addWidget(self.scen_box)
        sv.addWidget(self.scen_desc)
        sform = QFormLayout()
        sform.addRow("Start", self.start_spin)
        sv.addLayout(sform)
        self.scen_params_box = QWidget()
        self.scen_form = QFormLayout(self.scen_params_box)
        self.scen_form.setContentsMargins(0, 0, 0, 0)
        sv.addWidget(self.scen_params_box)
        b3 = QPushButton("Szenario-Parameter zurücksetzen")
        b3.clicked.connect(self.reset_scenario_params)
        sv.addWidget(b3)
        lv.addWidget(sbox)
        self.scen_widgets: dict = {}

        self.profile_widgets = {}
        box = QGroupBox("Profil (aus Daten geschätzt)")
        form = QFormLayout(box)
        for s in PROFILE_SPECS:
            w = make_widget(s)
            connect(w, s, self.schedule)
            form.addRow(s.label, w)
            self.profile_widgets[s.key] = (w, s)
        lv.addWidget(box)

        self.config_widgets = {}
        for title, specs in CONFIG_GROUPS.items():
            box = QGroupBox(title)
            form = QFormLayout(box)
            for s in specs:
                w = make_widget(s)
                connect(w, s, self.schedule)
                form.addRow(s.label, w)
                self.config_widgets[s.key] = (w, s)
            if title == "Simulation":
                self.real_cb = QCheckBox()
                self.real_cb.toggled.connect(self.schedule)
                form.addRow("Real (inflationsbereinigt)", self.real_cb)
            lv.addWidget(box)
        lv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)

        # --- rechte Seite: Charts + Kennzahlen ---
        right = QWidget()
        rv = QVBoxLayout(right)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setStyleSheet(f"font-size: 13px; color: {INK_2};")
        rv.addWidget(self.summary)

        self.fig = Figure(figsize=(12, 7.5), facecolor=SURFACE, layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        rv.addWidget(self.canvas, 1)

        self.goals = QTableWidget(0, 6)
        self.goals.setHorizontalHeaderLabels(["Ziel", "Betrag CHF", "Datum", "Priorität",
                                              "P(erreicht) Baseline", "P(erreicht) Szenario"])
        self.goals.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.goals.verticalHeader().setVisible(False)
        self.goals.setEditTriggers(QTableWidget.NoEditTriggers)
        self.goals.setMaximumHeight(120)
        rv.addWidget(QLabel("<b>Ziele aus synthetic-goals.csv</b> (Net Worth zum Zieldatum ≥ Betrag, nominal)"))
        rv.addWidget(self.goals)

        split = QSplitter()
        split.addWidget(scroll)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self.reset_config(run=False)
        self.fill_scenarios()
        if profile and profile in p.index:
            self.profile_box.setCurrentIndex(p.index.get_loc(profile))
        self.load_profile()

    # --- Zustand <-> Widgets ---
    def schedule(self, *_):
        self.timer.start()

    def current_pid(self) -> str:
        return self.profile_box.currentData()

    def current_sid(self) -> str | None:
        return self.scen_box.currentData()

    def load_profile(self, *_):
        row = self.model.params.loc[self.current_pid()]
        for key, (w, s) in self.profile_widgets.items():
            set_value(w, s, row[key])
        self.reset_scenario_params(run=False)   # profilabhängige Defaults (Miete, Einkommen …)
        self.run()

    def reset_config(self, *_, run: bool = True):
        d = self.model.defaults
        for key, (w, s) in self.config_widgets.items():
            set_value(w, s, getattr(d, key))
        self.real_cb.setChecked(False)
        if run:
            self.run()

    def fill_scenarios(self, *_):
        cat = self.cat_box.currentText()
        keep = self.current_sid()
        self.scen_box.blockSignals(True)
        self.scen_box.clear()
        self.scen_box.addItem(NO_SCENARIO, None)
        for sid, d in SCENARIOS.items():
            if cat == "Alle Kategorien" or d.category == cat:
                self.scen_box.addItem(f"{sid} · {d.name}", sid)
        idx = self.scen_box.findData(keep)
        self.scen_box.setCurrentIndex(max(idx, 0))
        self.scen_box.blockSignals(False)
        self.load_scenario()

    def load_scenario(self, *_):
        # Formular für die Parameter des gewählten Szenarios neu aufbauen
        while self.scen_form.rowCount():
            self.scen_form.removeRow(0)
        self.scen_widgets = {}
        sid = self.current_sid()
        if sid is None:
            self.scen_desc.setText("Nur die Simulation mit den aktuellen Einstellungen.")
        else:
            d = SCENARIOS[sid]
            base = d.baseline_text if d.baseline else f"Status quo ({d.baseline_text})"
            note = f"<br><i>{d.note}</i>" if d.note else ""
            self.scen_desc.setText(f"<b>{d.category}</b><br>Baseline: {base}<br>"
                                   f"Intervention: {d.intervention_text}{note}")
            for key, prm in d.params.items():
                spec = param_spec(key, prm)
                w = make_widget(spec)
                connect(w, spec, self.schedule)
                self.scen_form.addRow(prm.label, w)
                self.scen_widgets[key] = (w, spec)
        self.reset_scenario_params()

    def reset_scenario_params(self, *_, run: bool = True):
        sid = self.current_sid()
        if sid is not None and self.scen_widgets:
            row = self.model.params.loc[self.current_pid()]
            for key, val in SCENARIOS[sid].defaults(row).items():
                w, s = self.scen_widgets[key]
                set_value(w, s, val)
        if run:
            self.schedule()

    def current_row(self) -> pd.Series:
        row = self.model.params.loc[self.current_pid()].copy()
        for key, (w, s) in self.profile_widgets.items():
            row[key] = get_value(w, s)
        row["NW0"] = row.C0 + row.I0 - row.L0
        return row

    def current_config(self) -> SimConfig:
        vals = {k: get_value(w, s) for k, (w, s) in self.config_widgets.items()}
        valid = {f.name for f in fields(SimConfig)}
        return replace(self.model.defaults, **{k: v for k, v in vals.items() if k in valid})

    # --- Simulation + Darstellung ---
    def run(self):
        if not hasattr(self, "canvas"):
            return
        row, cfg = self.current_row(), self.current_config()
        real = self.real_cb.isChecked()
        sid = self.current_sid()
        if sid is None:
            res, base, comp_cfg = simulate_profile(row, self.model, cfg), None, cfg
        else:
            params = {k: get_value(w, s) for k, (w, s) in self.scen_widgets.items()}
            comp = run_comparison(row, self.model, cfg, sid, params, self.start_spin.value())
            res, base, comp_cfg = comp.scenario, comp.baseline, comp.cfg
        defl = res.deflator() if real else np.ones(len(res.dates))

        self.fig.clear()
        gs = self.fig.add_gridspec(2, 3, height_ratios=[1.5, 1])
        a_nw = self.fig.add_subplot(gs[0, :])
        if base is None:
            draw_nw_fan(a_nw, res, row, cfg, real=real)
            a_mid = self.fig.add_subplot(gs[1, 0])
            self.draw_components(a_mid, res, defl)
            self.draw_states(self.fig.add_subplot(gs[1, 1:]), res)
        else:
            self.draw_comparison(a_nw, base, res, row, comp_cfg, defl, sid)
            self.draw_delta(self.fig.add_subplot(gs[1, 0]), base, res, defl)
            self.draw_components(self.fig.add_subplot(gs[1, 1]), res, defl)
            self.draw_states(self.fig.add_subplot(gs[1, 2]), res)
        self.canvas.draw_idle()

        self.update_summary(row, comp_cfg, res, base, defl, real)
        self.update_goals(res, base)

    def draw_comparison(self, ax, base: SimResult, res: SimResult, row, cfg, defl, sid):
        for r_, color, band, label in ((base, INK_2, GRID, "Baseline"), (res, BLUE, BLUE_LIGHT, "Szenario")):
            q = quantile_frame(r_.NW * defl, r_.dates)
            ax.fill_between(q.index, q.p05, q.p95, color=band, lw=0, alpha=0.8 if r_ is base else 0.7,
                            label=f"{label} 5–95 %")
            ax.plot(q.index, q.p50, color=color, lw=2, ls="--" if r_ is base else "-", label=f"{label} Median")
            ax.annotate(kchf(q.p50.iloc[-1]), (q.index[-1], q.p50.iloc[-1]), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=9, color=color)
        start = res.dates[0] + pd.DateOffset(months=self.start_spin.value())
        if start <= res.dates[-1]:
            ax.axvline(start, color=ORANGE, lw=1.2, ls="-.")
            ax.annotate("Szenario-Start", (start, 0), xycoords=("data", "axes fraction"), xytext=(4, 4),
                        textcoords="offset points", va="bottom", fontsize=8.5, color=INK_2)
        for d, label in lifecycle_events(row, cfg, res.dates):
            ax.axvline(d, color=NEUTRAL, lw=1, ls=":")
            ax.annotate(label, (d, 0), xycoords=("data", "axes fraction"), xytext=(4, 18),
                        textcoords="offset points", va="bottom", fontsize=8, color=INK_2)
        if (np.quantile(base.NW * defl, 0.05, axis=0) < 0).any() or (np.quantile(res.NW * defl, 0.05, axis=0) < 0).any():
            ax.axhline(0, color=INK, lw=0.8)
        d = SCENARIOS[sid]
        ax.set_title(f"{sid} {d.name}: Net Worth{' real' if self.real_cb.isChecked() else ''} Baseline vs. Szenario")
        ax.yaxis.set_major_formatter(CHF_K)
        ax.legend(fontsize=8.5, loc="upper left", ncol=2)

    def draw_delta(self, ax, base: SimResult, res: SimResult, defl):
        delta = (res.NW - base.NW) * defl
        q = quantile_frame(delta, res.dates)
        ax.fill_between(q.index, q.p05, q.p95, color=BLUE_LIGHT, lw=0, label="5–95 %")
        ax.fill_between(q.index, q.p25, q.p75, color=BLUE_MID, lw=0, label="25–75 %")
        ax.plot(q.index, q.p50, color=BLUE, lw=2, label="Median")
        ax.axhline(0, color=INK, lw=0.8)
        p_better = (delta[:, -1] > 0).mean()
        ax.set_title(f"Δ Net Worth · P(besser) {p_better:.0%}")
        ax.yaxis.set_major_formatter(CHF_K)
        ax.legend(fontsize=8, loc="best")

    def draw_components(self, ax, res: SimResult, defl):
        for arr, name, color in ((res.C, "Cash", BLUE), (res.I, "Depot", ORANGE),
                                 (res.H, "Immobilie", YELLOW), (-res.L, "Schulden", AQUA)):
            med = np.median(arr * defl, axis=0)
            if np.abs(med).max() > 0:
                ax.plot(res.dates, med, color=color, lw=2, label=name)
        ax.axhline(0, color=INK_2, lw=0.8)
        ax.set_title("Komponenten (Median)")
        ax.yaxis.set_major_formatter(CHF_K)
        ax.legend(fontsize=8.5, loc="best")

    def draw_states(self, ax, res: SimResult):
        order = [(STUD, NEUTRAL), (WORK, BLUE), (UNEMP, ORANGE), (RET, AQUA)]
        ax.stackplot(res.dates, *[res.state_share[:, s] for s, _ in order],
                     labels=[STATE_NAMES[s] for s, _ in order],
                     colors=[c for _, c in order], edgecolor=SURFACE, linewidth=0.5)
        ax.set_ylim(0, 1)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.set_title("Lebenszyklus-Zustände")
        ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4)

    def update_summary(self, row, cfg, res, base, defl, real):
        def stats_(r_):
            nw = r_.NW[:, -1] * defl[-1]
            q = np.quantile(nw, QUANTILES)
            return q, (nw < 0).mean(), (r_.C.min(axis=1) < 0).mean()

        q, pneg, pcash = stats_(res)
        head = (f"<b>{row.display_name}</b> · Start {kchf(row.NW0)} · nach {cfg.months / 12:g} J."
                f"{' (real)' if real else ''}")
        if base is None:
            self.summary.setText(
                f"{head}: P5 <b>{kchf(q[0])}</b> · Median <b>{kchf(q[2])}</b> · P95 <b>{kchf(q[4])}</b> · "
                f"P(NW&lt;0) <b>{pneg:.0%}</b> · P(Cash jemals &lt;0) <b>{pcash:.0%}</b>")
            return
        qb, pnegb, pcashb = stats_(base)
        delta = (res.NW[:, -1] - base.NW[:, -1]) * defl[-1]
        warn = (f" · <span style='color:{ORANGE}'><b>Liquiditätsengpass:</b> Cash wird in "
                f"{pcash:.0%} der Pfade negativ (Baseline {pcashb:.0%})</span>") if pcash > pcashb + 0.05 else ""
        self.summary.setText(
            f"{head}<br>Baseline: Median <b>{kchf(qb[2])}</b> (P5 {kchf(qb[0])} · P95 {kchf(qb[4])}) · "
            f"Szenario: Median <b>{kchf(q[2])}</b> (P5 {kchf(q[0])} · P95 {kchf(q[4])})<br>"
            f"Δ Median <b>{kchf(np.median(delta))}</b> · Δ Mittel {kchf(delta.mean())} · "
            f"P(Szenario besser) <b>{(delta > 0).mean():.0%}</b> · "
            f"P(Cash jemals &lt;0) {pcashb:.0%} → <b>{pcash:.0%}</b>{warn}")

    def update_goals(self, res, base):
        goals = self.model.goals[self.model.goals.profile_id == self.current_pid()]
        gp = goal_probabilities(res, goals)
        gb = goal_probabilities(base, goals) if base is not None else None
        self.goals.setRowCount(len(gp))
        for i, g in gp.iterrows():
            beyond = pd.Timestamp(g["Datum"]) > res.dates[-1]
            fmt = lambda v: "> Horizont" if beyond else f"{v:.0%}"  # noqa: E731
            cells = [g["Ziel"], f"{g['Betrag']:,.0f}".replace(",", "'"), str(g["Datum"]), g["Priorität"],
                     fmt(gb.loc[i, "P(erreicht)"]) if gb is not None else "–", fmt(g["P(erreicht)"])]
            for j, c in enumerate(cells):
                self.goals.setItem(i, j, QTableWidgetItem(c))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="P00001")
    ap.add_argument("--scenario", help="Szenario-ID vorwählen, z. B. S001")
    ap.add_argument("--start", type=int, default=0, help="Szenario-Startmonat")
    ap.add_argument("--screenshot", help="Fenster rendern, als PNG speichern und beenden")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    model = prepare()
    win = MainWindow(model, args.profile)
    if args.scenario:
        win.scen_box.setCurrentIndex(max(win.scen_box.findData(args.scenario), 0))
        win.start_spin.setValue(args.start)
        win.run()
    win.show()
    if args.screenshot:
        app.processEvents()
        win.canvas.draw()
        app.processEvents()
        win.grab().save(args.screenshot)
        return
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
