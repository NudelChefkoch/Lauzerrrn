"""Game layer "Lebensweg": one station per year, the player CHOOSES (no dice), very gamified.

* Decisions are grouped by category; locked options show why (e.g. "Eigenkapital fehlt").
* Every card shows the twin's preview (median net worth at the end, range, credit risk).
* XP, levels, happiness meter, achievements and quests make the trade-offs tangible.
* The played life is path 0 of the Monte Carlo run; ``fixed_until`` makes all other paths share
  its past, so the fan always shows the futures still possible from where the player stands.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .calibration import Calibration, Person
from .config import Assumptions, EMPLOYED, SELF_EMPLOYED, STUDENT, UNEMPLOYED
from .engine import Result, simulate
from .scenarios import (Event, ExpenseChange, HouseBuy, Job, JobChange, OneOff, SelfEmployment, StrategyChange,
                        Study)

YEARS = 15
N_PATHS = 400


# ---------------------------------------------------------------- snapshot & context
@dataclass(frozen=True)
class Snapshot:
    month: int
    state: int
    income: float
    cash: float
    portfolio: float
    debt: float
    net_worth: float
    liquid: float


def snapshot(res: Result, month: int) -> Snapshot:
    p = res.path0
    m = min(month, res.plan.months - 1)
    return Snapshot(month, int(p["state"][month]), float(res.plan.income[m]), float(p["cash"][month]),
                    float(p["portfolio"][month]), float(p["debt"][month]), float(p["net_worth"][month]),
                    float(p["liquid"][month]))


@dataclass(frozen=True)
class Ctx:
    snap: Snapshot
    done: frozenset[str]
    age: int
    kids: int
    finished: frozenset[str]     # completed degrees: "bachelor", "master", "lehre"


# ---------------------------------------------------------------- decision cards
@dataclass(frozen=True)
class Option:
    key: str
    cat: str
    emoji: str
    title: str
    text: str
    make: Callable[[int, Snapshot], list[Event]]
    lock: Callable[[Ctx], str | None] = lambda c: None   # None = available, else reason
    joy: int = 0
    xp: int = 50
    once: bool = True


CATS = ["🎓 Bildung", "💼 Karriere", "🏡 Wohnen", "👨‍👩‍👧 Familie", "🏝️ Auszeit", "💰 Geld"]


def _studying(c: Ctx) -> str | None:
    return "Du studierst gerade" if c.snap.state == STUDENT and ({"bachelor", "master", "lehre"} & c.done) else None


def _house(price: int) -> Callable[[Ctx], str | None]:
    def f(c: Ctx) -> str | None:
        if c.snap.state not in (EMPLOYED, SELF_EMPLOYED):
            return "Erst ein festes Einkommen"
        need = 0.22 * price
        return None if c.snap.liquid >= need else f"Eigenkapital fehlt: CHF {need - c.snap.liquid:,.0f}".replace(",", "'")
    return f


def _job_lock(req: str | None) -> Callable[[Ctx], str | None]:
    def f(c: Ctx) -> str | None:
        if c.snap.state == EMPLOYED:
            return "Du hast schon einen Job"
        if _studying(c):
            return _studying(c)
        if req and req not in c.finished and not (req == "abschluss" and c.finished):
            return {"abschluss": "Braucht Bachelor oder Lehre", "master": "Braucht einen Master"}[req]
        return None
    return f


OPTIONS: list[Option] = [
    # ---- Bildung
    Option("bachelor", CATS[0], "🎓", "Bachelor", "3 Jahre Uni, CHF 1'500 Gebühren/Jahr. Danach Einstieg mit CHF 5'200.",
           lambda t, s: [Study(t, 36, 1500, None, 5200, 800, "Bachelor", "Bachelor-Abschluss")],
           lambda c: "Schon gemacht" if {"bachelor", "lehre"} & c.done else None, joy=1, xp=100),
    Option("master", CATS[0], "🎓", "Master", "2 Jahre, CHF 1'500/Jahr. Danach Einstieg mit CHF 6'300.",
           lambda t, s: [Study(t, 24, 1500, None, 6300, 1000, "Master", "Master-Abschluss")],
           lambda c: None if "bachelor" in c.finished and "master" not in c.done else
           ("Schon gemacht" if "master" in c.done else "Erst Bachelor abschliessen"), joy=1, xp=120),
    Option("lehre", CATS[0], "🛠️", "Lehre", "3 Jahre, Lehrlingslohn CHF 900. Danach Fachkraft mit CHF 5'000.",
           lambda t, s: [Study(t, 36, 0, 900, 5000, 600, "Lehre", "Lehrabschluss")],
           lambda c: "Schon gemacht" if {"bachelor", "lehre"} & c.done else ("Nur bis 25" if c.age > 25 else None), joy=1, xp=100),
    # ---- Karriere
    Option("job_start", CATS[1], "🛒", "Einstiegsjob", "Sofort Geld verdienen: CHF 4'300 netto, eigene Wohnung +CHF 800/Monat.",
           lambda t, s: [Job(t, 4300, 800, "Job: Einstieg")], _job_lock(None), joy=0, xp=60),
    Option("job_office", CATS[1], "🏢", "Bürojob", "CHF 5'800 netto. Braucht Bachelor oder Lehre.",
           lambda t, s: [Job(t, 5800, 900, "Job: Büro")], _job_lock("abschluss"), joy=0, xp=80),
    Option("job_tech", CATS[1], "💻", "Tech-Job", "CHF 7'400 netto. Braucht einen Master.",
           lambda t, s: [Job(t, 7400, 1000, "Job: Tech")], _job_lock("master"), joy=1, xp=100),
    Option("switch", CATS[1], "🚀", "Jobwechsel", "+15 % Lohn, 1 Monat ohne Einkommen dazwischen.",
           lambda t, s: [JobChange(t, 0.15, 1, "Jobwechsel")],
           lambda c: None if c.snap.state == EMPLOYED else "Nur mit Job", joy=0, xp=70, once=False),
    Option("course", CATS[1], "📚", "Weiterbildung", "CHF 12'000 jetzt, in 18 Monaten +20 % Lohn.",
           lambda t, s: [OneOff(t, 12_000, "Weiterbildung"), JobChange(t + 18, 0.20, 0, "Beförderung")],
           lambda c: None if c.snap.state == EMPLOYED else "Nur mit Job", joy=-1, xp=90),
    Option("startup", CATS[1], "💡", "Startup gründen", "CHF 20'000 Startkapital, Einkommen ~CHF 6'000, stark schwankend.",
           lambda t, s: [SelfEmployment(t, 6000, 20_000, "Startup")],
           lambda c: None if c.snap.state == EMPLOYED else "Erst Berufserfahrung sammeln", joy=2, xp=120),
    Option("parttime", CATS[1], "⏳", "Teilzeit 80 %", "20 % weniger Lohn, mehr Freizeit.",
           lambda t, s: [JobChange(t, -0.20, 0, "Teilzeit")],
           lambda c: None if c.snap.state == EMPLOYED else "Nur mit Job", joy=2, xp=40),
    # ---- Wohnen
    Option("flat", CATS[2], "🛋️", "Schönere Wohnung", "+CHF 600 Miete pro Monat.",
           lambda t, s: [ExpenseChange(t, 600, "Neue Wohnung")],
           lambda c: None if c.snap.state in (EMPLOYED, SELF_EMPLOYED) else "Erst ein festes Einkommen", joy=2, xp=40),
    Option("buy_flat", CATS[2], "🏢", "Eigentumswohnung", "CHF 550'000 – 20 % Eigenkapital, Hypothek 2 %.",
           lambda t, s: [HouseBuy(t, 550_000, "Kauf: Wohnung")], _house(550_000), joy=3, xp=200),
    Option("buy_house", CATS[2], "🏡", "Haus mit Garten", "CHF 850'000 – 20 % Eigenkapital, Hypothek 2 %.",
           lambda t, s: [HouseBuy(t, 850_000, "Kauf: Haus")], _house(850_000), joy=4, xp=250),
    Option("car", CATS[2], "🚙", "Eigenes Auto", "CHF 25'000 und +CHF 350/Monat Unterhalt.",
           lambda t, s: [OneOff(t, 25_000, "Autokauf"), ExpenseChange(t, 350, "Autokosten")],
           lambda c: None if c.snap.state in (EMPLOYED, SELF_EMPLOYED) else "Erst ein festes Einkommen", joy=2, xp=40),
    # ---- Familie
    Option("wedding", CATS[3], "💍", "Hochzeit", "Fest für CHF 20'000.",
           lambda t, s: [OneOff(t, 20_000, "Hochzeit")], lambda c: None if c.age >= 22 else "Ab 22", joy=4, xp=150),
    Option("child", CATS[3], "👶", "Kind bekommen", "CHF 3'000 Geburt, danach +CHF 1'100/Monat (nach Kinderzulage).",
           lambda t, s: [OneOff(t, 3000, "Kind"), ExpenseChange(t, 1100, "Kinderkosten")],
           lambda c: "Ab 22" if c.age < 22 else ("Maximal 2 Kinder im Spiel" if c.kids >= 2 else None),
           joy=5, xp=200, once=False),
    # ---- Auszeit
    Option("travel", CATS[4], "🌍", "Weltreise", "3 Monate reisen für CHF 7'000.",
           lambda t, s: [OneOff(t, 7000, "Weltreise")], joy=4, xp=80),
    Option("sabbatical3", CATS[4], "🏝️", "Auszeit 3 Monate", "3 Monate ohne Lohn, danach gleicher Job.",
           lambda t, s: [JobChange(t, 0.0, 3, "Auszeit")],
           lambda c: None if c.snap.state == EMPLOYED else "Nur mit Job", joy=3, xp=60, once=False),
    Option("sabbatical12", CATS[4], "🏖️", "Sabbatjahr", "12 Monate ohne Lohn, danach gleicher Job.",
           lambda t, s: [JobChange(t, 0.0, 12, "Auszeit")],
           lambda c: None if c.snap.state == EMPLOYED else "Nur mit Job", joy=6, xp=100),
    # ---- Geld
    Option("frugal", CATS[5], "🥦", "Sparsamer leben", "CHF 300 weniger Ausgaben pro Monat.",
           lambda t, s: [ExpenseChange(t, -300, "Sparsamer")], joy=-1, xp=40, once=False),
    Option("risk_up", CATS[5], "📈", "Mehr Risiko", "Portfolio zu 100 % in Aktien.",
           lambda t, s: [StrategyChange(t, 1.0, "100 % Aktien")],
           lambda c: None if c.snap.portfolio > 1000 else "Erst investieren (Portfolio > CHF 1'000)", joy=0, xp=40, once=False),
    Option("risk_down", CATS[5], "🛡️", "Weniger Risiko", "Portfolio zu 25 % in Aktien.",
           lambda t, s: [StrategyChange(t, 0.25, "25 % Aktien")],
           lambda c: None if c.snap.portfolio > 1000 else "Erst investieren (Portfolio > CHF 1'000)", joy=0, xp=40, once=False),
]
STAY = Option("stay", "", "🛣️", "Weiterfahren", "Nichts ändern.", lambda t, s: [], joy=0, xp=10, once=False)
OPTION_BY_KEY = {o.key: o for o in OPTIONS + [STAY]}


def available(ctx: Ctx) -> list[tuple[Option, str | None]]:
    """All options with their lock reason (None = selectable)."""
    out = []
    for o in OPTIONS:
        reason = "Schon gemacht" if (o.once and o.key in ctx.done) else o.lock(ctx)
        out.append((o, reason))
    return out


# ---------------------------------------------------------------- simulation helpers
def play(person: Person, events: list[Event], a: Assumptions, calib: Calibration, seed: int, now_month: int) -> Result:
    return simulate(person, events, YEARS, a, N_PATHS, seed, calib=calib, fixed_until=now_month)


def preview(person: Person, events: list[Event], opt: Option, snap: Snapshot, a: Assumptions,
            calib: Calibration, seed: int) -> dict:
    res = play(person, events + opt.make(snap.month, snap), a, calib, seed, snap.month)
    return {"median": res.metrics["median_net_worth_end"], "p5": res.metrics["p5_net_worth_end"],
            "p95": res.metrics["p95_net_worth_end"], "credit": res.metrics["p_credit_future"]}


# ---------------------------------------------------------------- 3D animations from the plan
def animations(plan, m0: int, m1: int, turn: int, played: set | None = None) -> list[dict]:
    """Events from the month of the decision up to and including the arrival month.
    ``played`` remembers (month, label) pairs so an event on a station boundary animates only once."""
    out = []
    played = played if played is not None else set()
    for t, label in plan.labels:
        if not (m0 <= t <= m1) or (t, label) in played:
            continue
        played.add((t, label))
        if label.endswith("Abschluss"):
            typ = "graduation"
        elif label.startswith("Job") or label in ("Berufseinstieg", "Beförderung"):
            typ = "job"
        elif label == "Startup":
            typ = "startup"
        elif label in ("Auszeit", "Weltreise"):
            typ = "vacation"
        elif label.startswith("Kauf"):
            typ = "house"
        elif label == "Kind":
            typ = "child"
        elif label == "Hochzeit":
            out.append({"id": f"{turn}-{len(out)}", "type": "fate", "emoji": "💍", "label": "Hochzeit!"})
            continue
        else:
            continue
        out.append({"id": f"{turn}-{len(out)}", "type": typ, "label": label})
        if typ == "graduation":   # a finished degree goes straight into the first job
            out.append({"id": f"{turn}-{len(out)}", "type": "job", "label": "Berufseinstieg!"})
    return out


def finished_degrees(plan, month: int) -> frozenset[str]:
    names = {"Bachelor-Abschluss": "bachelor", "Master-Abschluss": "master", "Lehrabschluss": "lehre"}
    return frozenset(names[l] for t, l in plan.labels if l in names and t <= month)


# ---------------------------------------------------------------- gamification
LEVELS = ["Neuling", "Durchstarter/in", "Profi", "Finanz-Ass", "Legende"]


def level(xp: int) -> tuple[int, str, float]:
    lv = min(xp // 400, len(LEVELS) - 1)
    return lv + 1, LEVELS[lv], (xp % 400) / 400 if lv < len(LEVELS) - 1 else 1.0


@dataclass(frozen=True)
class Achievement:
    key: str
    emoji: str
    title: str
    test: Callable[[Ctx, dict], bool]


ACHIEVEMENTS = [
    Achievement("grad", "🎓", "Abschluss geschafft", lambda c, f: bool(c.finished)),
    Achievement("job", "💼", "Erster Job", lambda c, f: c.snap.state == EMPLOYED or f.get("ever_job", False)),
    Achievement("buffer", "🐷", "Notgroschen: 3 Monatsausgaben", lambda c, f: c.snap.cash >= 3 * f["expenses"]),
    Achievement("k10", "💯", "Erste CHF 10'000", lambda c, f: c.snap.net_worth >= 10_000),
    Achievement("k50", "🥈", "50k-Club", lambda c, f: c.snap.net_worth >= 50_000),
    Achievement("k100", "🥇", "100k-Club", lambda c, f: c.snap.net_worth >= 100_000),
    Achievement("debtfree", "🧾", "Schuldenfrei", lambda c, f: f.get("had_credit", False) and f["credit"] <= 0),
    Achievement("investor", "📈", "Investor/in: Portfolio ≥ CHF 20'000", lambda c, f: c.snap.portfolio >= 20_000),
    Achievement("home", "🏡", "Eigene vier Wände", lambda c, f: bool({"buy_flat", "buy_house"} & c.done)),
    Achievement("family", "👶", "Familie gegründet", lambda c, f: c.kids > 0),
    Achievement("balance", "🏝️", "Work-Life-Balance", lambda c, f: bool({"travel", "sabbatical3", "sabbatical12", "parttime"} & c.done)),
    Achievement("happy", "😄", "Glückspilz: Glück ≥ 85", lambda c, f: f["joy"] >= 85),
]


def joy_label(j: int) -> str:
    return "😄" if j >= 80 else "🙂" if j >= 60 else "😐" if j >= 40 else "😟"
