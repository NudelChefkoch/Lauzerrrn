"""Alternative life path after the game: move, remove and add decisions, see the effect on the net worth.

The played life stays as it was. An *alt state* describes the edits on top of it (plain dict, JSON-safe)::

    {"moves": {gid: age}, "removed": [gid], "added": [{"id": "a1", "key": option_key, "age": int,
                                                     "params": {name: value}}]}

* ``gid`` = id of a played decision group ("d1", "d2", ... in the order of the decisions; the events a decision
  added = the events starting at its month, as in ``twin.review``); an added option has id "a1", "a2", ...
* a move shifts ALL events of the group by the same number of months (as ``dashboard.shift_events`` on the
  Juli port): follow-up events (degree finished, child moves out) move along; removed groups drop out;
  added options build their events with ``Option.events`` at the chosen month (snapshot + context taken from the
  alternative plan up to then), with the chosen params.
* forced retirement at 70 is added by ``game.play`` (so adding "Retire at 60" removes it, removing a played
  retirement brings it back).
* a gap year, the degree job or a master taken right after a degree follow that degree (``follows`` on the
  timeline): moving the degree moves them along, and the degree job never starts before the degree is finished.
* an ADDED degree brings the job of that degree at graduation (like the card previews, ``game.assume_degree_jobs``)
  unless the path already decides what comes next.

Every number is our simulation: ``game.play`` / ``engine.simulate`` with the game's seed (common random numbers),
``fixed_until=0`` (the whole life re-simulated), ``game.N_PATHS`` paths (suggestions are screened with fewer
paths and re-checked with the full count). Results are cached.

Public API: ``EMPTY``, ``normalize``, ``apply_edit``, ``apply_action``, ``timeline_items``, ``addable``,
``alt_events``, ``simulate_paths``, ``suggestions``.
"""
from __future__ import annotations

import copy
import json
import math
from collections import Counter
from dataclasses import replace
from functools import lru_cache

import numpy as np

from . import game
from . import review as rv
from .calibration import calibrate
from .config import EMPLOYED, SELF_EMPLOYED
from .engine import simulate
from .scenarios import ExpenseChange, Job, Retirement, SelfEmployment, Study, Unemployment, build_plan

EMPTY = {"moves": {}, "removed": [], "added": []}
SCREEN_PATHS = 150          # suggestions: first screen with fewer paths ...
DEGREES = ("bachelor", "master", "lehre")

# the forced retirement and the follow-up labels of the plan, shown as small event markers
EVENT_EMOJI = {"graduation": "🎓", "child_leaves": "🏠", "retirement": "🪑", "job": "💼", "gapyear": "🎒"}


def empty() -> dict:
    return copy.deepcopy(EMPTY)


# ---------------------------------------------------------------- alt state
def _num(x) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _age_val(x) -> int | None:
    v = _num(x)
    return None if v is None else int(round(v))


def normalize(alt) -> dict:
    """A clean, JSON-safe alt state (unknown keys and broken values dropped; None -> EMPTY)."""
    out = empty()
    if not isinstance(alt, dict):
        return out
    moves = alt.get("moves")
    if isinstance(moves, dict):
        for gid, age in moves.items():
            a = _age_val(age)
            if a is not None:
                out["moves"][str(gid)] = a
    removed = alt.get("removed")
    if isinstance(removed, (list, tuple)):
        for gid in removed:
            if str(gid) not in out["removed"]:
                out["removed"].append(str(gid))
    added = alt.get("added")
    if isinstance(added, (list, tuple)):
        for item in added:
            if not isinstance(item, dict) or item.get("key") not in game.OPTION_BY_KEY or item["key"] == "stay":
                continue
            a = _age_val(item.get("age"))
            if a is None:
                continue
            opt = game.OPTION_BY_KEY[item["key"]]
            params = item.get("params") if isinstance(item.get("params"), dict) else {}
            params = {n: opt.params[n].snap(v) for n, v in params.items() if n in opt.params}
            iid = str(item.get("id") or "")
            if not iid or any(x["id"] == iid for x in out["added"]):
                iid = _next_id(out["added"])
            out["added"].append({"id": iid, "key": item["key"], "age": a, "params": params})
    return out


def _next_id(added: list) -> str:
    used = {x["id"] for x in added}
    n = 1
    while f"a{n}" in used:
        n += 1
    return f"a{n}"


def is_empty(alt) -> bool:
    a = normalize(alt)
    return not (a["moves"] or a["removed"] or a["added"])


