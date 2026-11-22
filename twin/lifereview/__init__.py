"""Life review component: editable timeline, the twin's suggestion cards and the expected-net-worth chart.

One static Streamlit component (``frontend/``: plain HTML + JS + CSS, no build step, no CDN, the game's fonts as
local woff2 copies) with three views, picked by ``view``:

``"timeline"``     the played life from the start age to ``end_age`` (85) with ALL events. Decisions are chips in
                   lanes above a yellow age axis (ticks every 5 years), coloured by their effect (▲ green / ▼ red /
                   ● grey); follow-up events ("Degree finished", "Child moves out", …) sit below the axis and move
                   with their decision. Drag a chip (or focus it and press ←/→, Shift = 5 years) to move it, ✕ /
                   Delete removes it, ↺ brings it back, "+ Add event" opens a menu of ``addable`` options with an age
                   slider and parameter sliders, "Reset" drops the whole alternative path.
                   data: ``{start_age, end_age, items: alt_path.timeline_items(...), addable: alt_path.addable(...),
                   has_alt: bool, title?, hint?}``
                   actions: ``{"action": "move", "id", "age"}``, ``{"action": "remove", "id"}``,
                   ``{"action": "restore", "id"}``, ``{"action": "add", "key", "age", "params"}``, ``{"action": "reset"}``
``"suggestions"``  cards ``{id, emoji, title, text, impact, delta, applied?}`` with "Try it".
                   data: ``{items: alt_path.suggestions(...), loading?: bool, end_age?: 85, vs?: "your path",
                   title?, intro?}``  ·  action: ``{"action": "apply", "id"}``
``"chart"``        expected net worth by age: played median + p5–p95 band + "your life" (pink), the alternative
                   path's median (orange, dashed) + band, event markers, hover / arrow-key readout, legend and the
                   summary line "New path: +CHF X at 85 vs. your path".
                   data: ``alt_path.simulate_paths(...)`` plus ``markers`` (see :func:`chart_markers`) or ``items``,
                   optional ``height`` (canvas px), ``title``, ``subtitle``, ``summary``  ·  no actions.

Every value the frontend posts carries a ``nonce``; :func:`lifereview` returns each action exactly once (a Streamlit
component keeps returning its last value on every rerun) and validates its shape, so the page can apply it directly.
Opened outside Streamlit (``python3 -m http.server`` in ``frontend/``) the page shows all three views with demo data.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

FRONTEND = Path(__file__).parent / "frontend"
VIEWS = ("timeline", "suggestions", "chart")
ACTIONS = {"timeline": {"move", "remove", "restore", "add", "reset"}, "suggestions": {"apply"}, "chart": set()}
END_AGE = 85
_NONCES = "_lifereview_nonces"        # st.session_state: {component key: last nonce handled}
_component = None


def _declare():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("lifereview", path=str(FRONTEND))
    return _component


# ---------------------------------------------------------------- JSON
def jsonable(obj: Any) -> Any:
    """Plain JSON types only: numpy scalars / arrays -> numbers / lists, tuples / sets -> lists, NaN / inf -> None."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in obj]
    tolist = getattr(obj, "tolist", None)            # numpy array / scalar
    if callable(tolist):
        return jsonable(tolist())
    item = getattr(obj, "item", None)
    if callable(item):
        return jsonable(item())
    try:
        f = float(obj)
    except (TypeError, ValueError):
        return str(obj)
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------- actions
def _int(v) -> int | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(round(f)) if math.isfinite(f) else None


def parse_action(value: Any, view: str | None = None) -> dict | None:
    """Validate a posted value -> ``{"action", "nonce", ...}`` with clean types, or None if it is not a valid action
    (for ``view``, when given)."""
    if not isinstance(value, dict):
        return None
    action = value.get("action")
    allowed = ACTIONS.get(view) if view else set().union(*ACTIONS.values())
    if not isinstance(action, str) or allowed is None or action not in allowed:
        return None
    out: dict[str, Any] = {"action": action, "nonce": str(value.get("nonce", ""))}
    if action in ("move", "remove", "restore", "apply"):
        gid = value.get("id")
        if gid is None or isinstance(gid, (dict, list)) or str(gid) == "":
            return None
        out["id"] = str(gid)
    if action in ("move", "add"):
        age = _int(value.get("age"))
        if age is None:
            return None
        out["age"] = age
    if action == "add":
        key = value.get("key")
        if not isinstance(key, str) or not key:
            return None
        out["key"] = key
        params = value.get("params") if isinstance(value.get("params"), dict) else {}
        clean = {}
        for k, v in params.items():
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(f):
                clean[str(k)] = int(f) if f.is_integer() else f
        out["params"] = clean
    return out


