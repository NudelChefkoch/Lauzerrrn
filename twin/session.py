"""Pure-Python game state machine for "YOUR LIFE · YOUR CHOICE".

``GameSession`` holds one player's game and produces exactly the payload described in
``twin/frontend3d/CONTRACT.md`` (phase boot | play | end | ride). Streamlit only hosts it: every action the
client sends goes through :meth:`GameSession.handle`, and :meth:`GameSession.payload` is passed back to the
component. ``seq`` is incremented on every state change; the payload is cached until the state changes.
All numbers in the payload are plain Python ints/floats/None (JSON-serialisable).
"""
from __future__ import annotations

import io
import math
from functools import lru_cache

import numpy as np
import pandas as pd

from . import game
from .calibration import Person, calibrate
from .config import RETIRED, STATE_NAMES, UNEMPLOYED, Assumptions
from .game import (CATS, GAME_STRATEGY, OPTION_BY_KEY, STAY, Ctx, animations, available,
                   finished_degrees, life_span, snapshot)
from .ist_zustand import STATUS_OPTIONS, ist_from_person, person_from_ist

HEIGHT = 860
EXAMPLE_ID = "P00004"          # the one example data set offered on the start screen (Yara, 24, employed)
MAX_CSV_BYTES = 400_000
DISCLAIMER = "Synthetic data · not a forecast · not investment advice"

DEFAULT_AVATAR = {"name": "Alex", "gender": "frau", "skin": "rosig", "hair": "lang", "hairColor": "braun",
                  "hat": "keiner", "outfit": "hoodie", "color": "violett", "car": "tuerkis"}

STATE_LABEL = {"student": "in education", "employed": "employed", "unemployed": "without a job",
               "self_employed": "self-employed", "other": "retired"}      # state OTHER = RETIRED in the game
STATUS_LABEL = {"student": "in education", "employed": "employed", "part_time": "part-time",
                "unemployed": "without a job", "self_employed": "self-employed", "retired": "retired"}
GOAL_LABEL = {"Emergency savings": "Emergency fund", "Career transition": "Career-change cushion",
              "Education flexibility": "Education reserve", "Housing deposit": "Home down payment",
              "Long-term financial resilience": "Long-term reserve", "Retirement reserve": "Retirement reserve"}

CHILD_LEFT = "Child moves out"   # plan label when a child's costs end (game.CHILD_MONTHS)
CAT_KEYS = ["education", "career", "housing", "family", "timeoff"]   # stable ids, same order as game.CATS
CAT_COLORS = {"education": "#2a78d6", "career": "#eb6834", "housing": "#2f9e44", "family": "#e87ba4",
              "timeoff": "#1baf7a"}
SKIP_CHOICES = ({"years": 5, "label": "+5 years"}, {"years": 10, "label": "+10 years"},
                {"until": "event", "label": "Next event"})
SKIP_UNTIL_MAX = 10            # "Next event" stops after at most this many years


def _split_cat(i: int, cat: str) -> tuple[str, str, str]:
    """'🎓 Education' -> ('education', 'Education', '🎓')."""
    emoji, label = cat.split(" ", 1)
    return CAT_KEYS[i], label, emoji


CAT_INFO = {c: _split_cat(i, c) for i, c in enumerate(CATS)}   # game.CATS label -> (key, label, emoji)


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
# keyed by the (frozen, hashable) Person, so self-entered Ist-Zustände share the cache like the profiles do
@lru_cache(maxsize=256)
def _play(person: Person, events: tuple, a: Assumptions, seed: int, now: int, years: int):
    return game.play(person, list(events), a, calibrate(), seed, now, years)


@lru_cache(maxsize=4096)
def _preview(person: Person, events: tuple, key: str, month: int, a: Assumptions, seed: int, years: int,
             ctx: Ctx | None = None, values: tuple = ()) -> dict:
    """Preview of option ``key`` at ``month``; ``values`` = sorted (param, value) pairs (part of the cache key)."""
    res = _play(person, events, a, seed, month, years)
    if key == STAY.key:                       # "drive on" = the current plan: reuse the cached run
        assumed = game.assume_degree_jobs(list(events), month)
        if len(assumed) != len(events):        # graduated: compare with "takes the degree job" (see game.py)
            res = game.play(person, assumed, a, calibrate(), seed, month, years, pct_series=())
        m = res.metrics
        return {"median": m["median_net_worth_end"], "p5": m["p5_net_worth_end"], "p95": m["p95_net_worth_end"],
                "credit": m["p_credit_future"]}
    snap = snapshot(res, month)
    return game.preview(person, list(events), OPTION_BY_KEY[key], snap, a, calibrate(), seed, years, ctx,
                        dict(values))