def apply_edit(alt, edit) -> dict:
    """New alt state = ``alt`` merged with ``edit`` (``alt`` is not changed).

    ``edit`` keys (all optional): ``moves`` {id: age} (an added id updates its age), ``removed`` [id] (an added id
    is dropped), ``added`` [{key, age, params}] (fresh ids "a<n>" are assigned), ``restore`` [id] (undo a remove
    and a move), ``reset`` True (back to EMPTY first)."""
    out = normalize(alt)
    if not isinstance(edit, dict):
        return out
    if edit.get("reset"):
        out = empty()
    restore = edit.get("restore")
    if isinstance(restore, (list, tuple, str)):
        for gid in ([restore] if isinstance(restore, str) else restore):
            gid = str(gid)
            out["moves"].pop(gid, None)
            if gid in out["removed"]:
                out["removed"].remove(gid)
    moves = edit.get("moves")
    if isinstance(moves, dict):
        for gid, age in moves.items():
            a, gid = _age_val(age), str(gid)
            if a is None:
                continue
            hit = next((x for x in out["added"] if x["id"] == gid), None)
            if hit is not None:
                hit["age"] = a
            else:
                out["moves"][gid] = a
    removed = edit.get("removed")
    if isinstance(removed, (list, tuple, str)):
        for gid in ([removed] if isinstance(removed, str) else removed):
            gid = str(gid)
            if any(x["id"] == gid for x in out["added"]):
                out["added"] = [x for x in out["added"] if x["id"] != gid]
            elif gid not in out["removed"]:
                out["removed"].append(gid)
                out["moves"].pop(gid, None)
    added = edit.get("added")
    if isinstance(added, (list, tuple)):
        for item in added:
            if not isinstance(item, dict):
                continue
            new = normalize({"added": [{**item, "id": None}]})["added"]
            for x in new:
                x["id"] = _next_id(out["added"])
                out["added"].append(x)
    return normalize(out)


def apply_action(alt, action) -> dict:
    """Alt state after a ``lifereview`` component action ({"action": move|remove|add|restore|reset, ...})."""
    if not isinstance(action, dict):
        return normalize(alt)
    kind = action.get("action")
    if kind == "move" and action.get("id") is not None:
        return apply_edit(alt, {"moves": {str(action["id"]): action.get("age")}})
    if kind == "remove" and action.get("id") is not None:
        return apply_edit(alt, {"removed": [str(action["id"])]})
    if kind == "restore" and action.get("id") is not None:
        return apply_edit(alt, {"restore": [str(action["id"])]})
    if kind == "add":
        return apply_edit(alt, {"added": [{"key": action.get("key"), "age": action.get("age"),
                                           "params": action.get("params") or {}}]})
    if kind == "reset":
        return empty()
    return normalize(alt)


def _alt_key(alt) -> str:
    return json.dumps(normalize(alt), sort_keys=True)


# ---------------------------------------------------------------- the played game
def _inputs(sess) -> rv.Inputs | None:
    return rv.inputs(sess)


def _T(inp: rv.Inputs) -> int:
    return 12 * inp.years


def _groups(inp: rv.Inputs) -> list[dict]:
    """Played decision groups: {id, key, emoji, title, cat, start_month, idx (event indices), events}."""
    out = []
    for n, ((turn, key, emoji, title, cat, _d, _b), idx) in enumerate(zip(inp.history, rv._groups(inp)), 1):
        month = 12 * min(turn * inp.step, inp.years)
        out.append({"id": f"d{n}", "key": key, "emoji": emoji, "title": title, "cat": rv.CAT_KEYS.get(cat, cat),
                    "start_month": month, "idx": idx, "events": [inp.events[i] for i in idx], "leader": None})
    _link_degree_chains(out)
    return out


CHAIN_KEYS = ("gap_year", "grad_job", "master")     # what directly follows a degree moves along with it


def _study_end(g: dict) -> int | None:
    st = next((e for e in g["events"] if isinstance(e, Study)), None)
    return None if st is None else st.start + st.months


def _link_degree_chains(groups: list[dict]) -> None:
    """A gap year, the degree job or a master taken right after a degree (between its end and the degree job)
    follow that degree: moving the degree moves them along (``leader`` = the degree's group id)."""
    for i, d in enumerate(groups):
        end = _study_end(d) if d["key"] in DEGREES else None
        if end is None:
            continue
        for g in groups[i + 1:]:
            if g["start_month"] < end or g["leader"] is not None:
                continue
            if g["key"] not in CHAIN_KEYS:
                break
            g["leader"] = d["id"]
            if g["key"] in ("grad_job", "master"):
                break


