"""Life chart: Juli's financial-twin chart (chart.js / timeline.js) as a small static Streamlit component.

Look & interaction: p5–p95 band, median of the plan, one simulated life, a dashed comparison line ("two life
paths", switchable inside the chart), event markers with labels, hover / keyboard readout per month and age.
The frontend lives in ``frontend/`` (plain HTML + JS, no build step, no CDN, works offline). It is one-way: the
chart never sends a value back.

All numbers come from our simulation: :func:`chart_data` turns ``engine.Result`` objects into the JSON the
frontend draws (``args.data``)::

    {"start_age": int,
     "plan": {"label": str, "p5": [..], "p50": [..], "p95": [..], "life": [..]},   # one value per month
     "comps": [{"key": str, "label": str, "p5": [..], "p50": [..], "p95": [..]}],
     "default_comp": str | None, "events": [{"month": int, "label": str}], "summary": str, "height": int}
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

FRONTEND = Path(__file__).parent / "frontend"
_component = None


def _declare():
    global _component
    if _component is None:
        import streamlit.components.v1 as components
        _component = components.declare_component("lifechart", path=str(FRONTEND))
    return _component


def _ints(a) -> list[int]:
    return [int(round(float(v))) if np.isfinite(v) else 0 for v in np.asarray(a, dtype=float)]


def chart_data(res, comps: list[tuple[str, str, object]] | None = None, start_age: int | None = None,
               plan_label: str = "Your plan", default_comp: str | None = None, summary: str = "",
               height: int = 340, hide_label_prefix: str = "") -> dict:
    """JSON for the chart from a main ``Result`` and comparison runs ``[(key, label, Result), ...]``.

    Comparison series are cut / padded to the length of the main run. Event labels starting with
    ``hide_label_prefix`` keep the prefix stripped (e.g. "Crisis: Market crash" -> "Market crash")."""
    p = res.percentiles["net_worth"]
    n = p.shape[1]
    life = res.path0.get("net_worth") if getattr(res, "path0", None) else None
    data = {
        "start_age": int(res.person.age if start_age is None else start_age),
        "plan": {"label": plan_label, "p5": _ints(p[0]), "p50": _ints(p[2]), "p95": _ints(p[4]),
                 "life": _ints(life[:n]) if life is not None else None},
        "comps": [], "default_comp": default_comp, "summary": summary, "height": int(height),
        "events": [],
    }
    for key, label, r in comps or []:
        if r is None:
            continue
        q = r.percentiles["net_worth"][:, :n]
        if q.shape[1] < n:                       # shorter run: hold the last value
            q = np.concatenate([q, np.repeat(q[:, -1:], n - q.shape[1], axis=1)], axis=1)
        data["comps"].append({"key": str(key), "label": str(label), "p5": _ints(q[0]), "p50": _ints(q[2]),
                              "p95": _ints(q[4])})
    for t, label in res.plan.labels:
        if 0 <= int(t) < n:
            lbl = str(label)
            if hide_label_prefix and lbl.startswith(hide_label_prefix):
                lbl = "⚡ " + lbl[len(hide_label_prefix):]
            data["events"].append({"month": int(t), "label": lbl})
    if data["default_comp"] not in {c["key"] for c in data["comps"]}:
        data["default_comp"] = data["comps"][0]["key"] if data["comps"] else None
    return data


def life_chart(data: dict, key: str | None = "lifechart") -> None:
    """Render the chart (one-way component; returns nothing)."""
    _declare()(data=data, key=key, default=None)