class GameSession:
    """One player's game. Methods: start, choose, skip, set_params, ride, restart, payload, handle,
    aktualisiere_mit_daten."""

    def __init__(self) -> None:
        self.calib = calibrate()
        self.seq = 0
        self.phase = "boot"
        self.avatar = dict(DEFAULT_AVATAR)
        self._handled: set = set()
        self._payload: dict | None = None
        self._boot: dict | None = None
        self.error: str | None = None          # one-shot message for the client (e.g. a CSV that cannot be read)
        self._reset_game()

    # ------------------------------------------------------------ state helpers
    def _reset_game(self) -> None:
        self.pid: str | None = None             # Beispielprofil, mit dem das Formular vorbefüllt war (oder None)
        self._person: Person | None = None      # Person aus dem abgefragten Ist-Zustand
        self.ist: dict | None = None
        self.seed = 0
        self.assumptions = Assumptions(strategy=GAME_STRATEGY)
        self.events: list = []
        self.turn = 0
        self.prev_turn = 0
        self.done: set[str] = set()
        self.badges: dict[int, str] = {}
        self.kids = 0
        self.played: set = set()
        self.history: list[dict] = []          # {turn, key, emoji, title, cat, delta}
        self.anims: list[dict] = []
        self.skipped = 0                       # stations driven by the last step (0 = normal step, n = skip)
        self.params: dict[str, dict] = {}      # chosen card values {key: {param: value}} (clamped/snapped)
        self.step, self.K, self.total = life_span(20)
        self.ride_data: dict | None = None     # film ride: stations from later data + updated statements
        self.data_person: Person | None = None  # person updated with the film-ride data (used by the analysis)

    def _changed(self) -> None:
        self.seq += 1
        self._payload = None

    @property
    def person(self) -> Person:
        return self._person

    # life span: station i is at age person.age + years(i); the last station is the retirement age
    def years_at(self, turn: int) -> int:
        return min(turn * self.step, self.total)

    def month_at(self, turn: int) -> int:
        return 12 * self.years_at(turn)

    def age_at(self, turn: int) -> int:
        return self.person.age + self.years_at(turn)

    def _res(self, month: int | None = None):
        month = self.month_at(self.turn) if month is None else month
        return _play(self.person, tuple(self.events), self.assumptions, self.seed, month, self.total)

    def _values(self, key: str) -> dict:
        return OPTION_BY_KEY[key].values(self.params.get(key))

    def set_params(self, key: str, params) -> bool:
        """Store chosen card values (clamped to min/max, snapped to the step). False if nothing applies."""
        opt = OPTION_BY_KEY.get(key)
        if opt is None or not opt.params or not isinstance(params, dict):
            return False
        cur = dict(self.params.get(key, {}))
        cur.update({n: opt.params[n].snap(v) for n, v in params.items() if n in opt.params})
        self.params[key] = opt.values(cur)
        return True

    def _ctx(self, res, month: int) -> Ctx:
        return Ctx(snapshot(res, month), frozenset(self.done), self.age_at(self.turn), self.kids,
                   finished_degrees(res.plan, month), None, self.turn)

    def _credit(self, res, month: int) -> float:
        p = res.path0
        return float(p["cash"][month] + p["portfolio"][month] - p["liquid"][month])

    # ------------------------------------------------------------ actions
    def start(self, ist: dict | None = None, avatar: dict | None = None, seed: int | None = None,
              pid: str | None = None) -> None:
        """Start a game from the Ist-Zustand the player entered (``ist``) – or, as a shortcut, from an example
        profile ``pid`` taken over unchanged. Investing follows the balanced default (analysis page compares styles)."""
        if ist is None:
            if pid not in self.calib.persons:
                raise KeyError(f"unknown profile {pid!r}")
            ist = ist_from_person(self.calib.persons[pid])
        self._reset_game()
        if avatar:
            self.avatar = {**DEFAULT_AVATAR, **{k: v for k, v in avatar.items() if v is not None}}
        self.ist = dict(ist)
        self._person = person_from_ist(self.calib, ist, self.avatar.get("name"))
        self.pid = self._person.profile_id if self._person.profile_id in self.calib.persons else None
        self.step, self.K, self.total = life_span(self._person.age)
        self.seed = int(np.random.default_rng().integers(1_000_000)) if seed is None else int(seed)
        self.assumptions = Assumptions(strategy=GAME_STRATEGY)
        self.phase = "play"
        self._changed()

    def choose(self, key: str, params: dict | None = None) -> bool:
        """Play one station with option ``key`` (or 'stay'). ``params`` = chosen card values (fallback: the stored
        ones, then the defaults). Returns False if the move is not allowed."""
        if self.phase != "play" or key not in OPTION_BY_KEY:
            return False
        opt = OPTION_BY_KEY[key]
        m0 = self.month_at(self.turn)
        res = self._res(m0)
        snap = snapshot(res, m0)
        ctx = self._ctx(res, m0)
        values = opt.values({**self.params.get(key, {}), **(params if isinstance(params, dict) else {})})
        delta = None
        if key != "stay":
            if opt.reason(ctx, values) is not None:
                return False
            if self._preview(key, m0, ctx, values).get("house_failed"):
                return False                     # the purchase would fail in the played life (see game.preview)
            delta = self._delta(key, m0, ctx, values)
            if opt.params:
                self.params[key] = values
        self.events = self.events + opt.events(m0, snap, ctx, values)
        if key != "stay":
            self.done.add(key)
            self.badges[self.turn] = opt.emoji
        if key == "child":
            self.kids += 1
        self.history.append({"turn": self.turn, "key": key, "emoji": opt.emoji, "title": opt.title,
                             "cat": opt.cat, "delta": delta})
        self.prev_turn, self.turn = self.turn, self.turn + 1
        m1 = self.month_at(self.turn)
        new = self._res(m1)
        self.anims = animations(new.plan, m0, m1, self.turn, self.played)
        self.skipped = 0
        if self.turn >= self.K:
            self.phase = "end"
        self._changed()
        return True

    def skip(self, years: int | None = None, until: str | None = None) -> bool:
        """Drive on for ``years`` stations in one step (= n x choose('stay')), stopping at the end of life.
        ``until='event'``: stop at the next station where a planned event happens (degree finished, child moves
        out, forced retirement, ...) or after 10 years. Returns False if the move is not allowed."""
        if self.phase != "play":
            return False
        if until == "event":
            n_max = SKIP_UNTIL_MAX
        else:
            try:
                n_max = int(years)
            except (TypeError, ValueError):
                return False
            if n_max < 1:
                return False
        n_max = min(n_max, self.K - self.turn)
        plan = self._res(self.month_at(self.turn)).plan     # events do not change: same plan for every station
        start, anims, n = self.turn, [], 0
        while n < n_max:
            m0 = self.month_at(self.turn)
            self.history.append({"turn": self.turn, "key": STAY.key, "emoji": STAY.emoji, "title": STAY.title,
                                 "cat": STAY.cat, "delta": None})
            self.turn += 1
            n += 1
            seg = animations(plan, m0, self.month_at(self.turn), self.turn, self.played)
            for a in seg:
                a["turn"] = self.turn        # station where it happened: the engine's drive pauses there
            anims += seg
            if until == "event" and seg:
                break
        if n >= 2:
            for a in anims:
                a["brief"] = True
        self.prev_turn, self.anims, self.skipped = start, anims, n
        if self.turn >= self.K:
            self.phase = "end"
        self._changed()
        return True

    def restart(self) -> None:
        self._reset_game()
        self.phase = "boot"
        self._changed()

    # ------------------------------------------------------------ film ride: later data, station by station
    def ride(self, ist: dict | None, avatar: dict | None = None, csv: str | None = None, seed: int = 0,
             example: bool = False) -> bool:
        """Film ride, one station per month (quarters only for more than 36 months).
        ``example=True``: the example data set rides through its own recorded months from the challenge data;
        otherwise ``csv`` (the player's later monthly data) updates the person from the status quo ``ist``.
        The twin is updated with ``aktualisiere_aus_daten``. Returns False (and sets ``error``) if the data is bad."""
        from .calibration import _read
        from .daten_update import aktualisiere_aus_daten
        if avatar:
            self.avatar = {**DEFAULT_AVATAR, **{k: v for k, v in avatar.items() if v is not None}}
        if example or csv is None:
            person = self.calib.persons[EXAMPLE_ID]       # the example's status quo at the start of its data
        else:
            person = person_from_ist(self.calib, ist or ist_from_person(self.calib.persons[EXAMPLE_ID]),
                                     self.avatar.get("name"))
        try:
            if example or csv is None:
                cb = _read("synthetic-cash-balances.csv")
                df = cb[cb["profile_id"] == EXAMPLE_ID][["month", "net_transactions_chf", "closing_cash_chf"]]
                source = f"the example data set ({person.name})"
            else:
                if len(csv) > MAX_CSV_BYTES:
                    raise ValueError("file is too large")
                df, source = pd.read_csv(io.StringIO(csv)), "your data"
            upd = aktualisiere_aus_daten(person, df, calib=self.calib, assumptions=Assumptions(strategy=GAME_STRATEGY),
                                         bis_alter=game.RETIRE_AGE, n_paths=600, seed=seed,
                                         profile_id=None if "profile_id" not in df.columns else
                                         (person.profile_id if person.profile_id in set(df["profile_id"]) else None))
        except Exception as e:                      # bad file: tell the player, stay on the start screen
            self.error = f"Could not read the data: {e}"
            self._changed()
            return False
        from .daten_update import lese_neue_daten
        data = lese_neue_daten(df, None if "profile_id" not in df.columns or df["profile_id"].nunique() <= 1
                               else person.profile_id)
        flows = data["net_transactions_chf"].to_numpy(dtype=float)
        bal = (data["closing_cash_chf"].to_numpy(dtype=float) if "closing_cash_chf" in data.columns
               else person.cash + np.cumsum(flows))
        months = pd.to_datetime(data["month"] + "-01")
        groups = [list(range(i, min(i + 3, len(data)))) for i in range(0, len(data), 3)] if len(data) > 36 \
            else [[i] for i in range(len(data))]
        sig = person.sigma if math.isfinite(person.sigma) and person.sigma > 0 else 300.0
        stations = []
        for g in groups:
            flow, n = float(flows[g].sum()), len(g)
            label = months.iloc[g[0]].strftime("%b %Y") if n == 1 else \
                f"{months.iloc[g[0]].strftime('%b')}–{months.iloc[g[-1]].strftime('%b %Y')}"
            z = (flow / n - person.mu) / sig
            note = "🎉 a strong month" if z > 1.3 else "⚠️ a tough month" if z < -1.3 else ""
            if n > 1 and note:
                note = note.replace("month", "quarter")
            stations.append({"label": label, "short": months.iloc[g[-1]].strftime("%b %y"), "flow": flow,
                             "balance": float(bal[g[-1]]), "note": note})
        self.ride_data = {"source": source, "months": int(len(data)), "stations": stations,
                          "statements": upd.aussagen, "before": upd.vorher, "after": upd.nachher, "ist": upd.ist,
                          "typical_before": person.mu, "typical_after": upd.person.mu}
        self._person, self.data_person = person, upd.person
        self.phase = "ride"
        self._changed()
        return True

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
            ist = value.get("ist") if isinstance(value.get("ist"), dict) else None
            pid = value.get("pid") if value.get("pid") in self.calib.persons else EXAMPLE_ID
            self.start(ist, value.get("avatar"), pid=pid)
        elif action == "ride":
            ist = value.get("ist") if isinstance(value.get("ist"), dict) else None
            csv = value.get("csv") if isinstance(value.get("csv"), str) and value.get("csv").strip() else None
            self.ride(ist, value.get("avatar"), csv, example=bool(value.get("example")) or csv is None)
        elif action == "ride_play":                   # play the game from the updated status quo
            if self.phase == "ride" and self.ride_data:
                self.start(self.ride_data["ist"], self.avatar)
        elif action == "choose":
            params = value.get("params") if isinstance(value.get("params"), dict) else None
            if not self.choose(str(value.get("key", "")), params):
                # rejected move: nothing changes, but bump seq so the client's waiting overlay clears
                self._changed()
        elif action == "card_params":                 # adjust a card's values: lock, preview and text follow
            self.set_params(str(value.get("key", "")), value.get("params"))
            self._changed()
        elif action == "skip":
            until = "event" if value.get("until") == "event" else None
            if not self.skip(value.get("years"), until):
                self._changed()
        elif action == "restart":
            self.restart()
        elif action == "analyse":
            return "analyse"
        return None

    # ------------------------------------------------------------ payload pieces
    def _preview(self, key: str, month: int, ctx: Ctx | None = None, values: dict | None = None) -> dict:
        vals = tuple(sorted(OPTION_BY_KEY[key].values(values).items()))
        return _preview(self.person, tuple(self.events), key, month, self.assumptions, self.seed, self.total,
                        ctx, vals)

    def _delta(self, key: str, month: int, ctx: Ctx | None = None, values: dict | None = None) -> float:
        return float(self._preview(key, month, ctx, values)["median"] - self._preview("stay", month)["median"])

    def _boot_block(self) -> dict:
        if self._boot is None:
            p = self.calib.persons[EXAMPLE_ID]
            # the player enters their own status quo; ONE example data set can pre-fill the form
            example = {"id": p.profile_id, "name": p.name, "age": p.age, "status": STATUS_LABEL.get(p.status, p.status),
                       "ist": ist_from_person(p)}
            statuses = [{"key": k, "label": v} for k, v in STATUS_OPTIONS.items()]
            self._boot = _clean({"example": example, "statuses": statuses, "retire_age": game.RETIRE_AGE,
                                 "retire_from": game.RETIRE_FROM, "forced_retire_age": game.FORCED_RETIRE_AGE,
                                 "end_age": game.END_AGE})
        return self._boot

    def _world(self, snap, finale: bool, plan=None) -> dict:
        month = self.month_at(self.turn)
        left = sum(1 for t, l in (plan.labels if plan is not None else ()) if l == CHILD_LEFT and t <= month)
        return {"avatar": dict(self.avatar), "turn": self.turn, "prev_turn": self.prev_turn,
                "start_age": self.person.age, "K": self.K, "step": self.step, "labels": self._ages(),
                "badges": {str(k): v for k, v in self.badges.items()},
                # kids = children born; kids_home = still at home (each moves out at 18); retired -> grey + cane
                "life": {"suit": snap.state == 1, "kids": self.kids, "kids_home": max(self.kids - left, 0),
                         "partner": "wedding" in self.done, "retired": snap.state == RETIRED},
                "anims": list(self.anims), "finale": finale, "skipped": self.skipped,
                # fresh game: the client plays the intro (fly-over, how to play, countdown) once
                "intro": self.turn == 0 and not self.history and not finale}

    def _hud(self, snap, ctx: Ctx | None = None, plan=None) -> dict:
        state = STATE_LABEL.get(STATE_NAMES.get(snap.state, "other"), "other")
        if snap.state == UNEMPLOYED and ctx is not None and ctx.finished and plan is not None:
            month = self.month_at(self.turn)     # no job started since the last degree (also after a gap year)
            deg = max((t for t, l in plan.labels if l in game.DEGREE_LABELS and t <= month), default=-1)
            job = max((t for t, l in plan.labels if (l == "First job" or l.startswith("Job:")) and t <= month), default=-1)
            if deg > job:
                state = "graduated · looking"
        return {"name": self.avatar.get("name", "Alex"), "age": self.age_at(self.turn),
                "net_worth": snap.net_worth, "cash": snap.cash, "portfolio": snap.portfolio, "debt": snap.debt,
                "income": snap.income, "state": state}

    def _cards(self, ctx: Ctx, month: int) -> tuple[list[dict], list[dict]]:
        opts = available(ctx, self.params)
        open_keys = [o.key for o, r in opts if r is None]
        pv = {k: self._preview(k, month, ctx, self.params.get(k)) for k in open_keys}
        pv["stay"] = self._preview("stay", month)
        opts = [(o, game.HOUSE_FAILED if r is None and pv[o.key].get("house_failed") else r) for o, r in opts]
        base = pv["stay"]["median"]
        cards = []
        for o, reason in opts:
            p = pv.get(o.key) if reason is None else None
            vals = self._values(o.key)
            card = {"key": o.key, "cat": CAT_INFO[o.cat][0], "emoji": o.emoji, "title": o.title,
                    "text": o.text_for(ctx, vals), "locked": reason,
                    "delta": None if p is None else p["median"] - base,
                    "median": None if p is None else p["median"], "p5": None if p is None else p["p5"],
                    "p95": None if p is None else p["p95"], "credit": None if p is None else p["credit"]}
            if o.params:
                card["params"] = {n: prm.spec(vals[n]) for n, prm in o.params.items()}
            cards.append(card)
        cats = []
        for c in CATS:
            key, label, emoji = CAT_INFO[c]
            cats.append({"key": key, "label": label, "emoji": emoji, "color": CAT_COLORS.get(key, "#2a78d6"),
                         "open": sum(1 for o, r in opts if o.cat == c and r is None)})
        return cats, cards

    def _quests(self, snap, credit: float) -> list[dict]:
        out = []
        for name, target, gm in self.person.goals:
            if gm <= 12 * self.total:
                out.append({"name": GOAL_LABEL.get(name, name), "current": snap.liquid, "target": target,
                            "by_age": self.person.age + gm // 12,
                            "progress": float(min(1.0, max(0.0, snap.liquid / target))) if target else 1.0,
                            "done": snap.liquid >= target})
        free = credit <= 1
        out.append({"name": "Stay debt-free", "current": max(credit, 0.0), "target": 0.0,
                    "by_age": self.age_at(self.K), "progress": 1.0 if free else 0.0, "done": free})
        return out

    def _ages(self) -> list[int]:
        return [self.age_at(i) for i in range(self.K + 1)]

    def _fan(self, res) -> dict:
        nw, pct = res.path0["net_worth"], res.percentiles["net_worth"]
        now, ms = self.turn, [self.month_at(i) for i in range(self.K + 1)]
        return {"ages": self._ages(),
                "past": [nw[m] if i <= now else None for i, m in enumerate(ms)],
                "p5": [pct[0, m] if i >= now else None for i, m in enumerate(ms)],
                "p50": [pct[2, m] if i >= now else None for i, m in enumerate(ms)],
                "p95": [pct[4, m] if i >= now else None for i, m in enumerate(ms)],
                "now_index": now}

    def _history(self) -> list[dict]:
        return [{"age": self.age_at(h["turn"]), "emoji": h["emoji"], "title": h["title"]} for h in self.history]

    def _play_block(self) -> dict:
        month = self.month_at(self.turn)
        res = self._res(month)
        snap = snapshot(res, month)
        ctx = self._ctx(res, month)
        cats, cards = self._cards(ctx, month)
        left = self.K - self.turn
        skip = [dict(c) for c in SKIP_CHOICES if c.get("years", 0) <= left]
        return {"turn": self.turn, "K": self.K, "step": self.step, "start_age": self.person.age,
                "age": self.age_at(self.turn), "end_age": self.age_at(self.K),
                "hud": self._hud(snap, ctx, res.plan), "world": self._world(snap, False, res.plan), "categories": cats, "cards": cards,
                "stay": {"key": STAY.key, "title": STAY.title}, "skip": skip,
                "quests": self._quests(snap, self._credit(res, month)),
                "history": self._history(), "fan": self._fan(res)}

    def _end_block(self) -> dict:
        T = self.month_at(self.K)
        mine = self._res(T)
        snap = snapshot(mine, T)
        p0 = mine.path0
        final = float(p0["net_worth"][-1])
        possible = self._res(0)
        lazy = _play(self.person, (), self.assumptions, self.seed, 0, self.total)
        dist = possible.percentiles["net_worth"][:, -1]
        percentile = int(round(float(np.interp(final, dist, [5, 25, 50, 75, 95]))))
        score = int(round(max(final, 0) / 1000))                  # net worth at the end (85) in k CHF
        stars = int(min(5, 1 + percentile // 20))
        credit_path = p0["cash"] + p0["portfolio"] - p0["liquid"]
        decisions = [h for h in self.history if h["key"] != "stay"]
        rated = [h for h in decisions if h["delta"] is not None]
        best = max(rated, key=lambda h: h["delta"]) if rated else None
        yearly = [self.month_at(i) for i in range(self.K + 1)]
        pct, lazy_pct = possible.percentiles["net_worth"], lazy.percentiles["net_worth"]
        summary = {"name": self.avatar.get("name", "Alex"), "age_end": self.age_at(self.K), "score": score,
                   "stars": stars, "percentile": percentile, "decisions": len(decisions),
                   "choices": [{"age": self.age_at(h["turn"]), "emoji": h["emoji"], "title": h["title"],
                                "cat_label": CAT_INFO[h["cat"]][1], "delta": h["delta"]}
                               for h in decisions]}
        facts = {"net_worth": final, "percentile": percentile, "p5": dist[0], "p95": dist[4],
                 "lazy_median": lazy.metrics["median_net_worth_end"],
                 "cash": p0["cash"][-1], "portfolio": p0["portfolio"][-1], "house_equity": p0["house_equity"][-1],
                 "debt": p0["debt"][-1], "max_credit": max(float(np.max(credit_path)), 0.0),
                 "months_with_credit": int(np.sum(credit_path[1:] > 1)), "decisions": len(decisions),
                 "best": None if best is None else {"title": best["title"], "delta": best["delta"]},
                 "fan": {"ages": self._ages(), "past": [p0["net_worth"][m] for m in yearly],
                         "p5": [pct[0, m] for m in yearly], "p50": [pct[2, m] for m in yearly],
                         "p95": [pct[4, m] for m in yearly], "lazy": [lazy_pct[2, m] for m in yearly],
                         "now_index": self.K},
                 "disclaimer": DISCLAIMER}
        return {"world": self._world(snap, True, mine.plan), "summary": summary, "facts": facts}

    def _ride_block(self) -> dict:
        r = self.ride_data
        labels = ["Today"] + [st["short"] for st in r["stations"]]
        world = {"avatar": dict(self.avatar), "turn": 0, "prev_turn": 0, "start_age": self.person.age,
                 "K": len(r["stations"]), "step": 0, "labels": labels, "badges": {}, "life": {}, "anims": [],
                 "finale": False, "intro": False, "ride": True,
                 "ride_tags": [{"text": ("+" if st["flow"] >= 0 else "−") + f"CHF {abs(st['flow']):,.0f}".replace(",", "'"),
                                "good": st["flow"] >= 0, "note": bool(st["note"])} for st in r["stations"]]}
        return {"world": world, **{k: r[k] for k in ("source", "months", "stations", "statements", "before",
                                                       "after", "typical_before", "typical_after")},
                "start_balance": self.person.cash, "name": self.avatar.get("name", "Alex")}

    @property
    def analysis_person(self) -> Person | None:
        """The player's own person for the analysis page: updated by the film ride if there was one."""
        return self.data_person or self._person

    # ------------------------------------------------------------ später: neue Daten einlesen
    def aktualisiere_mit_daten(self, quelle, **kw):
        """Neue (später entstandene) Monatsdaten einlesen und die Aussagen des Zwillings aktualisieren.

        Noch nirgends aufgerufen. ``quelle``: CSV-Pfad oder DataFrame im Format der Challenge-Daten
        (siehe ``twin.daten_update``). Die Person wird nachkalibriert und ersetzt; das laufende Spiel
        beginnt mit dem neuen Stand von vorne (Entscheidungen bleiben nicht erhalten). Gibt das
        ``Aktualisierung``-Objekt mit alten/neuen Kennzahlen und den Aussagen zurück.
        """
        from .daten_update import aktualisiere_aus_daten
        if self.person is None:
            raise RuntimeError("start a game first (no current state yet)")
        upd = aktualisiere_aus_daten(self.person, quelle, calib=self.calib, assumptions=self.assumptions,
                                     bis_alter=game.RETIRE_AGE, seed=self.seed, **kw)
        avatar, seed, ist = dict(self.avatar), self.seed, dict(self.ist or {})
        self._reset_game()
        self.avatar, self.seed, self._person, self.pid = avatar, seed, upd.person, None
        self.ist = {**ist, **upd.ist}
        self.step, self.K, self.total = life_span(upd.person.age)
        self.phase = "play"
        self._changed()
        return upd

    def payload(self) -> dict:
        """The component args for the current state (cached until the state changes)."""
        if self._payload is None:
            out = {"height": HEIGHT, "seq": self.seq, "phase": self.phase, "avatar": dict(self.avatar),
                   "boot": self._boot_block()}
            if self.error:
                out["error"], self.error = self.error, None
            if self.phase == "play":
                out["play"] = self._play_block()
            elif self.phase == "end":
                out["end"] = self._end_block()
            elif self.phase == "ride":
                out["ride"] = self._ride_block()
            self._payload = _clean(out)
        return self._payload