def _rest(inp: rv.Inputs, groups: list[dict]) -> list:
    used = {i for g in groups for i in g["idx"]}
    return [e for i, e in enumerate(inp.events) if i not in used]


def age_bounds(key: str, start_age: int, end_age: int) -> tuple[int, int]:
    """Ages an option can sit at in the alternative path (simple rules from the game's locks)."""
    lo, hi = start_age, end_age - 1
    if key == "retire":
        lo = max(lo, game.RETIRE_FROM)
    elif key == "child":
        lo, hi = max(lo, 22), min(hi, 50)
    elif key == "wedding":
        lo = max(lo, 22)
    elif key == "lehre":
        hi = min(hi, 25)
    elif key in DEGREES or key == "grad_job" or key == "job_start":
        hi = min(hi, 64)
    elif key in ("buy_house", "flat", "switch", "parttime", "gap_year"):
        hi = min(hi, 69)
    return lo, hi


def _target_month(key: str, age: float, inp: rv.Inputs) -> int:
    end_age = inp.person.age + inp.years
    lo, hi = age_bounds(key, inp.person.age, end_age)
    a = min(max(float(age), lo), max(hi, lo))
    return int(min(max(round((a - inp.person.age) * 12), 0), _T(inp) - 1))


def shift_events(events, delta: int, t_max: int) -> list:
    """Shift all events of one group by ``delta`` months (first event kept inside [0, t_max], offsets kept)."""
    events = list(events)
    if not events:
        return []
    lo = min(ev.start for ev in events)
    delta = int(min(max(delta, -lo), t_max - lo))
    return [replace(ev, start=int(min(max(ev.start + delta, 0), t_max))) for ev in events]


def _group_shift(g: dict, alt: dict, inp: rv.Inputs, shifts: dict, by_id: dict) -> int:
    """Months the group is shifted in the alt path (0 = not moved). A follower of a degree moves with the degree
    unless it is moved itself, and never starts before the (shifted) degree is finished."""
    if not g["events"]:
        return 0
    lead = by_id.get(g["leader"]) if g["leader"] else None
    lead_alive = lead is not None and lead["id"] not in alt["removed"]
    lo = min(ev.start for ev in g["events"])
    if g["id"] in alt["moves"]:
        new = _target_month(g["key"], alt["moves"][g["id"]], inp)
        if lead_alive:
            end = _study_end(lead)
            new = max(new, end + shifts.get(lead["id"], 0)) if end is not None else new
        delta = new - g["start_month"]
    elif lead_alive:
        delta = shifts.get(lead["id"], 0)
    else:
        return 0
    return int(min(max(delta, -lo), _T(inp) - 1 - lo))


def _snapshot_from_plan(plan, person, month: int) -> game.Snapshot:
    m = min(max(month, 0), plan.months - 1)
    return game.Snapshot(month, int(plan.state[m]), float(plan.income[m]), 0.0, 0.0, 0.0, 0.0, 0.0,
                         float(person.expenses + plan.extra_expenses[m]), 0.0)