def fresh_action(value: Any, seen: dict, key: str, view: str | None = None) -> dict | None:
    """``parse_action`` + nonce dedupe: return the action only the first time its nonce shows up for ``key``
    (``seen`` is updated in place)."""
    act = parse_action(value, view)
    if act is None or not act["nonce"] or seen.get(key) == act["nonce"]:
        return None
    seen[key] = act["nonce"]
    return act


# ---------------------------------------------------------------- data builders (optional helpers for the page)
def timeline_data(items: list[dict], addable: list[dict] | None = None, start_age: int = 25, end_age: int = END_AGE,
                  has_alt: bool | None = None, **extra) -> dict:
    """Data for the timeline view. ``has_alt`` defaults to "any item is moved / removed / added"."""
    if has_alt is None:
        has_alt = any(it.get("removed") or it.get("kind") == "added"
                      or (it.get("alt_age") is not None and abs(float(it["alt_age"]) - float(it.get("age", 0))) > 1e-6)
                      for it in items or [])
    return jsonable({"start_age": int(start_age), "end_age": int(end_age), "items": list(items or []),
                     "addable": list(addable or []), "has_alt": bool(has_alt), **extra})


def suggestions_data(items: list[dict] | None, loading: bool = False, end_age: int = END_AGE, **extra) -> dict:
    """Data for the suggestions view (the ``edit`` of each suggestion stays on the Python side)."""
    keep = ("id", "emoji", "title", "text", "impact", "delta", "applied")
    rows = [{k: s.get(k) for k in keep if k in s} for s in items or []]
    return jsonable({"items": rows, "loading": bool(loading), "end_age": int(end_age), **extra})


def chart_markers(items: list[dict] | None, has_alt: bool = True) -> list[dict]:
    """Event markers for the chart from ``timeline_items``: every played item at its played age (``path`` "played"),
    plus moved / added ones at their age in the alternative path (``path`` "alt"). Removed items keep only the
    played marker."""
    out = []
    for it in items or []:
        try:
            age = float(it.get("age"))
        except (TypeError, ValueError):
            continue
        base = {"emoji": str(it.get("emoji") or ""), "label": str(it.get("title") or "")}
        alt = it.get("alt_age")
        if it.get("kind") != "added":
            out.append({"age": age, "path": "played", **base})
        if not has_alt or it.get("removed"):
            continue
        if it.get("kind") == "added":
            out.append({"age": float(alt if alt is not None else age), "path": "alt", **base})
        elif alt is not None and abs(float(alt) - age) > 1e-6:
            out.append({"age": float(alt), "path": "alt", **base})
    return out


def chart_data(paths: dict, items: list[dict] | None = None, height: int | None = None, **extra) -> dict:
    """Data for the chart view from ``alt_path.simulate_paths`` output and (optionally) ``timeline_items``."""
    data = dict(paths or {})
    data["markers"] = chart_markers(items, has_alt=bool(data.get("alt")))
    if height:
        data["height"] = int(height)
    data.update(extra)
    return jsonable(data)


# ---------------------------------------------------------------- the component
def lifereview(view: str, data: dict, key: str, height: int | None = None) -> dict | None:
    """Render one view; returns a NEW action dict (see module doc) once, otherwise None.

    ``height`` is the minimum frame height in px (the frame grows to its content on its own)."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}, not {view!r}")
    value = _declare()(view=view, data=jsonable(data or {}), height=int(height) if height else 0,
                       key=key, default=None)
    if view == "chart":
        return None
    try:
        import streamlit as st
        seen = st.session_state.setdefault(_NONCES, {})
    except Exception:                                  # no Streamlit session (bare script / tests)
        seen = _fallback_seen
    return fresh_action(value, seen, key, view)


_fallback_seen: dict = {}
