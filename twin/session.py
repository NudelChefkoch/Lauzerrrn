"""Pure-Python game state machine for "YOUR LIFE · YOUR CHOICE".

``GameSession`` holds one player's game and produces exactly the payload described in
``twin/frontend3d/CONTRACT.md`` (phase boot | play | end). Streamlit only hosts it: every action the
client sends goes through :meth:`GameSession.handle`, and :meth:`GameSession.payload` is passed back to the
component. ``seq`` is incremented on every state change; the payload is cached until the state changes.
All numbers in the payload are plain Python ints/floats/None (JSON-serialisable).
"""
from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from . import agent, dashboard, game
from .analysis import tornado
from .calibration import calibrate
from .config import STATE_NAMES, STRATEGY_PRESETS, Assumptions, Strategy
from .game import (ACHIEVEMENTS, CATS, OPTION_BY_KEY, STAY, YEARS, Ctx, animations, available,
                   finished_degrees, joy_label, level, snapshot)

HEIGHT = 860
XP_PER_LEVEL = 400
ACHIEVEMENT_XP = 150
START_JOY = 60
DISCLAIMER = "Synthetic data · not a forecast · not investment advice"

DEFAULT_AVATAR = {"name": "Alex", "gender": "frau", "skin": "rosig", "hair": "lang", "hairColor": "braun",
                  "hat": "keiner", "outfit": "hoodie", "color": "violett", "car": "tuerkis"}

# display texts (the payload keys keep their historical *_de names, see CONTRACT.md)
STATE_DE = {"student": "in education", "employed": "employed", "unemployed": "no job",
            "self_employed": "self-employed", "other": "other"}
STATUS_DE = {"student": "in education", "employed": "employed", "part_time": "part-time",
             "unemployed": "no job", "self_employed": "self-employed", "retired": "retired"}
GOAL_DE = {"Emergency savings": "Rainy-day fund", "Career transition": "Cushion for a job change",
           "Education flexibility": "Education reserve", "Housing deposit": "Home deposit",
           "Long-term financial resilience": "Long-term reserve", "Retirement reserve": "Retirement savings"}

CAT_COLORS = {"bildung": "#2a78d6", "karriere": "#eb6834", "wohnen": "#2f9e44", "familie": "#e87ba4",
              "auszeit": "#1baf7a", "geld": "#eda100"}


# stable internal category keys (used by the client for colours and tabs)
CAT_KEYS = {"Education": "bildung", "Career": "karriere", "Housing": "wohnen", "Family": "familie",
            "Time off": "auszeit", "Money": "geld"}


def _split_cat(cat: str) -> tuple[str, str, str]:
    """'🎓 Education' -> ('bildung', 'Education', '🎓')."""
    emoji, label = cat.split(" ", 1)
    return CAT_KEYS.get(label, label.lower()), label, emoji


CAT_INFO = {c: _split_cat(c) for c in CATS}          # game.CATS label -> (key, label, emoji)

RISK_META = {"konservativ": ("Conservative", "🛡️"), "ausgewogen": ("Balanced", "⚖️"), "risky": ("Bold", "🚀")}


def _risk_text(s: Strategy) -> str:
    months = f"{s.buffer_months:g} {'month' if s.buffer_months == 1 else 'months'}"
    return f"{s.equity_share * 100:.0f} % stocks, {months} rainy-day fund"


def rarity(xp: int) -> str:
    if xp <= 50:
        return "COMMON"
    if xp <= 90:
        return "UNCOMMON"
    if xp <= 140:
        return "RARE"
    if xp < 200:
        return "EPIC"
    return "LEGENDARY"


