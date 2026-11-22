"""Game-style "TWIN VS. REALITY" card for the backtest (``twin.backtest.backtest``).

Same look as ``twin/lifechart/review_view.py`` (Lilita One title band, chunky card with ink border and hard shadow);
it reuses that module's ``.lr`` classes, so the page must have ``review_view.style_block()`` once (the analysis page
already does), or call ``backtest_card_html(result, with_style=True)`` for a standalone page.

Returns ONE line of HTML (for ``st.markdown(..., unsafe_allow_html=True)``); every text is escaped.
"""
from __future__ import annotations

import html

from .lifechart.review_view import style_block

STATUS_LABEL = {"employed": "Employed", "part_time": "Part-time", "self_employed": "Self-employed",
                "retired": "Retired", "student": "Students", "unemployed": "Unemployed"}
TARGET = 0.90            # a calibrated 90 % band should catch ~90 % of the real outcomes

CSS = """
.bt-body{padding:16px 20px 14px;background:linear-gradient(180deg,#f3f0ff,#fff)}
.lr p.bt-head{font-family:var(--fd);font-weight:400;font-size:26px;line-height:1.15;color:var(--ink);margin:0 0 4px}
.bt-head b{font-weight:400;color:var(--green-d)}
.lr p.bt-sub{font-weight:800;font-size:14px;color:#5b5391;margin:0 0 12px}
.lr ul.bt-bars{list-style:none;margin:0;padding:0}
.lr li.bt-row{display:grid;grid-template-columns:128px 1fr 54px;gap:10px;align-items:center;padding:5px 0;
font-weight:900;font-size:14px}
.bt-row .n{font-weight:700;font-size:12px;color:#7a73a3;margin-left:4px}
.bt-track{position:relative;height:18px;border:3px solid var(--ink);border-radius:999px;background:#eceaf6;
overflow:hidden;box-shadow:0 3px 0 var(--ink)}
.bt-fill{position:absolute;left:0;top:0;bottom:0;background:linear-gradient(180deg,#6ff0a4,#17b862)}
.bt-fill.low{background:linear-gradient(180deg,#ffd27a,#f0a020)}
.bt-target{position:absolute;top:-2px;bottom:-2px;border-left:3px dashed var(--ink)}
.bt-row .v{font-family:var(--fd);font-weight:400;font-size:17px;text-align:right}
.lr p.bt-note{margin:12px 0 0;font-weight:700;font-size:12.5px;line-height:1.35;color:#5b5391}
@media (max-width:520px){.lr li.bt-row{grid-template-columns:96px 1fr 46px}.lr p.bt-head{font-size:21px}}
"""


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def backtest_card_html(result: dict, with_style: bool = False) -> str:
    """The card for a ``backtest()`` result: headline coverage, one mini bar per employment status, method note."""
    n = int(result.get("n_profiles", 0))
    cov = float(result.get("coverage_90", 0.0))
    rows = []
    for status, v in (result.get("by_status") or {}).items():
        c = float(v.get("coverage_90", 0.0))
        low = " low" if c < TARGET - 0.05 else ""
        label = STATUS_LABEL.get(status, status.replace("_", " ").capitalize())
        rows.append(f'<li class="bt-row"><span>{_e(label)}<span class="n">{int(v.get("n", 0)):,}</span></span>'
                    f'<span class="bt-track" role="img" aria-label="{_e(label)}: {_pct(c)} inside the band">'
                    f'<span class="bt-fill{low}" style="width:{min(max(c, 0.0), 1.0) * 100:.1f}%"></span>'
                    f'<span class="bt-target" style="left:{TARGET * 100:.0f}%"></span></span>'
                    f'<span class="v">{_pct(c)}</span></li>')
    sub = (f'Typical miss of the median forecast: CHF {result.get("median_abs_error_chf", 0):,.0f} '
           f'({result.get("median_abs_error_pct", 0) * 100:.1f} % of the balance) · inner 50 % band: '
           f'{_pct(float(result.get("coverage_50", 0.0)))} · dashed line = 90 % target')
    note = str(result.get("method", ""))
    if not result.get("param_uncertainty", True):
        note += " Without parameter uncertainty."
    body = (f'<div class="bt-body"><p class="bt-head">The 90 % band caught <b>{_pct(cov)}</b> of {n:,} real outcomes'
            f'</p><p class="bt-sub">{_e(sub)}</p><ul class="bt-bars">{"".join(rows)}</ul>'
            f'<p class="bt-note">{_e(note)}</p></div>')
    style = (style_block() if with_style else "") + "<style>" + " ".join(CSS.split()) + "</style>"
    return (f'{style}<div class="lr"><section class="lr-card"><div class="lr-band good"><span class="ol">'
            f'TWIN VS. REALITY</span></div>{body}</section></div>')