def _added_events(inp: rv.Inputs, base: list, added: list, done: set, kids: int) -> tuple[list, dict]:
    """Events of the added options (in age order), each built on the alternative plan up to then.
    Returns (all events, {added id: its events})."""
    events = list(base)
    per: dict[str, list] = {}
    c = calibrate()
    for item in sorted(added, key=lambda x: (x["age"], x["id"])):
        opt = game.OPTION_BY_KEY[item["key"]]
        t = _target_month(item["key"], item["age"], inp)
        plan = build_plan(inp.person, events + game.forced_retirement(inp.person, events), _T(inp), c, inp.a)
        snap = _snapshot_from_plan(plan, inp.person, t)
        ctx = game.Ctx(snap, frozenset(done), inp.person.age + t // 12, kids, game.finished_degrees(plan, t))
        evs = list(opt.events(t, snap, ctx, item["params"]))
        per[item["id"]] = evs
        events += evs
        done.add(item["key"])
        kids += item["key"] == "child"
    # an ADDED degree comes with the job of that degree at graduation (as the card previews assume, see
    # game.assume_degree_jobs) unless the path already decides what comes next – else a what-if degree would mean
    # "never work again". The played life is left exactly as it was played.
    for iid, evs in per.items():
        for st in [e for e in evs if isinstance(e, Study) and not e.job_after and e.end_label in game.DEGREE_LABELS]:
            end = st.start + st.months
            if end >= _T(inp) or any(isinstance(e, (Job, SelfEmployment, Study, Retirement)) and e.start >= end
                                     for e in events if e is not st):
                continue
            t = end
            for e in sorted(events, key=lambda e: e.start):      # a gap year running then pushes the job back
                if isinstance(e, Unemployment) and e.start <= t < e.start + e.months:
                    t = e.start + e.months
            if t >= _T(inp):
                continue
            sal, exp = game.GRAD_JOBS[game.DEGREE_LABELS[st.end_label]]
            job = Job(t, sal, exp, "First job")
            per[iid] = per[iid] + [job]
            events.append(job)
    return events, per


def _build(inp: rv.Inputs, alt: dict) -> dict:
    """Everything about the alt path: events, groups, shifts, added events."""
    groups = _groups(inp)
    base = list(_rest(inp, groups))
    shifts, done, kids = {}, set(), 0
    t_max = _T(inp) - 1
    by_id = {g["id"]: g for g in groups}
    for g in groups:
        if g["id"] in alt["removed"]:
            continue
        d = _group_shift(g, alt, inp, shifts, by_id)
        shifts[g["id"]] = d
        base += shift_events(g["events"], d, t_max) if d else list(g["events"])
        done.add(g["key"])
        kids += g["key"] == "child"
    events, per = _added_events(inp, base, alt["added"], done, kids)
    return {"groups": groups, "shifts": shifts, "events": events, "added": per}


@lru_cache(maxsize=256)
def _build_cached(inp: rv.Inputs, alt_key: str) -> dict:
    return _build(inp, json.loads(alt_key))


def alt_events(sess, alt) -> list:
    """Events of the alternative life (without the forced retirement: ``game.play`` adds it)."""
    inp = _inputs(sess)
    if inp is None:
        return []
    return list(_build_cached(inp, _alt_key(alt))["events"])


def _same_events(a, b) -> bool:
    return Counter(a) == Counter(b)


# ---------------------------------------------------------------- simulation (cached)
@lru_cache(maxsize=512)
def _metrics(person, events: tuple, a, seed: int, years: int, n: int) -> dict:
    events = list(events)
    res = simulate(person, events + game.forced_retirement(person, events), years, a, n, seed, calib=calibrate(),
                   fixed_until=0, pct_series=())
    return dict(res.metrics)


@lru_cache(maxsize=128)
def _paths(person, events: tuple, a, seed: int, years: int) -> dict:
    res = game.play(person, list(events), a, calibrate(), seed, 0, years, pct_series=("net_worth",))
    pct, life = res.percentiles["net_worth"], res.path0["net_worth"]

    def yearly(arr):
        return [float(arr[min(12 * i, len(arr) - 1)]) for i in range(years + 1)]

    m = res.metrics
    return {"series": {"p5": yearly(pct[0]), "p50": yearly(pct[2]), "p95": yearly(pct[4]), "life": yearly(life)},
            "end": float(m["median_net_worth_end"]), "credit": float(m["p_credit_future"]),
            "labels": sorted((int(t), str(l)) for t, l in res.plan.labels)}


def _label(inp: rv.Inputs, alt: dict, built: dict) -> str | None:
    parts = []
    for g in built["groups"]:
        if g["id"] in alt["removed"]:
            parts.append(f"− {g['title']}")
        elif built["shifts"].get(g["id"]) and (g["id"] in alt["moves"] or not g["leader"]):
            parts.append(move_label(g["title"], built["shifts"][g["id"]]))
    for item in sorted(alt["added"], key=lambda x: (x["age"], x["id"])):
        opt = game.OPTION_BY_KEY[item["key"]]
        t = _target_month(item["key"], item["age"], inp)
        parts.append(f"+ {opt.title} at {inp.person.age + t // 12}")
    return " · ".join(parts) if parts else None


def move_label(title: str, delta_months: int) -> str:
    years = abs(delta_months) / 12
    if float(years).is_integer():
        n = int(years)
        span = f"{n} year" if n == 1 else f"{n} years"
    else:
        span = f"{abs(delta_months)} months"
    return f"{title} {span} {'later' if delta_months > 0 else 'earlier'}"


def simulate_paths(sess, alt=None) -> dict | None:
    """Expected net worth per year (start age .. end age) for the played life and the alternative path.

    {"ages", "played": {"p5", "p50", "p95", "life"}, "alt": same or None (no effective change), "label",
     "metrics": {"played_end", "alt_end", "delta_end", "played_credit", "alt_credit"}}. None without a game."""
    inp = _inputs(sess)
    if inp is None:
        return None
    alt = normalize(alt)
    played = _paths(inp.person, tuple(inp.events), inp.a, inp.seed, inp.years)
    built = _build_cached(inp, _alt_key(alt))
    other = None
    if not _same_events(built["events"], inp.events):
        other = _paths(inp.person, tuple(built["events"]), inp.a, inp.seed, inp.years)
    metrics = {"played_end": played["end"], "alt_end": other["end"] if other else None,
               "delta_end": (other["end"] - played["end"]) if other else None,
               "played_credit": played["credit"], "alt_credit": other["credit"] if other else None}
    return copy.deepcopy({"ages": [inp.person.age + i for i in range(inp.years + 1)],
                          "played": played["series"], "alt": other["series"] if other else None,
                          "label": _label(inp, alt, built) if other else None, "metrics": metrics})


# ---------------------------------------------------------------- timeline
def _end_labels(ev) -> list[tuple[int, str]]:
    """Follow-up labels an event produces later in the plan (degree finished, child moves out)."""
    if isinstance(ev, Study) and ev.end_label:
        return [(ev.start + ev.months, ev.end_label)]
    if isinstance(ev, ExpenseChange) and ev.months is not None and ev.end_label:
        return [(ev.start + int(ev.months), ev.end_label)]
    return []


def _event_item(iid: str, label: str, month: int, start_age: int, follows: str | None, cat: str) -> dict:
    a = game.anim_for(label)
    title = a[1] if a else label
    emoji = EVENT_EMOJI.get(a[0], "📍") if a else "📍"
    return {"id": iid, "kind": "event", "key": None, "emoji": emoji, "title": title, "cat": cat,
            "age": round(start_age + month / 12, 3), "alt_age": None, "removed": False, "movable": False,
            "impact": None, "follows": follows, "alt_only": False}


def timeline_items(sess, alt=None) -> list[dict]:
    """Decisions, follow-up events and added options for the timeline (played ages + their place in the alt path).

    Item: {id, kind: decision|event|added, key, emoji, title, cat, age, alt_age (None = unchanged), removed, movable,
    impact (decisions: as in twin.review), follows (events: id of the decision they belong to), alt_only}.
    ``alt_only`` events (e.g. the forced retirement once a played retirement is removed, the degree of an added
    bachelor) exist only in the alternative path: ``age`` is their place there. Added options: ``age`` = chosen age."""
    inp = _inputs(sess)
    if inp is None:
        return []
    alt = normalize(alt)
    start, T = inp.person.age, _T(inp)
    built = _build_cached(inp, _alt_key(alt))
    groups = built["groups"]
    review = rv.review(sess) if not isinstance(sess, rv.Inputs) else None
    impacts = [t["impact"] for t in (review or {}).get("timeline", [])]
    items: list[dict] = []
    for n, g in enumerate(groups):
        removed = g["id"] in alt["removed"]
        d = built["shifts"].get(g["id"], 0)
        age = start + g["start_month"] / 12
        items.append({"id": g["id"], "kind": "decision", "key": g["key"], "emoji": g["emoji"], "title": g["title"],
                      "cat": g["cat"], "age": round(age, 3),
                      "alt_age": round(age + d / 12, 3) if d and not removed else None,
                      "removed": removed, "movable": bool(g["events"]), "impact": impacts[n] if n < len(impacts) else None,
                      "follows": g["leader"], "alt_only": False})
    # follow-up events of the played life (plan labels that are not the start of a decision's own event)
    played = _paths(inp.person, tuple(inp.events), inp.a, inp.seed, inp.years)
    starts = Counter((int(e.start), e.label) for g in groups for e in g["events"])
    owner: dict[tuple[int, str], str] = {}
    for g in groups:
        for e in g["events"]:
            for key in _end_labels(e):
                owner.setdefault(key, g["id"])
    cat_of = {g["id"]: g["cat"] for g in groups}
    alt_retires = any(isinstance(e, Retirement) for e in built["events"])
    n_ev = 0
    for t, label in played["labels"]:
        if starts[(t, label)] > 0:
            starts[(t, label)] -= 1
            continue
        gid = owner.get((t, label))
        n_ev += 1
        item = _event_item(f"e{n_ev}", label, t, start, gid, cat_of.get(gid, "career"))
        if gid is not None:
            if gid in alt["removed"]:
                item["removed"] = True
            elif built["shifts"].get(gid):
                t2 = t + built["shifts"][gid]
                if t2 >= T:
                    item["removed"] = True
                else:
                    item["alt_age"] = round(start + t2 / 12, 3)
        elif label == "Retirement":
            forced = game.forced_retirement(inp.person, built["events"])
            if not forced:
                item["removed"] = True
        items.append(item)
    # forced retirement that only the alternative path has
    if not any(it["kind"] == "event" and it["title"] == "Retirement" for it in items) and not alt_retires:
        f = game.forced_retirement(inp.person, built["events"])
        if f and f[0].start < T:
            n_ev += 1
            it = _event_item(f"e{n_ev}", f[0].label, f[0].start, start, None, "career")
            it["alt_only"] = True
            items.append(it)
    # added options and their follow-ups
    for item in sorted(alt["added"], key=lambda x: (x["age"], x["id"])):
        opt = game.OPTION_BY_KEY[item["key"]]
        evs = built["added"].get(item["id"], [])
        t = min((e.start for e in evs), default=_target_month(item["key"], item["age"], inp))
        cat = rv.CAT_KEYS.get(opt.cat, opt.cat)
        title = opt.title
        if opt.params:
            vals = opt.values(item["params"])
            if item["key"] == "buy_house":
                title = f"{opt.title} ({rv.money(vals['price'])})"
            elif item["key"] == "costs":
                title = f"Monthly costs {'+' if vals['delta'] >= 0 else '−'}{rv.money(abs(vals['delta']))}"
        items.append({"id": item["id"], "kind": "added", "key": item["key"], "emoji": opt.emoji, "title": title,
                      "cat": cat, "age": round(start + t / 12, 3), "alt_age": None, "removed": False,
                      "movable": True, "impact": None, "follows": None, "alt_only": True})
        for e in evs:
            later = [(int(e.start), e.label)] if e.start > t else []      # e.g. the degree job at graduation
            for (t2, label) in later + _end_labels(e):
                if t2 < T:
                    n_ev += 1
                    it = _event_item(f"e{n_ev}", label, t2, start, item["id"], cat)
                    it["alt_only"] = True
                    items.append(it)
    items.sort(key=lambda x: (x["age"], 0 if x["kind"] != "event" else 1))
    return items


# ---------------------------------------------------------------- what can be added
def addable(sess) -> list[dict]:
    """Options that can be added to the alternative path: {key, emoji, title, text, cat, params, min_age, max_age}."""
    inp = _inputs(sess)
    if inp is None:
        return []
    start, end = inp.person.age, inp.person.age + inp.years
    out = []
    for opt in game.OPTIONS:
        lo, hi = age_bounds(opt.key, start, end)
        if lo > hi:
            continue
        params = {n: p.spec(p.snap(p.default)) for n, p in opt.params.items()}
        out.append({"key": opt.key, "emoji": opt.emoji, "title": opt.title, "text": opt.text_for(None, None),
                    "cat": rv.CAT_KEYS.get(opt.cat, opt.cat), "params": params, "min_age": lo, "max_age": hi})
    return out


# ---------------------------------------------------------------- suggestions
LIFE_CHOICES = ("child", "wedding")
SKIP_TITLE = {"bachelor": "No bachelor", "master": "No master", "lehre": "No apprenticeship",
              "grad_job": "No degree job", "job_start": "No entry job", "switch": "No job change",
              "parttime": "Stay full-time", "retire": "Work on instead of retiring", "buy_house": "Keep renting",
              "flat": "No luxury flat", "costs": "Keep your monthly costs", "gap_year": "No gap year"}


def _age_word(n: int) -> str:
    return f"{n} year" if n == 1 else f"{n} years"


def _candidates(inp: rv.Inputs, alt: dict, built: dict, screen_res) -> list[dict]:
    """Candidate edits: {id, emoji, title, kind, subject, what, edit}."""
    start, end = inp.person.age, inp.person.age + inp.years
    T = _T(inp)
    out = []
    # ---- move / drop the played decisions
    for g in built["groups"]:
        if g["id"] in alt["removed"] or not g["events"]:
            continue
        cur = start + (g["start_month"] + built["shifts"].get(g["id"], 0)) / 12
        lo, hi = age_bounds(g["key"], start, end)
        for dy in (-5, -3, 3, 5):
            new = int(round(cur + dy))
            if not lo <= new <= hi:
                continue
            out.append({"id": f"mv-{g['id']}-{dy:+d}", "emoji": g["emoji"], "kind": "move", "subject": g["id"],
                        "title": "", "what": "", "group": g, "cur": int(round(cur)),
                        "edit": {"moves": {g["id"]: new}}})
        if g["key"] in LIFE_CHOICES:          # kids and a wedding are life choices: suggest timing, not dropping
            continue
        skip = SKIP_TITLE.get(g["key"], f"Without: {g['title']}")
        out.append({"id": f"rm-{g['id']}", "emoji": g["emoji"], "kind": "remove", "subject": g["id"],
                    "title": skip, "what": f"{skip} – instead of {g['title'].lower()} at {int(round(cur))}",
                    "edit": {"removed": [g["id"]]}})
    # ---- add options that were not taken
    have = Counter(g["key"] for g in built["groups"] if g["id"] not in alt["removed"])
    have.update(x["key"] for x in alt["added"])
    plan = build_plan(inp.person, built["events"] + game.forced_retirement(inp.person, built["events"]), T,
                      calibrate(), inp.a)
    working = np.isin(plan.state, (EMPLOYED, SELF_EMPLOYED))
    retire_t = next((t for t, l in sorted(plan.labels) if l in ("Retired", "Retirement")), T)

    def first_working(age_from: int) -> int | None:
        t0 = max(0, 12 * (age_from - start))
        idx = np.nonzero(working[t0:min(retire_t, T)])[0]
        return None if not len(idx) else start + (t0 + int(idx[0]) + 11) // 12

    def add(key: str, age: int | None, params: dict | None = None, title: str | None = None, sid: str | None = None):
        if age is None:
            return
        lo, hi = age_bounds(key, start, end)
        if not lo <= age <= hi:
            return
        opt = game.OPTION_BY_KEY[key]
        out.append({"id": sid or f"add-{key}-{age}", "emoji": opt.emoji, "kind": "add", "subject": key,
                    "title": title or f"{opt.title} at {age}", "what": title or f"{opt.title} at {age}",
                    "edit": {"added": [{"key": key, "age": age, "params": dict(params or {})}]}})

    # a home at the first age the median down payment is there (850k, else a cheaper one)
    if not have["buy_house"] and screen_res is not None:
        liquid = screen_res.percentiles["liquid"][2]
        level = (1 + game.INFLATION) ** (np.arange(T + 1) / 12)
        exp = inp.person.expenses + np.append(plan.extra_expenses, plan.extra_expenses[-1])
        for price in (850_000, 600_000):
            need = (0.22 * price + np.maximum(exp, 0.0)) * level
            ok = np.nonzero((liquid[:T] >= need[:T]) & working & (np.arange(T) < retire_t))[0]
            ok = ok[ok >= 12 * max(0, 25 - start)]
            if len(ok):
                age = start + (int(ok[0]) + 11) // 12
                add("buy_house", age, {"price": price}, f"Buy a {rv.money(price)} home at {age}",
                    f"add-buy_house-{price // 1000}k-{age}")
                break
    if not have["switch"]:
        add("switch", first_working(start + 2))
    if not have["parttime"]:
        add("parttime", first_working(max(start, 45)))
    add("gap_year", first_working(max(start, 30)))
    add("costs", start, {"delta": -300}, f"Spend CHF 300 less a month from {start}", f"add-costs-300-{start}")
    if not have["flat"]:
        add("flat", first_working(max(start, 28)))
    if have["child"] < 2:
        add("child", max(start, 30))
    if not have["wedding"]:
        add("wedding", max(start, 30))
    retire_age = start + retire_t // 12
    for age in (60, 65):
        if age < retire_age:
            add("retire", age, None, f"Retire at {age}")
    # dedupe by id
    seen, uniq = set(), []
    for c in out:
        if c["id"] not in seen:
            seen.add(c["id"])
            uniq.append(c)
    return uniq


def _full(inp: rv.Inputs, events) -> dict:
    return _metrics(inp.person, tuple(events), inp.a, inp.seed, inp.years, game.N_PATHS)


def _house_fails(m: dict, base: dict) -> bool:
    """The edit makes a home purchase fail in most lives (the down payment is not there)."""
    p, p0 = m.get("p_house_failed", 0.0), base.get("p_house_failed", 0.0)
    return p > 0.5 and p > p0 + 0.05


@lru_cache(maxsize=64)
def _suggestions(inp: rv.Inputs, alt_key: str, n: int) -> list[dict]:
    alt = json.loads(alt_key)
    built = _build_cached(inp, alt_key)
    base_events = built["events"]
    end_age = inp.person.age + inp.years
    vs = "your new path" if not _same_events(base_events, inp.events) else "your life"
    base_events_full = list(base_events) + game.forced_retirement(inp.person, list(base_events))
    screen_res = simulate(inp.person, base_events_full, inp.years, inp.a, SCREEN_PATHS, inp.seed,
                          calib=calibrate(), fixed_until=0, pct_series=("liquid",))
    base_screen = float(screen_res.metrics["median_net_worth_end"])
    scored = []
    for c in _candidates(inp, alt, built, screen_res):
        new_alt = apply_edit(alt, c["edit"])
        new_built = _build_cached(inp, _alt_key(new_alt))
        evs = new_built["events"]
        if _same_events(evs, base_events):
            continue
        if c["kind"] == "move":            # the title says where the decision really lands (bounds, degree end)
            g = c.pop("group")
            eff = int(round(inp.person.age + (g["start_month"] + new_built["shifts"].get(g["id"], 0)) / 12))
            dy = eff - c["cur"]
            if dy == 0:
                continue
            c["id"] = f"mv-{g['id']}-{eff}"
            c["edit"] = {"moves": {g["id"]: eff}}
            c["title"] = f"{g['title']} {_age_word(abs(dy))} {'earlier' if dy < 0 else 'later'}"
            c["what"] = f"{g['title']} at {eff} instead of {c['cur']}"
        m = _metrics(inp.person, tuple(evs), inp.a, inp.seed, inp.years, SCREEN_PATHS)
        if _house_fails(m, screen_res.metrics):
            continue
        d = float(m["median_net_worth_end"]) - base_screen
        if abs(d) < 1.0 or any(x[1]["id"] == c["id"] for x in scored):
            continue                       # no effect at all (e.g. overridden by a later decision) / duplicate
        scored.append((d, c, evs))
    if not scored:
        return []
    # re-check the most promising and the most instructive negatives with the full path count
    scored.sort(key=lambda x: -x[0])
    top = scored[:n + 3]
    pick = top + [x for x in scored[-6:] if all(x[1]["id"] != y[1]["id"] for y in top)]
    base_m = _full(inp, base_events)
    base_full = base_m["median_net_worth_end"]
    checked = []
    for _, c, evs in pick:
        m = _full(inp, evs)
        if _house_fails(m, base_m):
            continue                       # a home that most lives could not pay for is no suggestion
        delta = float(m["median_net_worth_end"] - base_full)
        imp = game.impact(delta, base_full) or "flat"
        checked.append({"id": c["id"], "emoji": c["emoji"], "title": c["title"], "kind": c["kind"],
                        "subject": c["subject"],
                        "text": f"{c['what']}: {rv.money_delta(delta)} at {end_age} compared with {vs}.",
                        "edit": copy.deepcopy(c["edit"]), "impact": imp, "delta": delta,
                        "credit": float(m["p_credit_future"])})

    def distinct(rows):
        seen, out = set(), []
        for r in rows:
            if r["subject"] in seen:
                continue
            seen.add(r["subject"])
            out.append(r)
        return out

    ups = distinct(sorted([r for r in checked if r["impact"] == "up"], key=lambda r: -r["delta"]))
    downs = distinct(sorted([r for r in checked if r["impact"] == "down"], key=lambda r: r["delta"]))
    flats = distinct(sorted([r for r in checked if r["impact"] == "flat" and abs(r["delta"]) >= 1.0],
                            key=lambda r: -abs(r["delta"])))
    n_down = min(len(downs), max(2, n - len(ups)))
    n_up = min(len(ups), n - n_down)
    chosen = ups[:n_up] + downs[:n_down]
    if len(chosen) < n:
        chosen += [r for r in flats if r["subject"] not in {x["subject"] for x in chosen}][:n - len(chosen)]
    return chosen


def suggestions(sess, alt=None, n: int = 6) -> list[dict]:
    """The twin's suggestions for another path, a MIX: the best positive ones and at least 2 instructive negative
    ones (when the simulation has any). Each: {id, emoji, title, text, edit (partial alt to merge with
    ``apply_edit``), impact up|down|flat, delta (CHF median at the end vs the current alt path or the played life),
    kind move|remove|add, subject, credit (share of lives that need a loan)}."""
    inp = _inputs(sess)
    if inp is None or n <= 0:
        return []
    return copy.deepcopy(_suggestions(inp, _alt_key(alt), int(n)))
