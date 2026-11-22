"""Lebensweg – Spieloberfläche (PySide6).

Ein Brett von Alter 20 bis 67, Avatare in Autos, Würfel (1–3 Jahre), Entscheidungen
mit Vorschau aufs Net Worth, Schicksalskarten und am Ende die Lebensbilanz als Graph.

Start:
    venv/bin/python sde/lebensweg_gui.py
Demo (alle auf Autopilot), z. B. für Screenshots:
    venv/bin/python sde/lebensweg_gui.py --demo --screenshot output/lebensweg_brett.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFormLayout, QGraphicsObject, QGraphicsScene, QGraphicsView,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QMainWindow, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from lebensweg import (BOARD, END_AGE, GAME_DEFAULTS, PLAYER_COLORS, SIM_END_AGE, START_AGE,
                       Decision, Game, life_figure, months, student_profiles)
from plots import CHF_K, GRID, INK, INK_2, NEUTRAL, SURFACE, kchf
from simulate import ROOT, prepare

SPACING, LANE_DY, MARGIN = 92, 74, 90
ROAD = "#d9d6cf"
GROUND = "#eef3ea"
DECISION_C = "#3d3b38"
EVENT_C = "#6250d6"
FINISH_C = "#eda100"
NAMES = ["Alexia", "Ben", "Chiara", "Dario"]


def field_pos(age: int, lane: int | None) -> QPointF:
    f = BOARD[age - START_AGE]
    x = MARGIN + (age - START_AGE) * SPACING
    if f.lane_of is None or lane is None:
        return QPointF(x, 0)
    return QPointF(x, (lane - (f.n_lanes - 1) / 2) * LANE_DY)


# ---------------------------------------------------------------------------
# Brett und Autos
# ---------------------------------------------------------------------------
class Car(QGraphicsObject):
    """Eigenes Design: kleines Auto in Spielerfarbe mit Avatar-Kopf und Initiale."""

    def __init__(self, name: str, color: str):
        super().__init__()
        self.name, self.color = name, QColor(color)
        self.setZValue(10)

    def boundingRect(self) -> QRectF:
        return QRectF(-24, -30, 48, 52)

    def paint(self, p: QPainter, *_):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 40))
        p.drawEllipse(QRectF(-20, 9, 40, 7))                               # Schatten
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(-20, -6, 40, 15), 6, 6)                   # Karosserie
        p.drawRoundedRect(QRectF(-11, -15, 22, 12), 5, 5)                  # Kabine
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(-8, -13, 16, 8), 3, 3)                    # Fenster
        p.setBrush(QColor("#2b2a28"))
        p.drawEllipse(QRectF(-15, 5, 9, 9))
        p.drawEllipse(QRectF(6, 5, 9, 9))                                  # Räder
        p.setBrush(QColor("#f3d2b3"))
        p.setPen(QPen(self.color.darker(130), 1.2))
        p.drawEllipse(QRectF(-7, -28, 14, 14))                             # Avatar-Kopf
        p.setPen(QColor(INK))
        f = QFont()
        f.setPixelSize(9)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(-7, -28, 14, 14), Qt.AlignCenter, self.name[:1])


class Board(QGraphicsScene):
    def __init__(self):
        super().__init__()
        width = MARGIN * 2 + (END_AGE - START_AGE) * SPACING
        self.setSceneRect(0, -230, width, 420)
        self.setBackgroundBrush(QColor(GROUND))
        self._draw_roads()
        self._draw_fields()

    def _segments(self):
        """Alle Strassenabschnitte (Start- und Endpunkt) zwischen benachbarten Feldern."""
        segs = []
        for f0, f1 in zip(BOARD[:-1], BOARD[1:]):
            l0 = range(f0.n_lanes) if f0.lane_of is not None else [None]
            l1 = range(f1.n_lanes) if f1.lane_of is not None else [None]
            if f0.lane_of is not None and f1.lane_of == f0.lane_of:
                pairs = [(i, i) for i in l0]
            else:
                pairs = [(a, b) for a in l0 for b in l1]
            segs += [(field_pos(f0.age, a), field_pos(f1.age, b)) for a, b in pairs]
        return segs

    def _draw_roads(self):
        for width, color, style in ((30, ROAD, Qt.SolidLine), (2, "#ffffff", Qt.DashLine)):
            pen = QPen(QColor(color), width, style, Qt.RoundCap, Qt.RoundJoin)
            for a, b in self._segments():
                path = QPainterPath(a)
                mid = (a.x() + b.x()) / 2
                path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
                self.addPath(path, pen).setZValue(0 if width > 2 else 1)

    def _text(self, text, x, y, size=10, color=INK_2, bold=False, center=True):
        t = self.addText(text)
        f = QFont()
        f.setPixelSize(size)
        f.setBold(bold)
        t.setFont(f)
        t.setDefaultTextColor(QColor(color))
        br = t.boundingRect()
        t.setPos(x - (br.width() / 2 if center else 0), y - br.height() / 2)
        t.setZValue(3)
        return t

    def _draw_fields(self):
        for f in BOARD:
            lanes = range(f.n_lanes) if f.lane_of is not None else [None]
            for lane in lanes:
                pos = field_pos(f.age, lane)
                r = 15
                if f.kind == "decision":
                    color, label = DECISION_C, "!"
                elif f.kind == "event":
                    color, label = EVENT_C, "?"
                elif f.kind == "finish":
                    color, label, r = FINISH_C, "🏁", 20
                else:
                    color, label = "#ffffff", ""
                item = self.addEllipse(pos.x() - r, pos.y() - r, 2 * r, 2 * r,
                                       QPen(QColor(INK_2 if color == "#ffffff" else color), 1.5), QBrush(QColor(color)))
                item.setZValue(2)
                if label:
                    self._text(label, pos.x(), pos.y(), 13, "#ffffff" if f.kind != "finish" else INK, True)
            base = field_pos(f.age, None)
            low = max((field_pos(f.age, l).y() for l in lanes if l is not None), default=0)
            self._text(str(f.age), base.x(), max(low, 0) + 30, 10, INK_2)
            if f.kind == "decision":
                d = f.decision
                self._text(f"{d.icon} {d.title}", base.x(), -58, 12, INK, True)
            if f.lane_of is not None and f.age == f.lane_of + 1:
                d = BOARD[f.lane_of - START_AGE].decision
                for i, opt in enumerate(d.options):
                    p = field_pos(f.age, i)
                    self._text(f"{opt.icon} {opt.label}", p.x() + 22, p.y() - 20, 10, INK_2, center=False)
        self._text("Start · 20", MARGIN, 60, 11, INK, True)


# ---------------------------------------------------------------------------
# Dialoge
# ---------------------------------------------------------------------------
class SetupDialog(QDialog):
    def __init__(self, model):
        super().__init__()
        self.setWindowTitle("Lebensweg · Neues Spiel")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<h2>Lebensweg</h2>Fahre von 20 bis 67 durchs Leben. Jede Entscheidung "
                             "und jedes Ereignis wird mit dem Finanzmodell (SDE, Monte Carlo) gerechnet."))
        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Spieler</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Startprofil (Studierende aus den Daten)</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Autopilot</b>"), 0, 2)
        studs = student_profiles(model)
        pids = ["P00001"] + [p for p in studs.index if p != "P00001"]
        self.rows = []
        for i in range(4):
            cb = QCheckBox(NAMES[i])
            cb.setChecked(i < 2)
            name = QLineEdit(NAMES[i])
            prof = QComboBox()
            for pid in pids:
                r = model.params.loc[pid]
                prof.addItem(f"{pid} · {r.display_name} · Cash {kchf(r.C0)} · Einkommen "
                             f"{r.reference_monthly_net_income_chf:,.0f}".replace(",", "'"), pid)
            prof.setCurrentIndex(i)
            auto = QCheckBox()
            auto.setChecked(i >= 1)
            box = QHBoxLayout()
            box.addWidget(cb)
            box.addWidget(name)
            w = QWidget()
            w.setLayout(box)
            grid.addWidget(w, i + 1, 0)
            grid.addWidget(prof, i + 1, 1)
            grid.addWidget(auto, i + 1, 2, Qt.AlignCenter)
            self.rows.append((cb, name, prof, auto))
        lay.addLayout(grid)

        form = QFormLayout()
        self.entry = QDoubleSpinBox()
        self.entry.setRange(1000, 30000)
        self.entry.setSingleStep(250)
        self.entry.setValue(GAME_DEFAULTS["entry_income"])
        self.entry.setSuffix(" CHF/Mt.")
        self.save = QDoubleSpinBox()
        self.save.setRange(0, 80)
        self.save.setValue(GAME_DEFAULTS["savings_rate_work"] * 100)
        self.save.setSuffix(" %")
        self.seed = QSpinBox()
        self.seed.setRange(0, 10**6)
        self.seed.setValue(7)
        form.addRow("Einstiegslohn (Spielannahme)", self.entry)
        form.addRow("Sparquote beim Berufseinstieg", self.save)
        form.addRow("Zufalls-Seed", self.seed)
        lay.addLayout(form)
        go = QPushButton("Los geht's 🚗")
        go.clicked.connect(self.accept)
        lay.addWidget(go)

    def players(self):
        return [(n.text() or "?", p.currentData(), a.isChecked()) for cb, n, p, a in self.rows if cb.isChecked()]

    def game_cfg(self):
        return {"entry_income": self.entry.value(), "savings_rate_work": self.save.value() / 100}


class DecisionDialog(QDialog):
    def __init__(self, game: Game, pl, decision: Decision, parent=None):
        super().__init__(parent)
        self.choice = None
        self.setWindowTitle(f"{pl.name} · {decision.title}")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<h3>{decision.icon} {decision.age} Jahre · {decision.title}</h3>{decision.question}"))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            prev = game.engine.preview(pl, decision)
        finally:
            QApplication.restoreOverrideCursor()
        for i, (opt, (nw, delta)) in enumerate(zip(decision.options, prev)):
            reason = game.allowed(pl, opt)
            txt = (f"{opt.icon}  {opt.label}\n{opt.text}\nLebensqualität {opt.lq:+d} · "
                   f"Net Worth mit 67: {kchf(nw)} ({'+' if delta >= 0 else ''}{kchf(delta)})")
            if reason:
                txt += f"\n🔒 {reason}"
            b = QPushButton(txt)
            b.setStyleSheet("text-align: left; padding: 8px;")
            b.setEnabled(reason is None)
            b.clicked.connect(lambda _=False, i=i: self._pick(i))
            lay.addWidget(b)
        lay.addWidget(QLabel(f"<span style='color:{INK_2}'>Vorschau: Median aus 200 Pfaden, Δ gegenüber "
                             "keiner Änderung, künftige Entscheidungen noch offen.</span>"))

    def _pick(self, i):
        self.choice = i
        self.accept()


class EndDialog(QDialog):
    def __init__(self, game: Game, out: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lebensweg · Lebensbilanz")
        self.resize(1500, 1000)
        lay = QVBoxLayout(self)
        self.fig = Figure(figsize=(16, 11), layout="constrained")
        life_figure(game, self.fig)
        lay.addWidget(FigureCanvasQTAgg(self.fig), 1)
        out.parent.mkdir(parents=True, exist_ok=True)
        self.fig.savefig(out, dpi=130)
        lay.addWidget(QLabel(f"Gespeichert: {out}"))


# ---------------------------------------------------------------------------
# Hauptfenster
# ---------------------------------------------------------------------------
class GameWindow(QMainWindow):
    def __init__(self, model, players, game_cfg, seed, fast=False):
        super().__init__()
        self.setWindowTitle("Lebensweg")
        self.resize(1500, 900)
        self.fast = fast
        self.busy = False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.game = Game(model, players, seed=seed, **game_cfg)
        QApplication.restoreOverrideCursor()

        self.board = Board()
        self.view = QGraphicsView(self.board)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setMinimumHeight(430)
        self.cars = []
        for i, pl in enumerate(self.game.players):
            car = Car(pl.name, pl.color)
            self.board.addItem(car)
            self.cars.append(car)
            car.setPos(self._car_pos(i, pl.age))

        side = QWidget()
        side.setFixedWidth(400)
        sv = QVBoxLayout(side)
        self.turn_lbl = QLabel()
        self.turn_lbl.setStyleSheet("font-size: 16px;")
        sv.addWidget(self.turn_lbl)
        self.roll_btn = QPushButton("🎲  Würfeln")
        self.roll_btn.setStyleSheet("font-size: 18px; padding: 10px;")
        self.roll_btn.clicked.connect(self.roll)
        sv.addWidget(self.roll_btn)
        self.die_lbl = QLabel()
        self.die_lbl.setAlignment(Qt.AlignCenter)
        self.die_lbl.setStyleSheet("font-size: 28px;")
        sv.addWidget(self.die_lbl)
        self.auto_all = QCheckBox("Alle auf Autopilot")
        self.auto_all.toggled.connect(lambda _: self.maybe_auto())
        sv.addWidget(self.auto_all)
        legend = QLabel(f"<span style='color:{DECISION_C}'>●</span> ! Entscheidung &nbsp; "
                        f"<span style='color:{EVENT_C}'>●</span> ? Schicksalskarte &nbsp; 🏁 Ruhestand mit 67")
        sv.addWidget(legend)
        self.cards = QLabel()
        self.cards.setTextFormat(Qt.RichText)
        self.cards.setWordWrap(True)
        sv.addWidget(self.cards)
        self.fig = Figure(figsize=(4, 2.6), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        sv.addWidget(self.canvas)
        sv.addWidget(QLabel("<b>Logbuch</b>"))
        self.log = QListWidget()
        sv.addWidget(self.log, 1)

        central = QWidget()
        h = QHBoxLayout(central)
        h.addWidget(self.view, 1)
        h.addWidget(side)
        self.setCentralWidget(central)
        self.refresh_panel()
        QTimer.singleShot(300, self.start_turn)

    # --- Anzeige ---
    def _car_pos(self, idx: int, age: int) -> QPointF:
        pl = self.game.players[idx]
        p = field_pos(age, pl.lane_at(age))
        n = len(self.game.players)
        return QPointF(p.x() + (idx - (n - 1) / 2) * 7, p.y() - 6 + (idx - (n - 1) / 2) * 10)

    def refresh_panel(self):
        g = self.game
        cur = g.current
        self.turn_lbl.setText(f"Am Zug: <b style='color:{cur.color}'>{cur.name}</b> · {cur.age} Jahre"
                              if not g.over() else "<b>Spiel beendet</b>")
        rows = []
        for pl in g.players:
            q = g.engine.nw_quantiles(pl.result, pl.age)
            icons = "".join(i for k, i in (("home", "🏠"), ("car", "🚗"), ("kids", "👶"), ("partner", "💞"),
                                            ("investor", "📈"), ("founder", "🚀")) if pl.flags.get(k))
            rows.append(f"<p style='margin:4px 0'><span style='color:{pl.color}'>■</span> <b>{pl.name}</b> "
                        f"{'🏁' if pl.done else ''} · {pl.age} J. · NW <b>{kchf(q[1])}</b> "
                        f"<span style='color:{INK_2}'>({kchf(q[0])}–{kchf(q[2])})</span> · LQ {pl.lq} {icons}</p>")
        self.cards.setText("".join(rows))
        self.fig.clear()
        ax = self.fig.add_subplot()
        for pl in g.players:
            if pl.history:
                a, q25, q50, q75 = zip(*pl.history)
                ax.plot(a, q50, color=pl.color, lw=2, marker="o", ms=3, label=pl.name)
        ax.axhline(0, color=INK, lw=0.6)
        ax.set_xlim(START_AGE, END_AGE)
        ax.yaxis.set_major_formatter(CHF_K)
        ax.set_title("Net Worth (Median) bisher", fontsize=10)
        ax.legend(fontsize=7, loc="upper left")
        self.canvas.draw_idle()
        car = self.cars[g.turn]
        if not g.over():
            self.view.centerOn(car.pos().x() + 250, 0)

    def add_log(self, text: str):
        self.log.insertItem(0, text)

    def is_auto(self, pl) -> bool:
        return pl.auto or self.auto_all.isChecked()

    # --- Ablauf ---
    def start_turn(self):
        g = self.game
        if g.over():
            return self.end_game()
        pl = g.current
        self.refresh_panel()
        d = g.pending_decision(pl)
        if d is not None:                    # Entscheidung auf dem Startfeld
            self.decide(pl, d)
            self.refresh_panel()
        self.roll_btn.setEnabled(not self.is_auto(pl))
        self.maybe_auto()

    def maybe_auto(self):
        if not self.game.over() and self.is_auto(self.game.current) and not self.busy:
            QTimer.singleShot(50 if self.fast else 600, self.roll)

    def roll(self):
        if self.busy or self.game.over():
            return
        self.busy = True
        self.roll_btn.setEnabled(False)
        g = self.game
        pl = g.current
        steps = g.roll()
        self.die_lbl.setText(["", "⚀", "⚁", "⚂"][steps] + f"  {steps} Jahr{'e' if steps > 1 else ''}")
        self.path = g.path(pl, steps)
        self.drive()

    def drive(self):
        g = self.game
        pl = g.current
        idx = g.turn
        if not self.path:
            return self.land()
        age = self.path.pop(0)
        g.arrive(pl, age)
        target = self._car_pos(idx, age)
        if self.fast:
            self.cars[idx].setPos(target)
            return self.drive()
        anim = QPropertyAnimation(self.cars[idx], b"pos", self)
        anim.setDuration(260)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.finished.connect(self.drive)
        self.view.centerOn(target.x() + 250, 0)
        anim.start()
        self._anim = anim

    def land(self):
        g = self.game
        pl = g.current
        f = g.field(pl.age)
        if f.kind == "decision":
            self.decide(pl, f.decision)
            self.cars[g.turn].setPos(self._car_pos(g.turn, pl.age))
        elif f.kind == "event":
            before = g.engine.nw_quantiles(pl.result, END_AGE)[1]
            card = g.draw_card(pl)
            after = g.engine.nw_quantiles(pl.result, END_AGE)[1]
            msg = f"{pl.name} ({pl.age}): {'🍀' if card.good else '⚡'} {card.title} – {card.text} " \
                  f"LQ {card.lq:+d}, NW mit 67 {'+' if after >= before else ''}{kchf(after - before)}"
            self.add_log(msg)
            if not self.is_auto(pl):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, f"Schicksalskarte: {card.title}", msg)
        else:
            pl.history.append((pl.age, *g.engine.nw_quantiles(pl.result, pl.age)))
            if f.kind == "finish":
                self.add_log(f"🏁 {pl.name} ist mit {pl.age} im Ruhestand angekommen.")
        g.next_turn()
        self.busy = False
        self.refresh_panel()
        QTimer.singleShot(0 if self.fast else 150, self.start_turn)

    def decide(self, pl, d: Decision):
        g = self.game
        if self.is_auto(pl):
            i = g.auto_choice(pl, d)
        else:
            dlg = DecisionDialog(g, pl, d, self)
            while dlg.exec() != QDialog.Accepted or dlg.choice is None:
                pass
            i = dlg.choice
        opt = g.choose(pl, d, i)
        self.add_log(f"{pl.name} ({d.age}): {d.title} → {opt.icon} {opt.label} (LQ {opt.lq:+d})")

    def end_game(self):
        self.roll_btn.setEnabled(False)
        self.refresh_panel()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.game.finish()
        QApplication.restoreOverrideCursor()
        self.end = EndDialog(self.game, ROOT / "output" / "lebensweg_bilanz.png", self)
        self.end.show()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="alle Spieler auf Autopilot, schnell")
    ap.add_argument("--players", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--screenshot", help="Brett mitten im Spiel und Lebensbilanz speichern, dann beenden")
    args = ap.parse_args()

    app = QApplication(sys.argv)
    model = prepare()
    if args.demo or args.screenshot:
        studs = student_profiles(model)
        pids = ["P00001"] + [p for p in studs.index if p != "P00001"]
        players = [(NAMES[i], pids[i], True) for i in range(args.players)]
        win = GameWindow(model, players, {}, args.seed, fast=bool(args.screenshot))
    else:
        setup = SetupDialog(model)
        if setup.exec() != QDialog.Accepted or not setup.players():
            return
        win = GameWindow(model, setup.players(), setup.game_cfg(), setup.seed.value())
    win.show()
    if args.screenshot:
        shot = Path(args.screenshot)
        # Brett nach etwa der Hälfte des Spiels festhalten
        win.fast = True
        while not win.game.over() and min(p.age for p in win.game.players) < 40:
            app.processEvents()
        app.processEvents()
        win.grab().save(str(shot))
        while not win.game.over() or not hasattr(win, "end"):
            app.processEvents()
        app.processEvents()
        win.end.grab().save(str(shot.with_name(shot.stem + "_ende.png")))
        return
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