def _f(x) -> float | None:
    """Plain, finite Python float (None for NaN/inf)."""
    if x is None:
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def _clean(obj):
    """Recursively convert numpy types to plain Python types (JSON-safe, no NaN)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _f(obj)
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    return obj


# ---------------------------------------------------------------- shared simulation cache (across sessions)
@lru_cache(maxsize=256)
def _play(pid: str, events: tuple, a: Assumptions, seed: int, now: int):
    c = calibrate()
    return game.play(c.persons[pid], list(events), a, c, seed, now)


@lru_cache(maxsize=64)
def _drivers(pid: str, events: tuple, a: Assumptions, seed: int) -> list[dict]:
    """Tornado rows (sorted ascending by impact) for the twin chat tool ``what_matters``."""
    c = calibrate()
    return tornado(c.persons[pid], list(events), YEARS, a, c, n_paths=200, seed=seed)[1]


@lru_cache(maxsize=4096)
def _preview(pid: str, events: tuple, key: str, month: int, a: Assumptions, seed: int) -> dict:
    c = calibrate()
    snap = snapshot(_play(pid, events, a, seed, month), month)
    return game.preview(c.persons[pid], list(events), OPTION_BY_KEY[key], snap, a, c, seed)


class GameSession:
    """One player's game. Methods: start, choose, restart, payload, handle."""

    def __init__(self) -> None:
        self.calib = calibrate()
        self.seq = 0
        self.phase = "boot"
        self.avatar = dict(DEFAULT_AVATAR)
        self._handled: set = set()
        self._payload: dict | None = None
        self._boot: dict | None = None
        self._reset_game()

    # ------------------------------------------------------------ state helpers
    def _reset_game(self) -> None:
        self.pid: str | None = None
        self.risk = "ausgewogen"
        self.seed = 0
        self.assumptions = Assumptions()
        self.events: list = []
        self.turn = 0
        self.prev_turn = 0
        self.done: set[str] = set()
        self.badges: dict[int, str] = {}
        self.kids = 0
        self.played: set = set()
        self.xp = 0
        self.joy = START_JOY
        self.history: list[dict] = []          # {turn, key, emoji, title, cat, xp, delta}
        self.anims: list[dict] = []
        self.achieved: set[str] = set()
        self.new_achievements: list[dict] = []
        # Juli's analysis inside the game (CONTRACT "Extension")
        self.groups: list[dict] = []           # decision groups {id, key, emoji, title, cat, turn, start_month, events}
        self.chat: list[dict] = []             # Zwilling-Chat messages (last agent.MAX_MESSAGES kept)
        self.chat_mode: str | None = None      # router of the last answer: 'llm' | 'offline'
        self.dash_open = False
        self.alt: dict | None = None           # {"kind": "moves", "moves": {gid: age}} | {"kind": "option", ...}

    def _changed(self) -> None:
        self.seq += 1
        self._payload = None

    @property
    def person(self):
        return self.calib.persons[self.pid]

    def _res(self, month: int | None = None):
        month = 12 * self.turn if month is None else month
        return _play(self.pid, tuple(self.events), self.assumptions, self.seed, month)

    def _ctx(self, res, month: int) -> Ctx:
        return Ctx(snapshot(res, month), frozenset(self.done), self.person.age + self.turn, self.kids,
                   finished_degrees(res.plan, month))

    def _flags(self, res, month: int) -> dict:
        p = res.path0
        credit_path = p["cash"][:month + 1] + p["portfolio"][:month + 1] - p["liquid"][:month + 1]
        return {"credit": float(credit_path[-1]), "ever_job": bool(np.any(p["state"][:month + 1] == 1)),
                "had_credit": bool(np.any(credit_path > 1)), "expenses": self.person.expenses, "joy": self.joy}

    def _check_achievements(self) -> None:
        """Unlock achievements for the current state (+150 XP each); new ones go to ``new_achievements``."""
        month = 12 * self.turn
        res = self._res(month)
        ctx, flags = self._ctx(res, month), self._flags(res, month)
        self.new_achievements = []
        for a in ACHIEVEMENTS:
            if a.key not in self.achieved and a.test(ctx, flags):
                self.achieved.add(a.key)
                self.xp += ACHIEVEMENT_XP
                self.new_achievements.append({"key": a.key, "emoji": a.emoji, "title": a.title, "xp": ACHIEVEMENT_XP})

    # ------------------------------------------------------------ actions
    def start(self, pid: str, avatar: dict | None = None, risk: str = "ausgewogen", seed: int | None = None) -> None:
        if pid not in self.calib.persons:
            raise KeyError(f"unknown profile {pid!r}")
        risk = risk if risk in STRATEGY_PRESETS else "ausgewogen"
        self._reset_game()
        if avatar:
            self.avatar = {**DEFAULT_AVATAR, **{k: v for k, v in avatar.items() if v is not None}}
        self.pid, self.risk = pid, risk
        self.seed = int(np.random.default_rng().integers(1_000_000)) if seed is None else int(seed)
        self.assumptions = Assumptions(strategy=STRATEGY_PRESETS[risk])
        self.phase = "play"
        self._check_achievements()
        self._post_opener()
        self._changed()

    def choose(self, key: str) -> bool:
        """Play one year with option ``key`` (or 'stay'). Returns False if the move is not allowed."""
        if self.phase != "play" or key not in OPTION_BY_KEY:
            return False
        opt = OPTION_BY_KEY[key]
        m0 = 12 * self.turn
        res = self._res(m0)
        snap = snapshot(res, m0)
        delta = None
        if key != "stay":
            locks = dict((o.key, r) for o, r in available(self._ctx(res, m0)))
            if locks.get(key) is not None:
                return False
            delta = self._delta(key, m0)
        new_events = opt.make(m0, snap)
        self.events = self.events + new_events
        if key != "stay":
            self.done.add(key)
            self.badges[self.turn] = opt.emoji
            self.groups.append({"id": f"d{len(self.groups) + 1}", "key": key, "emoji": opt.emoji,
                                "title": opt.title, "cat": CAT_INFO[opt.cat][0], "turn": self.turn,
                                "start_month": m0, "events": list(new_events), "movable": True})
        if key == "child":
            self.kids += 1
        self.xp += opt.xp
        self.joy = int(np.clip(self.joy + 3 * opt.joy, 0, 100))
        self.history.append({"turn": self.turn, "key": key, "emoji": opt.emoji, "title": opt.title,
                             "cat": opt.cat, "xp": opt.xp, "delta": delta})
        self.prev_turn, self.turn = self.turn, self.turn + 1
        new = self._res(12 * self.turn)
        self.anims = animations(new.plan, m0, 12 * self.turn, self.turn, self.played)
        self._check_achievements()
        if self.turn >= YEARS:
            self.phase = "end"
            self.dash_open = False          # the end starts on the life summary, not inside the dashboard
        if self.alt and self.alt.get("kind") == "option":     # "this option now" is stale after a turn
            self.alt = None
        self._post_opener()
        self._changed()
        return True

    def restart(self) -> None:
        self._reset_game()
        self.phase = "boot"
        self._changed()

    def is_new(self, value) -> bool:
        """True if ``value`` is an action whose nonce has not been handled yet."""
        if not isinstance(value, dict) or not isinstance(value.get("nonce"), (int, float, str)):
            return False
        return value["nonce"] not in self._handled

    def handle(self, value) -> str | None:
        """Apply one action from the client. Returns 'analyse' to switch pages, else None. Dedupes by nonce."""
        if not self.is_new(value):
            return None
        self._handled.add(value["nonce"])
        action = value.get("action")
        if action == "start":
            pid = value.get("pid") or "P00001"
            if pid not in self.calib.persons:
                pid = "P00001"
            self.start(pid, value.get("avatar"), value.get("risk") or "ausgewogen")
        elif action == "choose":
            if not self.choose(str(value.get("key", ""))):
                # rejected move: nothing changes, but bump seq so the client's waiting overlay clears
                # (and don't re-announce the previous turn's achievements under the new seq)
                self.new_achievements = []
                self._changed()
        elif action == "restart":
            self.restart()
        elif action == "analyse":
            return "analyse"
        elif action == "chat":
            self.ask(str(value.get("message") or ""))
            self._changed()
        elif action == "dashboard":
            self.dash_open = bool(value.get("open", True)) and self.phase in ("play", "end")
            self._changed()
        elif action == "plan_edit":
            self.plan_edit(value.get("moves") or {})
            self._changed()
        elif action == "plan_alt":
            self.plan_alt(str(value.get("key") or ""))
            self._changed()
        elif action == "plan_reset":
            self.alt = None
            self._changed()
        return None

    # ------------------------------------------------------------ Zwilling-Chat & dashboard
    def _state_name(self, month: int | None = None) -> str:
        month = min(12 * self.turn if month is None else month, 12 * YEARS)
        return STATE_NAMES.get(snapshot(self._res(month), month).state, "other")

    def _post_opener(self) -> None:
        """When a new station starts, the twin opens it with a tip + question (Juli's STAGES)."""
        if self.phase not in ("play", "end"):
            return
        studying = any(g["key"] in ("bachelor", "master", "lehre") for g in self.groups)
        msg = agent.opener(self.phase, self._state_name(), self.turn, self.person.age + self.turn, studying)
        self.chat = agent.trim(self.chat + [msg])

    def _chat_ctx(self) -> agent.ChatCtx:
        end = self.phase == "end"
        month = 12 * YEARS if end else 12 * self.turn
        res = self._res(month)
        snap = snapshot(res, month)
        ctx = self._ctx(res, month)
        options = [{"key": o.key, "title": o.title, "emoji": o.emoji, "cat": CAT_INFO[o.cat][0],
                    "locked": r, "joy": o.joy} for o, r in available(ctx)]
        pid, a, seed = self.pid, self.assumptions, self.seed
        return agent.ChatCtx(
            phase=self.phase, start_age=self.person.age, age=self.person.age + self.turn, month=month,
            state=STATE_NAMES.get(snap.state, "other"), events=tuple(self.events), groups=list(self.groups),
            options=options, sim=lambda ev, fixed: _play(pid, tuple(ev), a, seed, int(fixed)),
            make=lambda key: OPTION_BY_KEY[key].make(month, snap),
            drivers=lambda ev=tuple(self.events): _drivers(pid, ev, a, seed),
            turn=self.turn, end_age=self.person.age + YEARS, fixed=0 if end else month)

    def ask(self, message: str) -> dict | None:
        """Answer one chat message synchronously (both messages are appended to the thread)."""
        message = message.strip()[:agent.MAX_QUESTION]
        if self.phase not in ("play", "end") or not message:
            return None
        reply = agent.answer(self._chat_ctx(), message)
        self.chat_mode = reply["mode"]
        msg = {"role": "twin", "text": reply["text"], "tools": reply["tools"], "suggestion": reply["suggestion"],
               "mode": reply["mode"]}
        self.chat = agent.trim(self.chat + [{"role": "user", "text": message, "tools": [], "suggestion": None},
                                            msg])
        return msg

    def plan_edit(self, moves) -> None:
        """Move decision groups to new ages (merged with earlier moves) -> ``series.alt``."""
        if self.phase not in ("play", "end") or not isinstance(moves, dict):
            return
        ids = {g["id"] for g in self.groups if g.get("movable", True)}
        prev = self.alt["moves"] if self.alt and self.alt.get("kind") == "moves" else {}
        merged = dict(prev)
        for gid, age in moves.items():
            if gid in ids and isinstance(age, (int, float)) and not isinstance(age, bool) and math.isfinite(age):
                merged[gid] = float(age)
        self.alt = {"kind": "moves", "moves": merged} if merged else None
        self.dash_open = True

    def plan_alt(self, key: str) -> None:
        """Alternative = played plan + option ``key`` now (only while it is selectable)."""
        if self.phase != "play" or key not in OPTION_BY_KEY or key == "stay":
            return
        m0 = 12 * self.turn
        res = self._res(m0)
        if dict((o.key, r) for o, r in available(self._ctx(res, m0))).get(key, "x") is not None:
            return
        self.alt = {"kind": "option", "key": key, "month": m0,
                    "events": OPTION_BY_KEY[key].make(m0, snapshot(res, m0))}
        self.dash_open = True

    def _alt_events(self) -> tuple[list | None, str | None, dict]:
        if not self.alt:
            return None, None, {}
        if self.alt["kind"] == "option":
            opt = OPTION_BY_KEY[self.alt["key"]]
            return (self.events + list(self.alt["events"]),
                    f"Plan + {opt.title} at {self.person.age + self.alt['month'] // 12}", {})
        moves = self.alt["moves"]
        in_groups = {id(e) for g in self.groups for e in g["events"]}
        rest = [e for e in self.events if id(e) not in in_groups]
        moved, labels = dashboard.apply_moves(self.groups, moves, self.person.age)
        return rest + moved, (" · ".join(labels) if labels else "Plan unchanged"), moves

    def _dashboard_block(self) -> dict | None:
        if not self.dash_open or self.phase not in ("play", "end"):
            return None
        alt_events, alt_label, moves = self._alt_events()
        pid, seed = self.pid, self.seed
        return dashboard.build(pid=pid, start_age=self.person.age, events=self.events, groups=self.groups,
                               a=self.assumptions, seed=seed, phase=self.phase, turn=self.turn,
                               alt_events=alt_events, alt_label=alt_label, moves=moves,
                               sim=lambda ev, a, fixed: _play(pid, tuple(ev), a, seed, int(fixed)))

    def _chat_block(self) -> dict:
        return agent.chat_block(self.chat, self.phase, self.chat_mode)

    # ------------------------------------------------------------ payload pieces
    def _preview(self, key: str, month: int) -> dict:
        return _preview(self.pid, tuple(self.events), key, month, self.assumptions, self.seed)

    def _delta(self, key: str, month: int) -> float:
        return float(self._preview(key, month)["median"] - self._preview("stay", month)["median"])

    def _boot_block(self) -> dict:
        if self._boot is None:
            young = sorted([p for p in self.calib.persons.values() if p.age <= 25],
                           key=lambda p: (p.profile_id != "P00001", p.profile_id))
            # a short, varied pick: Alexia first, then up to 2 profiles per status (max 9 cards)
            picked, per = [], {}
            for p in young:
                if p.profile_id == "P00001" or per.get(p.status, 0) < 2:
                    picked.append(p); per[p.status] = per.get(p.status, 0) + 1
            young = picked[:9]
            profiles = [{"id": p.profile_id, "name": p.name, "age": p.age,
                         "status_de": STATUS_DE.get(p.status, p.status),
                         "start_capital": _f(p.cash + p.portfolio - p.debt), "typical_month": _f(p.mu)}
                        for p in young]
            risks = [{"key": k, "title": RISK_META.get(k, (k.title(), "🎯"))[0],
                      "emoji": RISK_META.get(k, (k.title(), "🎯"))[1], "text": _risk_text(s)}
                     for k, s in STRATEGY_PRESETS.items()]
            self._boot = _clean({"profiles": profiles, "risks": risks})
        return self._boot

    def _achievements(self) -> list[dict]:
        return [{"key": a.key, "emoji": a.emoji, "title": a.title, "got": a.key in self.achieved}
                for a in ACHIEVEMENTS]

    def _world(self, snap, finale: bool) -> dict:
        return {"avatar": dict(self.avatar), "turn": self.turn, "prev_turn": self.prev_turn,
                "start_age": self.person.age, "K": YEARS, "badges": {str(k): v for k, v in self.badges.items()},
                "life": {"suit": snap.state == 1, "kids": self.kids}, "anims": list(self.anims), "finale": finale}

    def _hud(self, snap) -> dict:
        lv, title, _ = level(self.xp)
        return {"name": self.avatar.get("name", "Alex"), "age": self.person.age + self.turn, "level": lv,
                "level_title": title,
                "xp_in_level": self.xp % XP_PER_LEVEL if lv < len(game.LEVELS) else XP_PER_LEVEL,
                "xp_per_level": XP_PER_LEVEL, "xp_total": self.xp, "joy": self.joy, "joy_emoji": joy_label(self.joy),
                "net_worth": snap.net_worth, "cash": snap.cash, "portfolio": snap.portfolio, "debt": snap.debt,
                "income": snap.income, "state_de": STATE_DE.get(STATE_NAMES.get(snap.state, "other"), "other"),
                "achievements_got": len(self.achieved), "achievements_total": len(ACHIEVEMENTS)}

    def _cards(self, ctx: Ctx, month: int) -> tuple[list[dict], list[dict]]:
        opts = available(ctx)
        open_keys = [o.key for o, r in opts if r is None]
        pv = {k: self._preview(k, month) for k in open_keys + ["stay"]}
        base = pv["stay"]["median"]
        cards = []
        for o, reason in opts:
            p = pv.get(o.key)
            cards.append({"key": o.key, "cat": CAT_INFO[o.cat][0], "emoji": o.emoji, "title": o.title, "text": o.text,
                          "locked": reason, "xp": o.xp, "joy": 3 * o.joy,
                          "delta": None if p is None else p["median"] - base,
                          "median": None if p is None else p["median"], "p5": None if p is None else p["p5"],
                          "p95": None if p is None else p["p95"], "credit": None if p is None else p["credit"],
                          "rarity": rarity(o.xp)})
        cats = []
        for c in CATS:
            key, label, emoji = CAT_INFO[c]
            cats.append({"key": key, "label": label, "emoji": emoji, "color": CAT_COLORS.get(key, "#2a78d6"),
                         "open": sum(1 for o, r in opts if o.cat == c and r is None)})
        return cats, cards

    def _quests(self, snap, credit: float) -> list[dict]:
        out = []
        for name, target, gm in self.person.goals:
            if gm <= 12 * YEARS:
                out.append({"name": GOAL_DE.get(name, name), "current": snap.liquid, "target": target,
                            "by_age": self.person.age + gm // 12,
                            "progress": float(min(1.0, max(0.0, snap.liquid / target))) if target else 1.0,
                            "done": snap.liquid >= target})
        free = credit <= 1
        out.append({"name": "Stay debt-free", "current": max(credit, 0.0), "target": 0.0,
                    "by_age": self.person.age + YEARS, "progress": 1.0 if free else 0.0, "done": free})
        return out

    def _ages(self) -> list[int]:
        return [self.person.age + i for i in range(YEARS + 1)]

    def _fan(self, res) -> dict:
        nw, pct = res.path0["net_worth"], res.percentiles["net_worth"]
        now = self.turn
        return {"ages": self._ages(),
                "past": [nw[12 * i] if i <= now else None for i in range(YEARS + 1)],
                "p5": [pct[0, 12 * i] if i >= now else None for i in range(YEARS + 1)],
                "p50": [pct[2, 12 * i] if i >= now else None for i in range(YEARS + 1)],
                "p95": [pct[4, 12 * i] if i >= now else None for i in range(YEARS + 1)],
                "now_index": now}

    def _history(self) -> list[dict]:
        return [{"age": self.person.age + h["turn"], "emoji": h["emoji"], "title": h["title"]} for h in self.history]

    def _play_block(self) -> dict:
        month = 12 * self.turn
        res = self._res(month)
        snap = snapshot(res, month)
        ctx, flags = self._ctx(res, month), self._flags(res, month)
        cats, cards = self._cards(ctx, month)
        return {"turn": self.turn, "K": YEARS, "start_age": self.person.age, "age": self.person.age + self.turn,
                "hud": self._hud(snap), "world": self._world(snap, False), "categories": cats, "cards": cards,
                "stay": {"key": STAY.key, "title": STAY.title, "xp": STAY.xp},
                "quests": self._quests(snap, flags["credit"]), "achievements": self._achievements(),
                "new_achievements": [{"emoji": a["emoji"], "title": a["title"], "xp": a["xp"]}
                                     for a in self.new_achievements],
                "history": self._history(), "fan": self._fan(res)}

    def _end_block(self) -> dict:
        T = 12 * YEARS
        mine = self._res(T)
        snap = snapshot(mine, T)
        p0 = mine.path0
        final = float(p0["net_worth"][-1])
        possible = self._res(0)
        lazy = _play(self.pid, (), self.assumptions, self.seed, 0)
        score = int(max(final, 0) / 1000 + self.joy * 5 + len(self.achieved) * 50)
        stars = int(min(5, 1 + score // 300))
        dist = possible.percentiles["net_worth"][:, -1]
        percentile = int(round(float(np.interp(final, dist, [5, 25, 50, 75, 95]))))
        credit_path = p0["cash"] + p0["portfolio"] - p0["liquid"]
        lv, title, _ = level(self.xp)
        decisions = [h for h in self.history if h["key"] != "stay"]
        rated = [h for h in decisions if h["delta"] is not None]
        best = max(rated, key=lambda h: h["delta"]) if rated else None
        yearly = [12 * i for i in range(YEARS + 1)]
        pct, lazy_pct = possible.percentiles["net_worth"], lazy.percentiles["net_worth"]
        summary = {"name": self.avatar.get("name", "Alex"), "age_end": self.person.age + YEARS, "score": score,
                   "stars": stars, "level": lv, "level_title": title, "joy": self.joy,
                   "joy_emoji": joy_label(self.joy), "xp_total": self.xp,
                   "choices": [{"age": self.person.age + h["turn"], "emoji": h["emoji"], "title": h["title"],
                                "cat_label": CAT_INFO[h["cat"]][1], "rarity": rarity(h["xp"]), "xp": h["xp"]}
                               for h in decisions],
                   "achievements": self._achievements()}
        facts = {"net_worth": final, "percentile": percentile, "p5": dist[0], "p95": dist[4],
                 "lazy_median": lazy.metrics["median_net_worth_end"],
                 "cash": p0["cash"][-1], "portfolio": p0["portfolio"][-1], "house_equity": p0["house_equity"][-1],
                 "debt": p0["debt"][-1], "max_credit": max(float(np.max(credit_path)), 0.0),
                 "months_with_credit": int(np.sum(credit_path[1:] > 1)), "decisions": len(decisions),
                 "best": None if best is None else {"title": best["title"], "delta": best["delta"]},
                 "fan": {"ages": self._ages(), "past": [p0["net_worth"][m] for m in yearly],
                         "p5": [pct[0, m] for m in yearly], "p50": [pct[2, m] for m in yearly],
                         "p95": [pct[4, m] for m in yearly], "lazy": [lazy_pct[2, m] for m in yearly],
                         "now_index": YEARS},
                 "disclaimer": DISCLAIMER}
        return {"world": self._world(snap, True), "summary": summary, "facts": facts}

    def payload(self) -> dict:
        """The component args for the current state (cached until the state changes)."""
        if self._payload is None:
            out = {"height": HEIGHT, "seq": self.seq, "phase": self.phase, "avatar": dict(self.avatar),
                   "boot": self._boot_block()}
            if self.phase == "play":
                out["play"] = self._play_block()
            elif self.phase == "end":
                out["end"] = self._end_block()
            if self.phase in ("play", "end"):
                out[self.phase]["chat"] = self._chat_block()
                out[self.phase]["dashboard"] = self._dashboard_block()
            self._payload = _clean(out)
        return self._payload
