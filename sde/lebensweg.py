"""Lebensweg: ein Brettspiel über finanzielle Lebensentscheidungen (Spiellogik + Finanzkern).

Das Brett ist eine Strasse von Alter 20 bis 67, ein Feld pro Lebensjahr. Auf
Entscheidungsfeldern teilt sie sich in Spuren (eine je Option), die später wieder
zusammenlaufen. Auf Schicksalsfeldern wird eine Ereigniskarte gezogen. Jede Wahl und
jedes Ereignis wird als Plan aus den Szenario-Bausteinen ins Finanzmodell eingespeist
(Monte-Carlo-SDE mit Lebenszyklus). Gewertet werden Net Worth und Lebensqualität.

Ohne GUI spielbar (Autopilot), erzeugt die Lebensbilanz als Grafik:
    venv/bin/python sde/lebensweg.py --players 3 --seed 7
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np
import pandas as pd

from interventions import (DepotShock, Expense, Income, Invest, OneOff, Plan, Property, compile_plan)
from scenarios import SCENARIOS
from simulate import ROOT, Model, SimConfig, SimResult, prepare, simulate_profile

START_AGE, END_AGE, SIM_END_AGE = 20, 67, 85
# Spielannahmen (illustrativ): Daten haben 8'163 CHF Einstiegslohn und 55 % Sparquote.
GAME_DEFAULTS = {"entry_income": 6000.0, "savings_rate_work": 0.15, "adaptive_cut": 0.30,
                 "lifestyle_share": 0.60, "retirement_expense_ratio": 0.80}
PLAYER_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]   # Referenzpalette, Slots 1-4

Build = Callable[["Player", int, SimConfig], Plan]   # (Spieler, Startmonat, aktuelle Config) -> Plan


# ---------------------------------------------------------------------------
# Bausteine für Optionen und Karten
# ---------------------------------------------------------------------------
def months(age: int) -> int:
    return (age - START_AGE) * 12


def sc(sid: str, **over) -> Build:
    """Szenario aus der Bibliothek als Baustein, Parameter-Overrides möglich."""
    def build(pl: "Player", s: int, cfg: SimConfig) -> Plan:
        d = SCENARIOS[sid]
        p = {**d.defaults(pl.row), **over}
        for k, v in d.params.items():
            if v.kind == "int":
                p[k] = int(round(p[k]))
        return d.build(pl.row, SimpleNamespace(**p), s, cfg)
    return build


def custom(fn: Callable[["Player", int, SimConfig], list], cfg: dict | None = None) -> Build:
    return lambda pl, s, c: Plan(fn(pl, s, c), dict(cfg or {}), {})


def combine(*builds: Build) -> Build:
    def build(pl, s, c):
        out = Plan()
        for b in builds:
            p = b(pl, s, c)
            out.interventions += p.interventions
            out.cfg.update(p.cfg)
            out.row.update(p.row)
        return out
    return build


NOTHING: Build = lambda pl, s, c: Plan()  # noqa: E731


@dataclass
class Option:
    label: str
    text: str
    lq: int                      # Lebensqualitäts-Punkte
    build: Build = NOTHING
    flags: dict = field(default_factory=dict)
    icon: str = ""
    need_cash: float = 0.0       # liquide Mittel (Cash + Depot, Median), die vorhanden sein müssen
    need_text: str = ""


@dataclass
class Decision:
    age: int
    title: str
    question: str
    options: list[Option]
    icon: str = ""


@dataclass
class Card:
    key: str
    title: str
    text: str
    weight: float
    lq: int
    build: Build = NOTHING
    when: Callable[["Player"], bool] = lambda pl: True
    good: bool = False


# ---------------------------------------------------------------------------
# Entscheidungen (Lebensphasen)
# ---------------------------------------------------------------------------
DECISIONS: list[Decision] = [
    Decision(20, "Ausbildung", "Wie geht es nach dem Bachelor weiter?", [
        Option("Master", "2 Jahre Studium, Gebühren, danach 10 % mehr Lohn (S001)", 2, sc("S001"), icon="🎓"),
        Option("Direkt arbeiten", "Sofort ins Berufsleben (S011)", 1,
               lambda pl, s, c: Plan(cfg={"study_years_left": s / 12}), icon="💼"),
        Option("Doktorat", "4 Jahre Doktorandenlohn, danach 15 % mehr (S007)", 3, sc("S007"), icon="🔬"),
    ]),
    Decision(23, "Karrierestart", "Wie startest du ins Berufsleben?", [
        Option("Lohn verhandeln", "5 % mehr Lohn ab jetzt (S012)", 1, sc("S012"), icon="🤝"),
        Option("Freelance", "20 % mehr Umsatz, 900 CHF/Mt. eigene Sozialabgaben bis zur Pension, "
               "schwankendes Einkommen (S015)", 2,
               lambda pl, s, c: Plan([Income(s, months(int(pl.retirement_age)), factor=1.2),
                                      Expense(s, months(int(pl.retirement_age)), add=900)], {},
                                     {"sigma_C_chf_month": pl.row.sigma_C_chf_month * 2}),
               flags={"freelance": True}, icon="🧑‍💻"),
        Option("Startup gründen", "10k Eigenkapital, 2 Jahre Mini-Lohn, danach +20 % (S111)", 3,
               sc("S111", capital=10000), flags={"founder": True}, icon="🚀",
               need_cash=10000, need_text="10k Eigenkapital"),
        Option("Sicherer Job", "Standardstelle, nichts Besonderes", 0, icon="🏢"),
    ]),
    Decision(26, "Wohnen", "Wie willst du wohnen?", [
        Option("WG", "Kosten teilen, 400 CHF/Mt. gespart (S032)", 1, sc("S032", saving=400), icon="🛋️"),
        Option("Eigene Wohnung", "Mehr Platz, 600 CHF mehr Miete (S031)", 3, sc("S031", add=600), icon="🏠"),
        Option("Bleiben wie bisher", "Keine Änderung", 0, icon="📦"),
    ]),
    Decision(28, "Geld anlegen", "Was machst du mit deinen Ersparnissen?", [
        Option("Sparplan ETF", "500 CHF pro Monat ins Depot (S061)", 0,
               custom(lambda pl, s, c: [Invest(s, None, 500)]), {"investor": True}, icon="📈"),
        Option("Notgroschen + Anlage", "6 Monatsausgaben Reserve, Rest zu 50 % anlegen (S051)", 1,
               lambda pl, s, c: Plan(cfg={"buffer_months": 6.0, "invest_share": 0.5}), {"investor": True}, icon="🛟"),
        Option("Einzelaktien", "500 CHF/Mt. in wenige Titel, 30 % Volatilität (S069)", 1,
               custom(lambda pl, s, c: [Invest(s, None, 500)], {"sigma_I": 0.30}), {"investor": True}, icon="🎲"),
        Option("Alles aufs Konto", "Bleibt Cash mit 0,5 % Zins", 0, icon="🏦"),
    ]),
    Decision(30, "Mobilität", "Wie bist du unterwegs?", [
        Option("Auto kaufen", "30k Kaufpreis, 520 CHF/Mt. Unterhalt (S042)", 3, sc("S042"), {"car": True}, icon="🚗",
               need_cash=30000, need_text="30k bar"),
        Option("Sportwagen", "80k Kaufpreis, 900 CHF/Mt. Unterhalt", 5, sc("S042", price=80000, running=900),
               {"car": True}, icon="🏎️", need_cash=80000, need_text="80k bar"),
        Option("ÖV & Velo", "Kein Auto", 1, icon="🚲"),
    ]),
    Decision(32, "Familie", "Wie sieht dein Privatleben aus?", [
        Option("Zusammenziehen", "Haushalt teilen, 800 CHF/Mt. gespart (S081)", 3, sc("S081", saving=800), {"partner": True}, icon="💞"),
        Option("Kinder", "Mit Partner: Haushalt teilen, Elternzeit, 4 Jahre Kita, 20 Jahre Kinderkosten "
               "(S081, S082, S083)", 6,
               combine(sc("S081", saving=800), sc("S083"), sc("S082", cost=1200), custom(lambda pl, s, c: [Expense(s, s + 240, add=700)])),
               {"kids": True, "partner": True}, icon="👶"),
        Option("Single bleiben", "Freiheit, volle Fixkosten", 1, icon="🧘"),
    ]),
    Decision(35, "Wohneigentum", "Kaufst du eine Immobilie?", [
        Option("Wohnung kaufen", "600k, 20 % Eigenkapital, Hypothek 2 % (S033)", 3,
               custom(lambda pl, s, c: [Property(s, 600_000, rent_saved=1800)]), {"home": True}, icon="🏢",
               need_cash=600_000 * 0.23, need_text="20 % Eigenkapital + 3 % Gebühren = 138k"),
        Option("Haus kaufen", "900k, 20 % Eigenkapital, Hypothek 2 % (S033)", 5,
               custom(lambda pl, s, c: [Property(s, 900_000, rent_saved=2200)]), {"home": True}, icon="🏡",
               need_cash=900_000 * 0.23, need_text="20 % Eigenkapital + 3 % Gebühren = 207k"),
        Option("Weiter mieten", "Flexibel bleiben", 1, icon="🔑"),
    ]),
    Decision(40, "Lebensmitte", "Was ändert sich mit 40?", [
        Option("Weiterbildung", "12k Kosten, danach 10 % mehr Lohn (S006)", 2, sc("S006"), icon="📚"),
        Option("Teilzeit 80 %", "Mehr Freizeit, 20 % weniger Lohn (S017)", 4, sc("S017"), icon="🌿"),
        Option("Umzug nach Zürich", "10 % mehr Lohn, 500 CHF mehr Miete (S021)", 2, sc("S021"), icon="🏙️"),
        Option("Alles bleibt", "Keine Änderung", 0, icon="⏸️"),
    ]),
    Decision(45, "Auszeit", "Gönnst du dir eine Pause?", [
        Option("Sabbatical", "6 Monate unbezahlt reisen (S044)", 5, sc("S044"), icon="✈️",
               need_cash=30000, need_text="30k Reserve"),
        Option("Nebenprojekt", "500 CHF/Mt. Zusatzeinkommen (S112)", 2, sc("S112"), icon="🛠️"),
        Option("Weiterarbeiten", "Keine Pause", 0, icon="⚙️"),
    ]),
    Decision(50, "Vorsorge", "Wie sorgst du fürs Alter vor?", [
        Option("Säule 3a", "605 CHF/Mt. bis zur Pension, Steuerersparnis (S093)", 1, sc("S093"), icon="🐷"),
        Option("Defensiv umschichten", "Mehr Obligationen: 3 % Rendite, 6 % Volatilität (S063)", 1,
               lambda pl, s, c: Plan(cfg={"mu_I": 0.03, "sigma_I": 0.06}), icon="🛡️"),
        Option("Nichts ändern", "Weiter wie bisher", 0, icon="➖"),
    ]),
    Decision(58, "Pensionierung", "Wann gehst du in Rente?", [
        Option("Mit 60", "Früher frei, 40 % des Lohns als Rente (S091)", 5, sc("S091"), icon="🏖️"),
        Option("Mit 65", "Regulär, 50 % des Lohns", 2, icon="🎂"),
        Option("Mit 67", "Länger arbeiten, 55 % des Lohns (S092)", 0, sc("S092"), icon="🏃"),
    ]),
]
DECISION_ICONS = {"Ausbildung": "🎓", "Karrierestart": "💼", "Wohnen": "🏠", "Geld anlegen": "💰",
                  "Mobilität": "🚦", "Familie": "👪", "Wohneigentum": "🔑", "Lebensmitte": "🧭",
                  "Auszeit": "🌴", "Vorsorge": "🐷", "Pensionierung": "🎉"}
for _d in DECISIONS:
    _d.icon = DECISION_ICONS.get(_d.title, "")
DECISION_AGES = {d.age: d for d in DECISIONS}


def working(pl: "Player") -> bool:
    return pl.age < pl.retirement_age


CARDS: list[Card] = [
    Card("jobloss", "Jobverlust", "Deine Stelle wird gestrichen: 6 Monate mit 70 % Taggeld (S014).",
         3, -3, sc("S014"), working),
    Card("promotion", "Beförderung", "Du wirst befördert: 10 % mehr Lohn (S013).",
         3, 2, sc("S013", after=0, raise_=0.10), working, good=True),
    Card("crash", "Börsencrash", "Die Märkte fallen: Depot −30 % (S065).", 2, -1, sc("S065", when=0)),
    Card("boom", "Börsenboom", "Starke Börsenjahre: Depot +20 %.", 2, 1,
         custom(lambda pl, s, c: [DepotShock(s, 0.20)]), good=True),
    Card("inheritance", "Erbschaft", "Eine Tante vererbt dir 30'000 CHF (S057).", 1, 1,
         sc("S057", amount=30000, when=0), good=True),
    Card("emergency", "Notfall", "Unerwartete Ausgabe von 10'000 CHF (S048).", 3, -1, sc("S048", when=0)),
    Card("illness", "Krankheit", "6 Monate arbeitsunfähig, Versicherung zahlt 80 % (S090).",
         2, -4, sc("S090", months=6), working),
    Card("bonus", "Bonus", "Gutes Geschäftsjahr: 5'000 CHF Bonus.", 3, 1,
         custom(lambda pl, s, c: [OneOff(s, 5000)]), working, good=True),
    Card("repair", "Hausreparatur", "Das Dach muss neu: 25'000 CHF (S040).", 2, -2,
         custom(lambda pl, s, c: [OneOff(s, -25000)]), lambda pl: pl.flags.get("home", False)),
    Card("accident", "Autounfall", "Blechschaden und Selbstbehalt: 5'000 CHF.", 2, -2,
         custom(lambda pl, s, c: [OneOff(s, -5000)]), lambda pl: pl.flags.get("car", False)),
    Card("rent", "Mieterhöhung", "Die Miete steigt jährlich 2 % über Inflation (S037).", 2, -1,
         sc("S037", growth=0.02), lambda pl: not pl.flags.get("home", False)),
    Card("energy", "Energiepreisschock", "2 Jahre 150 CHF/Mt. mehr für Energie (S050).", 1, -1, sc("S050")),
    Card("braces", "Zahnspange", "Für die Kinder: 6'000 CHF.", 1, -1,
         custom(lambda pl, s, c: [OneOff(s, -6000)]), lambda pl: pl.flags.get("kids", False)),
    Card("sidegig", "Nebenjob-Anfrage", "Ein Kunde bietet 2 Jahre lang 800 CHF/Mt. extra.", 2, 1,
         custom(lambda pl, s, c: [Income(s, s + 24, add=800)]), working, good=True),
]


# ---------------------------------------------------------------------------
# Brett
# ---------------------------------------------------------------------------
@dataclass
class Field:
    age: int
    kind: str                     # start | decision | event | year | finish
    decision: Decision | None = None
    lane_of: int | None = None    # Alter der Entscheidung, deren Spuren hier verlaufen
    n_lanes: int = 1


def lane_span(dec_age: int) -> list[int]:
    """Alter, auf denen die Spuren einer Entscheidung getrennt verlaufen (max. 2 Felder)."""
    ages = sorted(DECISION_AGES) + [END_AGE]
    nxt = ages[ages.index(dec_age) + 1]
    return list(range(dec_age + 1, dec_age + 1 + min(2, nxt - dec_age - 1)))


def build_board() -> list[Field]:
    lanes = {a: d for d in DECISIONS for a in lane_span(d.age)}
    board = []
    for age in range(START_AGE, END_AGE + 1):
        if age in DECISION_AGES:
            f = Field(age, "decision", DECISION_AGES[age])
        elif age == END_AGE:
            f = Field(age, "finish")
        elif age % 2 == 1 or age in (44, 52, 56, 64):
            f = Field(age, "event")
        else:
            f = Field(age, "year")
        if age in lanes:
            f.lane_of, f.n_lanes = lanes[age].age, len(lanes[age].options)
        board.append(f)
    return board


BOARD = build_board()


# ---------------------------------------------------------------------------
# Spieler und Finanzkern
# ---------------------------------------------------------------------------
@dataclass
class Player:
    name: str
    color: str
    profile_id: str
    row: pd.Series
    auto: bool = False
    age: int = START_AGE
    lanes: dict = field(default_factory=dict)     # Entscheidungsalter -> Optionsindex
    choices: list = field(default_factory=list)   # (Alter, Decision, Option)
    events: list = field(default_factory=list)    # (Alter, Card)
    plans: list = field(default_factory=list)     # (Startmonat, Build)
    flags: dict = field(default_factory=dict)
    lq: int = 0
    history: list = field(default_factory=list)   # (Alter, P25, Median, P75)
    result: SimResult | None = None
    done: bool = False
    retirement_age: float = 65.0

    def lane_at(self, age: int) -> int | None:
        f = BOARD[age - START_AGE]
        return self.lanes.get(f.lane_of) if f.lane_of is not None else None


class Engine:
    """Rechnet die Lebensverläufe der Spieler mit dem SDE-Modell."""

    def __init__(self, model: Model, n_paths: int = 300, seed: int = 0, **game_cfg):
        self.model = model
        # Jobverlust kommt im Spiel über Ereigniskarten, nicht zusätzlich über die Rate.
        # Spielannahmen (GAME_DEFAULTS) statt synthetischer Datenwerte, sonst landet jeder
        # Lebensweg bei mehreren Millionen.
        self.cfg = replace(model.defaults, job_loss_rate=0.0, n_paths=n_paths, seed=seed,
                           months=months(SIM_END_AGE), **{**GAME_DEFAULTS, **game_cfg})

    def player_row(self, profile_id: str) -> pd.Series:
        row = self.model.params.loc[profile_id].copy()
        row["age_at_start"] = START_AGE
        return row

    def merged(self, pl: Player, extra: list | None = None) -> tuple[pd.Series, SimConfig, Plan]:
        cfg, row, plan = self.cfg, pl.row.copy(), Plan()
        for s, b in list(pl.plans) + list(extra or []):
            p = b(pl, s, cfg)
            plan.interventions += p.interventions
            cfg = replace(cfg, **p.cfg)
            for k, v in p.row.items():
                row[k] = v
        row["NW0"] = row.C0 + row.I0 - row.L0
        return row, cfg, plan

    def simulate(self, pl: Player, extra: list | None = None, n_paths: int | None = None) -> SimResult:
        row, cfg, plan = self.merged(pl, extra)
        if n_paths:
            cfg = replace(cfg, n_paths=n_paths)
        return simulate_profile(row, self.model, cfg, plan=compile_plan(plan, cfg.months))

    def refresh(self, pl: Player) -> None:
        pl.result = self.simulate(pl)
        q = self.nw_quantiles(pl.result, pl.age)
        pl.history.append((pl.age, *q))

    @staticmethod
    def nw_quantiles(res: SimResult, age: int, qs=(0.25, 0.5, 0.75)) -> tuple:
        t = min(months(age), res.NW.shape[1] - 1)
        return tuple(float(v) for v in np.quantile(res.NW[:, t], qs))

    def preview(self, pl: Player, decision: Decision, at_age: int = END_AGE) -> list[tuple[float, float]]:
        """Median-NW mit at_age je Option und Differenz zur ersten 'nichts tun'-ähnlichen Basis."""
        s = months(decision.age)
        base = self.simulate(pl, n_paths=200)
        b = self.nw_quantiles(base, at_age)[1]
        out = []
        for opt in decision.options:
            r = self.simulate(pl, [(s, opt.build)], n_paths=200)
            m = self.nw_quantiles(r, at_age)[1]
            out.append((m, m - b))
        return out


# ---------------------------------------------------------------------------
# Spielablauf (ohne GUI nutzbar)
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, model: Model, players: list[tuple[str, str, bool]], seed: int | None = None,
                 n_paths: int = 300, **game_cfg):
        self.rng = random.Random(seed)
        self.engine = Engine(model, n_paths=n_paths, seed=seed or 0, **game_cfg)
        self.players = [Player(n, PLAYER_COLORS[i % 4], pid, self.engine.player_row(pid), auto)
                        for i, (n, pid, auto) in enumerate(players)]
        for pl in self.players:
            self.engine.refresh(pl)
        self.turn = 0
        self.log: list[str] = []

    @property
    def current(self) -> Player:
        return self.players[self.turn]

    def over(self) -> bool:
        return all(p.done for p in self.players)

    def next_turn(self) -> None:
        if self.over():
            return
        for _ in range(len(self.players)):
            self.turn = (self.turn + 1) % len(self.players)
            if not self.current.done:
                return

    def roll(self) -> int:
        return self.rng.randint(1, 3)

    def path(self, pl: Player, steps: int) -> list[int]:
        """Alter, die gefahren werden; Halt an Entscheidungen und am Ziel."""
        ages = []
        for _ in range(steps):
            a = pl.age + 1 if not ages else ages[-1] + 1
            if a > END_AGE:
                break
            ages.append(a)
            if a in DECISION_AGES or a == END_AGE:
                break
        return ages

    def field(self, age: int) -> Field:
        return BOARD[age - START_AGE]

    def liquid(self, pl: Player) -> float:
        t = min(months(pl.age), pl.result.C.shape[1] - 1)
        return float(np.median(pl.result.C[:, t] + pl.result.I[:, t]))

    def allowed(self, pl: Player, opt: Option) -> str | None:
        """None = wählbar, sonst Grund der Sperre (Tragbarkeit)."""
        if opt.need_cash and self.liquid(pl) < opt.need_cash:
            return f"Gesperrt: braucht {opt.need_text} (du hast {self.liquid(pl) / 1000:,.0f}k)".replace(",", "'")
        return None

    def pending_decision(self, pl: Player) -> Decision | None:
        """Entscheidung auf dem aktuellen Feld, die noch offen ist (z. B. Start mit 20)."""
        d = DECISION_AGES.get(pl.age)
        return d if d is not None and d.age not in pl.lanes else None

    def choose(self, pl: Player, decision: Decision, idx: int) -> Option:
        opt = decision.options[idx]
        pl.lanes[decision.age] = idx
        pl.choices.append((decision.age, decision, opt))
        pl.plans.append((months(decision.age), opt.build))
        pl.flags.update(opt.flags)
        pl.lq += opt.lq
        pl.retirement_age = opt.build(pl, months(decision.age), self.engine.cfg).cfg.get(
            "retirement_age", pl.retirement_age)
        self.log.append(f"{pl.name} ({decision.age}): {decision.title} → {opt.label}")
        self.engine.refresh(pl)
        return opt

    def draw_card(self, pl: Player) -> Card:
        deck = [c for c in CARDS if c.when(pl)]
        card = self.rng.choices(deck, weights=[c.weight for c in deck])[0]
        pl.events.append((pl.age, card))
        pl.plans.append((months(pl.age), card.build))
        pl.lq += card.lq
        self.log.append(f"{pl.name} ({pl.age}): {card.title}")
        self.engine.refresh(pl)
        return card

    def arrive(self, pl: Player, age: int) -> Field:
        pl.age = age
        f = self.field(age)
        if f.kind == "finish":
            pl.done = True
            self.log.append(f"{pl.name} erreicht mit {age} den Ruhestand.")
        return f

    def auto_choice(self, pl: Player, decision: Decision) -> int:
        ok = [i for i, o in enumerate(decision.options) if self.allowed(pl, o) is None]
        return self.rng.choice(ok)

    def play_turn_auto(self) -> None:
        pl = self.current
        d = self.pending_decision(pl)
        if d is not None:
            self.choose(pl, d, self.auto_choice(pl, d))
        for age in self.path(pl, self.roll()):
            f = self.arrive(pl, age)
        if f.kind == "decision":
            self.choose(pl, f.decision, self.auto_choice(pl, f.decision))
        elif f.kind == "event":
            self.draw_card(pl)
        else:
            pl.history.append((pl.age, *self.engine.nw_quantiles(pl.result, pl.age)))
        self.next_turn()

    def finish(self, n_paths: int = 1000) -> None:
        for pl in self.players:
            pl.result = self.engine.simulate(pl, n_paths=n_paths)

    def ranking(self) -> pd.DataFrame:
        rows = []
        for pl in self.players:
            q = self.engine.nw_quantiles(pl.result, END_AGE, (0.05, 0.5, 0.95))
            rows.append({"Spieler": pl.name, "NW mit 67 (Median)": q[1], "P5": q[0], "P95": q[2],
                         "Lebensqualität": pl.lq, "Punkte": round(q[1] / 100_000 + pl.lq, 1)})
        return pd.DataFrame(rows).sort_values("Punkte", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Lebensbilanz als Grafik
# ---------------------------------------------------------------------------
def life_figure(game: Game, fig=None):
    """Net Worth über das Leben, Entscheidungsgraph mit Routen, Rangliste."""
    import matplotlib.ticker as mtick
    from matplotlib.figure import Figure

    import plots  # noqa: F401  (setzt den Stil)
    from plots import CHF_K, GRID, INK, INK_2, NEUTRAL, SURFACE, kchf

    fig = fig or Figure(figsize=(16, 11), facecolor=SURFACE, layout="constrained")
    gs = fig.add_gridspec(2, 3, height_ratios=[1.1, 1])
    a_nw = fig.add_subplot(gs[0, :])
    a_graph = fig.add_subplot(gs[1, :2])
    a_rank = fig.add_subplot(gs[1, 2])
    fig.suptitle("Lebensweg · Lebensbilanz", x=0.01, ha="left", fontsize=16, fontweight="bold", color=INK)

    # --- Net Worth über das Leben ---
    for pl in game.players:
        res = pl.result
        ages = START_AGE + np.arange(res.NW.shape[1]) / 12
        q25, q50, q75 = np.quantile(res.NW, [0.25, 0.5, 0.75], axis=0)
        a_nw.fill_between(ages, q25, q75, color=pl.color, alpha=0.15, lw=0)
        a_nw.plot(ages, q50, color=pl.color, lw=2.2, label=pl.name)
        for age, dec, opt in pl.choices:
            y = q50[months(age)]
            a_nw.scatter(age, y, marker="D", s=46, color=pl.color, edgecolor=SURFACE, lw=1.5, zorder=4)
        for age, card in pl.events:
            y = q50[months(age)]
            a_nw.scatter(age, y, marker="^" if card.good else "v", s=60, color=pl.color,
                         edgecolor=INK, lw=0.6, zorder=5)
        a_nw.annotate(f"{pl.name}: {kchf(q50[-1])}", (ages[-1], q50[-1]), xytext=(6, 0),
                      textcoords="offset points", va="center", fontsize=9, color=INK_2)
    a_nw.axvline(END_AGE, color=NEUTRAL, ls=":", lw=1)
    a_nw.annotate("Ziel des Bretts (67)", (END_AGE, 1), xycoords=("data", "axes fraction"),
                  xytext=(4, -4), textcoords="offset points", va="top", fontsize=8.5, color=INK_2)
    a_nw.axhline(0, color=INK, lw=0.8)
    a_nw.set_xlim(START_AGE, SIM_END_AGE + 4)
    a_nw.set_xlabel("Alter")
    a_nw.yaxis.set_major_formatter(CHF_K)
    a_nw.set_title("Net Worth über das Leben (Median, Band 25–75 %) · ◆ Entscheidung  ▲ gutes  ▼ schlechtes Ereignis")
    a_nw.legend(loc="upper left", fontsize=9)

    # --- Entscheidungsgraph mit Routen ---
    a_graph.set_title("Lebensweg-Graph: Entscheidungen, Optionen und gefahrene Routen")
    a_graph.grid(False)
    for sp in a_graph.spines.values():
        sp.set_visible(False)
    xs = {d.age: i for i, d in enumerate(DECISIONS)}
    node_y = {}
    for d in DECISIONS:
        k = len(d.options)
        for j, o in enumerate(d.options):
            node_y[(d.age, j)] = (k - 1) / 2 - j
    # alle möglichen Kanten (Modellstruktur)
    for d0, d1 in zip(DECISIONS[:-1], DECISIONS[1:]):
        for j0 in range(len(d0.options)):
            for j1 in range(len(d1.options)):
                a_graph.plot([xs[d0.age], xs[d1.age]], [node_y[(d0.age, j0)], node_y[(d1.age, j1)]],
                             color=GRID, lw=0.8, zorder=1)
    # Routen der Spieler
    n = len(game.players)
    for i, pl in enumerate(game.players):
        off = (i - (n - 1) / 2) * 0.06
        pts = [(xs[a], node_y[(a, pl.lanes[a])] + off) for a in sorted(pl.lanes)]
        if pts:
            a_graph.plot(*zip(*pts), color=pl.color, lw=2.6, alpha=0.9, zorder=3, label=pl.name,
                         solid_capstyle="round")
    for d in DECISIONS:
        a_graph.annotate(f"{d.age}\n{d.title}", (xs[d.age], 1.95), ha="center", va="bottom", fontsize=8,
                         color=INK, fontweight="bold")
        for j, o in enumerate(d.options):
            chosen = [pl for pl in game.players if pl.lanes.get(d.age) == j]
            a_graph.scatter(xs[d.age], node_y[(d.age, j)], s=260 if chosen else 120,
                            color=SURFACE, edgecolor=INK if chosen else NEUTRAL, lw=1.4, zorder=4)
            a_graph.annotate(o.label, (xs[d.age], node_y[(d.age, j)]), xytext=(0, -14),
                             textcoords="offset points", ha="center", va="top", fontsize=7.2,
                             color=INK if chosen else INK_2)
    a_graph.set_xlim(-0.6, len(DECISIONS) - 0.4)
    a_graph.set_ylim(-2.2, 2.6)
    a_graph.set_xticks([])
    a_graph.set_yticks([])
    a_graph.legend(loc="lower left", fontsize=8.5, ncol=n)

    # --- Rangliste ---
    rk = game.ranking()
    y = np.arange(len(rk))[::-1]
    colors = [next(p.color for p in game.players if p.name == nm) for nm in rk.Spieler]
    a_rank.barh(y, rk["NW mit 67 (Median)"], color=colors, height=0.55)
    for yi, (_, r) in zip(y, rk.iterrows()):
        a_rank.annotate(f"{kchf(r['NW mit 67 (Median)'])} · LQ {r['Lebensqualität']} · {r['Punkte']} P.",
                        (max(r["NW mit 67 (Median)"], 0), yi), xytext=(6, 0), textcoords="offset points",
                        va="center", fontsize=9, color=INK_2)
    a_rank.set_yticks(y, [f"{i + 1}. {nm}" for i, nm in enumerate(rk.Spieler)])
    a_rank.xaxis.set_major_formatter(CHF_K)
    a_rank.set_title("Rangliste (Punkte = NW/100k + LQ)")
    a_rank.set_xlim(right=max(rk["NW mit 67 (Median)"].max(), 1) * 1.6)
    return fig


def student_profiles(model: Model) -> pd.DataFrame:
    p = model.params
    return p[p.employment_status == "student"].sort_values("age_at_start")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--players", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=ROOT / "output" / "lebensweg_bilanz.png")
    args = ap.parse_args()

    model = prepare()
    studs = student_profiles(model)
    names = ["Alexia", "Ben", "Chiara", "Dario"]
    pids = ["P00001"] + [p for p in studs.index if p != "P00001"]
    game = Game(model, [(names[i], pids[i], True) for i in range(args.players)], seed=args.seed)
    while not game.over():
        game.play_turn_auto()
    game.finish()
    print("\n".join(game.log))
    print(game.ranking().round(0).to_string(index=False))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    life_figure(game).savefig(args.out, dpi=130)
    print(args.out)


if __name__ == "__main__":
    main()
