"""Game-style HTML blocks for the top of the analysis page: header with the verdict, timeline, positives / negatives.

Same look as the game (``twin/frontend3d``): Lilita One titles with a dark ink outline, Nunito text, chunky rounded
cards with 4px ink borders and a hard drop shadow, the game's colours. The fonts are the game's own woff2 files,
embedded as base64 ``@font-face`` (offline, no CDN). The timeline follows Juli's financial-twin timeline (horizontal
age axis with an arrow, ticks, event chips lifted in lanes above the axis); here it is read-only and every chip is
coloured by its effect on the net worth at the end: green ▲ better, red ▼ costs money, grey ● about the same.

All functions return ONE line of HTML (no blank lines, so ``st.markdown(..., unsafe_allow_html=True)`` keeps it as
HTML); every text is escaped.
"""
from __future__ import annotations

import base64
import html
from functools import lru_cache
from pathlib import Path

FONTS = Path(__file__).resolve().parents[1] / "frontend3d" / "fonts"
CHIP_W = 180             # px a chip needs on the axis (max-width 170 + air): closer chips go to the next lane
WIDTHS = (980, 1400, 2000, 2800, 4000)   # track widths tried until the chips fit in MAX_LANES lanes (then it scrolls)
MAX_LANES = 4
ARROW = {"up": ("▲", "Better for your money"), "down": ("▼", "Costs you money"), "flat": ("●", "About the same")}
LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, "
         "U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")
LATIN_EXT = ("U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+1D00-1DBF, U+1E00-1E9F, "
             "U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF")

CSS = """
.lr{--ink:#1d1446;--ink2:#2b2063;--yellow:#ffd23f;--green:#2fd27a;--green-d:#13a157;--red:#ff5a4e;--red-d:#d8322a;
--grey:#9b95b8;--fd:'Lilita One','Arial Rounded MT Bold','Trebuchet MS',system-ui,sans-serif;
--fu:'Nunito',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;font-family:var(--fu);color:var(--ink);
margin:6px 0 22px}
.lr *{box-sizing:border-box}
.lr p,.lr li,.lr ul{font-family:var(--fu);margin:0;padding:0}
.lr li::marker{content:""}
.lr .ol{-webkit-text-stroke:var(--sw,6px) var(--ink);paint-order:stroke fill;text-shadow:0 var(--sd,4px) 0 var(--ink)}
.lr-card{background:#fff;border:4px solid var(--ink);border-radius:24px;box-shadow:0 8px 0 var(--ink);overflow:hidden}
.lr-band{padding:10px 18px 12px;border-bottom:4px solid var(--ink);text-align:center;
background:linear-gradient(180deg,#4f97ff,#1f5fe6)}
.lr-band span{font-family:var(--fd);color:#fff;font-size:26px;letter-spacing:.05em;--sw:6px;--sd:3px}
.lr-band.good{background:linear-gradient(180deg,#6ff0a4,#17b862)}
.lr-band.bad{background:linear-gradient(180deg,#ff9a6b,#f0412a)}
.lr-hero{position:relative;display:flex;align-items:center;gap:22px;flex-wrap:wrap;color:#fff;padding:30px 28px 24px;
background:linear-gradient(180deg,#3b2d8f 0%,#23185c 100%);border:5px solid #fff;border-radius:30px;
box-shadow:0 0 0 5px var(--ink),0 12px 0 5px var(--ink);margin:18px 6px 26px}
.lr-tag{position:absolute;top:-18px;left:-10px;transform:rotate(-6deg);font-family:var(--fd);font-size:20px;
letter-spacing:.1em;color:var(--ink);background:linear-gradient(180deg,#ffe577,#ffb800);border:4px solid var(--ink);
border-radius:999px;padding:3px 16px 5px;box-shadow:0 5px 0 var(--ink)}
.lr-hero .ttl{margin:0;padding:0;font-family:var(--fd);font-weight:400;font-size:44px;line-height:1.05;color:#fff;
letter-spacing:.03em;--sw:8px;--sd:5px}
.lr .lr-hero p.sub{margin:6px 0 0;font-weight:800;font-size:16px;color:#d9d2ff}
.lr-hero .txt{flex:1 1 320px;min-width:0}
.lr-grade{flex:0 0 auto;width:112px;height:112px;border-radius:50%;display:flex;align-items:center;justify-content:center;
background:radial-gradient(circle at 35% 30%,#fff6b0,#ffd23f 45%,#f2a900);border:5px solid var(--ink);
box-shadow:0 7px 0 var(--ink);font-family:var(--fd);font-size:64px;color:#fff;--sw:8px;--sd:4px}
.lr-grade.g-D,.lr-grade.g-E{background:radial-gradient(circle at 35% 30%,#ffc2a8,#ff7a4e 45%,#e2421f)}
.lr-verdict{flex:1 1 100%;background:rgba(255,255,255,.1);border:3px solid rgba(255,255,255,.35);border-radius:18px;
padding:10px 14px;font-weight:800;font-size:16px;line-height:1.4}
.lr-verdict b{font-family:var(--fd);font-weight:400;font-size:22px;letter-spacing:.02em;color:var(--yellow);
margin-right:6px}
.lr-tl-body{padding:14px 12px 10px;background:linear-gradient(180deg,#bfe3ff,#e8f5ff)}
.lr-scroll{overflow-x:auto;padding:0 0 6px;scrollbar-width:thin}
.lr-track{position:relative;min-width:980px;margin:0 70px;height:calc(86px + var(--lanes,1) * 50px);--axis:40px}
.lr-axis{position:absolute;left:0;right:0;bottom:var(--axis);height:12px;border-radius:8px;background:var(--yellow);
border:3px solid var(--ink);box-shadow:0 3px 0 var(--ink)}
.lr-axis::after{content:"";position:absolute;right:-20px;top:-11px;border-block:14px solid transparent;
border-left:20px solid var(--ink)}
.lr-ticks{position:absolute;left:0;right:0;bottom:0;height:30px}
.lr-ticks span{position:absolute;transform:translateX(-50%);font-family:var(--fd);font-size:15px;color:var(--ink);
white-space:nowrap}
.lr-mark{position:absolute;bottom:calc(var(--axis) + 6px);--lift:calc(16px + var(--lane,0) * 50px)}
.lr-mark::before{content:"";position:absolute;left:-1.5px;bottom:0;height:var(--lift);border-left:3px solid var(--ink)}
.lr-mark::after{content:"";position:absolute;left:-8px;bottom:-9px;width:16px;height:16px;border-radius:50%;
border:3px solid var(--ink);background:var(--c,#fff)}
.lr-chip{position:absolute;left:0;bottom:var(--lift);transform:translateX(-50%);display:flex;align-items:center;gap:5px;
max-width:170px;padding:4px 9px 5px 7px;border:3px solid var(--ink);border-radius:14px;background:var(--bg,#fff);
box-shadow:0 4px 0 var(--ink);white-space:nowrap;font-weight:900;font-size:13px;line-height:1.1}
.lr-chip .e{font-size:18px}
.lr-chip .t{overflow:hidden;text-overflow:ellipsis;min-width:0}
.lr-chip .a{font-family:var(--fd);font-weight:400;font-size:14px;color:#5b5391}
.lr-chip .ar{font-size:14px;color:var(--c,var(--ink))}
.lr-up{--c:var(--green-d);--bg:#d8fbe6}.lr-down{--c:var(--red-d);--bg:#ffe1dc}.lr-flat{--c:#6b6394;--bg:#eceaf6}
.lr-none{--c:#2f7bff;--bg:#fff}
.lr-legend{display:flex;flex-wrap:wrap;gap:8px 18px;justify-content:center;padding:8px 10px 2px;font-weight:900;
font-size:13px}
.lr-legend i{font-style:normal;margin-right:4px}
.lr p.lr-empty{text-align:center;font-weight:800;color:#5b5391;padding:4px 0 10px}
.lr-cols{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin-top:26px}
@media (max-width:760px){.lr-cols{grid-template-columns:1fr}.lr-hero .ttl{font-size:34px}.lr-grade{width:88px;height:88px;
font-size:48px}}
.lr ul.lr-items{list-style:none;margin:0;padding:8px 14px 14px}
.lr li.lr-item{display:flex;gap:12px;align-items:flex-start;padding:12px 2px;border-bottom:3px dashed #e3defa}
.lr li.lr-item:last-child{border-bottom:0}
.lr-ic{flex:0 0 48px;height:48px;border-radius:50%;border:3px solid var(--ink);box-shadow:0 3px 0 var(--ink);
display:flex;align-items:center;justify-content:center;font-size:24px;background:#d8fbe6}
.bad .lr-ic,.lr-items.bad .lr-ic{background:#ffe1dc}
.lr-item .it{margin:0 0 2px;padding:0;font-family:var(--fd);font-weight:400;font-size:20px;line-height:1.1;
letter-spacing:.01em;color:var(--ink)}
.lr .lr-item p{margin:0;font-weight:700;font-size:14px;line-height:1.35;color:#4d4575}
.lr .lr-item p.lr-better{margin-top:7px;color:var(--ink)}
.lr-better span{display:inline-block;font-family:var(--fd);font-weight:400;font-size:13px;letter-spacing:.06em;
background:linear-gradient(180deg,#ffe577,#ffb800);border:3px solid var(--ink);border-radius:999px;padding:0 9px 1px;
margin-right:6px;box-shadow:0 2px 0 var(--ink)}
.lr-h{font-family:var(--fd);font-weight:400;font-size:30px;letter-spacing:.04em;color:#fff;margin:26px 4px 10px;
--sw:7px;--sd:4px}
.lr p.lr-hsub{display:inline-block;margin:-2px 4px 12px;padding:6px 12px 7px;background:#fff;border:3px solid var(--ink);
border-radius:14px;box-shadow:0 3px 0 var(--ink);font-weight:800;font-size:14px;line-height:1.35;color:#4d4575}
.lr-speech{position:relative;margin:8px 0 6px 16px;background:#fff;border:4px solid var(--ink);border-radius:26px;
box-shadow:0 8px 0 var(--ink);padding:16px 16px 8px}
.lr-speech::before{content:"";position:absolute;left:-17px;top:70px;width:26px;height:26px;background:#fff;
border-left:4px solid var(--ink);border-bottom:4px solid var(--ink);transform:rotate(45deg);border-radius:0 0 0 6px}
.lr-who{display:inline-block;font-family:var(--fd);font-size:16px;letter-spacing:.08em;color:var(--ink);
background:linear-gradient(180deg,#ffe577,#ffb800);border:3px solid var(--ink);border-radius:999px;padding:1px 12px 3px;
box-shadow:0 3px 0 var(--ink);transform:rotate(-2deg)}
.lr .lr-speech p.lr-say{margin:10px 2px 4px;font-weight:800;font-size:16px;line-height:1.4;color:var(--ink)}
.lr-say b{font-family:var(--fd);font-weight:400;font-size:20px;letter-spacing:.02em;color:#3b2d8f;margin-right:4px}
.lr-sh{display:flex;align-items:center;gap:8px;margin:12px 0 0;padding:6px 12px 7px;border:3px solid var(--ink);
border-radius:16px;font-family:var(--fd);font-size:19px;letter-spacing:.03em;color:#fff;box-shadow:0 3px 0 var(--ink)}
.lr-sh.good{background:linear-gradient(180deg,#6ff0a4,#17b862)}
.lr-sh.bad{background:linear-gradient(180deg,#ff9a6b,#f0412a)}
.lr-sh .ol{--sw:5px;--sd:2px}
.lr-speech ul.lr-items{padding:2px 4px 6px}
.lr-speech li.lr-item{padding:10px 2px}
.lr-speech .lr-ic{flex-basis:42px;height:42px;font-size:21px}
.lr-speech .lr-item .it{font-size:18px}
.lr-tiles{display:flex;flex-wrap:wrap;gap:14px;margin:4px 0 10px}
.lr-tile{flex:1 1 180px;min-width:0;background:#fff;border:4px solid var(--ink);border-radius:20px;
box-shadow:0 6px 0 var(--ink);padding:10px 14px 12px;border-top-width:10px;border-top-color:var(--tc,var(--ink))}
.lr-tile .tl{font-family:var(--fd);font-size:15px;letter-spacing:.06em;color:#5b5391}
.lr-tile .tv{font-family:var(--fd);font-size:28px;line-height:1.1;color:var(--ink);overflow-wrap:anywhere}
.lr .lr-tile p.ts{margin:2px 0 0;font-weight:800;font-size:13px;color:#4d4575}
.lr-tile.blue{--tc:#2a78d6}.lr-tile.orange{--tc:#eb6834}.lr-tile.up{--tc:var(--green-d)}.lr-tile.down{--tc:var(--red-d)}
.lr-tile.flat{--tc:#6b6394}
@media (max-width:640px){.lr-speech{margin:16px 0 6px}.lr-speech::before{left:calc(50% - 13px);top:-17px;
transform:rotate(135deg)}.lr-h{font-size:25px}}
"""


def _e(x) -> str:
    return html.escape(str(x), quote=True)


@lru_cache(maxsize=1)
def font_css() -> str:
    """@font-face rules with the game's fonts as base64 data (empty if the files are missing)."""
    out = []
    for fam, file, rng, weight in (("Lilita One", "LilitaOne-latin.woff2", LATIN, "400"),
                                   ("Lilita One", "LilitaOne-latinext.woff2", LATIN_EXT, "400"),
                                   ("Nunito", "Nunito-latin.woff2", None, "200 1000")):
        f = FONTS / file
        if not f.is_file():
            continue
        b64 = base64.b64encode(f.read_bytes()).decode("ascii")
        out.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{weight};font-display:swap;"
                   f"src:url(data:font/woff2;base64,{b64}) format('woff2')"
                   + (f";unicode-range:{rng}" if rng else "") + "}")
    return "".join(out)


@lru_cache(maxsize=1)
def style_block() -> str:
    """The <style> block (fonts + game look). Inject once per page run."""
    return "<style>" + font_css() + " ".join(CSS.split()) + "</style>"


def heading_html(text: str) -> str:
    return f'<div class="lr"><div class="lr-h ol">{_e(text)}</div></div>'


def hero_html(title: str, subtitle: str = "", verdict: dict | None = None, tag: str = "RESULTS") -> str:
    """Purple results panel: corner tag, big outlined title, subtitle; with a verdict also the grade badge + text."""
    grade = ""
    vtxt = ""
    if verdict:
        g = _e(verdict.get("grade", ""))
        grade = f'<div class="lr-grade ol g-{g}" aria-label="Grade {g}">{g}</div>'
        vtxt = (f'<div class="lr-verdict"><b>{_e(verdict.get("title", ""))}</b>{_e(verdict.get("text", ""))}</div>')
    sub = f'<p class="sub">{_e(subtitle)}</p>' if subtitle else ""
    return (f'<div class="lr"><section class="lr-hero"><span class="lr-tag">{_e(tag)}</span>{grade}'
            f'<div class="txt"><div class="ttl ol" role="heading" aria-level="1">{_e(title)}</div>{sub}</div>{vtxt}</section></div>')


def lanes(fracs: list[float], gap: float = CHIP_W / WIDTHS[0]) -> list[int]:
    """Greedy lanes like Juli's timeline: a chip goes to the first lane whose last chip is far enough to the left."""
    last: list[float] = []
    out = []
    for x in fracs:
        lane = next((i for i, prev in enumerate(last) if x - prev >= gap), len(last))
        if lane == len(last):
            last.append(x)
        else:
            last[lane] = x
        out.append(lane)
    return out


def _ticks(start: int, end: int) -> list[int]:
    ticks = [start] + [a for a in range((start // 10 + 1) * 10, end, 10) if a - start >= 4 and end - a >= 4] + [end]
    return sorted(set(ticks))


def timeline_html(items: list[dict], start_age: int, end_age: int, title: str = "YOUR TIMELINE",
                  empty: str = "No events yet.", legend: bool = True) -> str:
    """Horizontal age axis with one chip per item ``{age, emoji, title, impact?: up|down|flat|None, note?}``."""
    span = max(end_age - start_age, 1)
    rows = sorted((it for it in items if start_age <= float(it.get("age", start_age)) <= end_age),
                  key=lambda it: float(it.get("age", start_age)))
    fracs = [(float(it["age"]) - start_age) / span for it in rows]
    width, ln = WIDTHS[0], lanes(fracs, CHIP_W / WIDTHS[0])
    for width in WIDTHS:                      # crowded years (many choices early): a wider, scrolling track
        ln = lanes(fracs, CHIP_W / width)
        if max(ln, default=0) < MAX_LANES:
            break
    marks = []
    for it, x, lane in zip(rows, fracs, ln):
        imp = it.get("impact")
        cls = f"lr-{imp}" if imp in ARROW else "lr-none"
        arrow, words = ARROW.get(imp, ("", ""))
        tip = " · ".join(str(v) for v in (it.get("title"), f"age {it['age']}", words, it.get("note")) if v)
        ar = f'<span class="ar" role="img" aria-label="{_e(words)}">{arrow}</span>' if arrow else ""
        marks.append(f'<div class="lr-mark {cls}" role="listitem" style="left:{x * 100:.2f}%;--lane:{lane}">'
                     f'<div class="lr-chip" title="{_e(tip)}"><span class="e">{_e(it.get("emoji") or "📌")}</span>'
                     f'<span class="t">{_e(it.get("title", ""))}</span><span class="a">{_e(it["age"])}</span>{ar}'
                     f'</div></div>')
    ticks = "".join(f'<span style="left:{(a - start_age) / span * 100:.2f}%">'
                    f'{"Today · " + str(a) if a == start_age else a}</span>' for a in _ticks(start_age, end_age))
    n_lanes = max(ln, default=0) + 1
    body = (f'<div class="lr-scroll"><div class="lr-track" style="--lanes:{n_lanes};min-width:{width}px" role="list" '
            f'aria-label="Timeline from age {start_age} to {end_age}"><div class="lr-axis"></div>'
            f'<div class="lr-ticks">{ticks}</div>{"".join(marks)}</div></div>')
    if not rows:
        body = f'<p class="lr-empty">{_e(empty)}</p>' + body
    leg = ""
    if legend and any(it.get("impact") in ARROW for it in rows):
        leg = ('<div class="lr-legend">' + "".join(
            f'<span class="lr-{k}"><i style="color:var(--c)">{a}</i>{_e(w)}</span>' for k, (a, w) in ARROW.items())
            + "</div>")
    return (f'<div class="lr"><section class="lr-card"><div class="lr-band"><span class="ol">{_e(title)}</span></div>'
            f'<div class="lr-tl-body">{body}{leg}</div></section></div>')


def _items(rows: list[dict], kind: str) -> str:
    out = []
    for r in rows:
        better = (f'<p class="lr-better"><span>BETTER</span>{_e(r["better"])}</p>' if r.get("better") else "")
        out.append(f'<li class="lr-item"><div class="lr-ic">{_e(r.get("icon", ""))}</div><div>'
                   f'<div class="it" role="heading" aria-level="3">{_e(r.get("title", ""))}</div><p>{_e(r.get("text", ""))}</p>{better}</div></li>')
    return f'<ul class="lr-items {kind}">{"".join(out)}</ul>'


def aspects_html(positives: list[dict], negatives: list[dict]) -> str:
    """Two chunky cards side by side: what went well (green) and where you can do better (red/orange)."""
    good = (f'<section class="lr-card"><div class="lr-band good"><span class="ol">WHAT WENT WELL</span></div>'
            f'{_items(positives, "good")}</section>')
    bad = (f'<section class="lr-card"><div class="lr-band bad"><span class="ol">WHERE YOU CAN DO BETTER</span></div>'
           f'{_items(negatives, "bad")}</section>')
    return f'<div class="lr"><div class="lr-cols">{good}{bad}</div></div>'


def subheading_html(text: str, sub: str = "") -> str:
    """Section title (white Lilita One with ink outline) plus an optional one-line explanation underneath."""
    tail = f'<p class="lr-hsub">{_e(sub)}</p>' if sub else ""
    return f'<div class="lr"><div class="lr-h ol" role="heading" aria-level="2">{_e(text)}</div>{tail}</div>'


def speech_html(name: str, verdict: dict | None, positives: list[dict], negatives: list[dict],
                extra: str = "") -> str:
    """The twin's message as a game-style speech panel (tail pointing at the 3D character on the left):
    the verdict, "Here's what went well …" (green) and "Where you can do better …" (red, every item with a BETTER
    tip). ``extra`` = one more line at the end (e.g. what the edited path changes)."""
    who = f'<span class="lr-who">{_e((name or "YOUR").upper())}\'S TWIN</span>'
    say = ""
    if verdict:
        say = (f'<p class="lr-say"><b>Grade {_e(verdict.get("grade", ""))} – {_e(verdict.get("title", ""))}</b>'
               f'{_e(verdict.get("text", ""))}</p>')
    good = bad = ""
    if positives:
        good = (f'<div class="lr-sh good" role="heading" aria-level="3"><span aria-hidden="true">▲</span>'
                f'<span class="ol">Here\'s what went well …</span></div>{_items(positives, "good")}')
    if negatives:
        bad = (f'<div class="lr-sh bad" role="heading" aria-level="3"><span aria-hidden="true">▼</span>'
               f'<span class="ol">Where you can do better …</span></div>{_items(negatives, "bad")}')
    tail = f'<p class="lr-say">{_e(extra)}</p>' if extra else ""
    return (f'<div class="lr"><section class="lr-speech" aria-label="Your twin says">{who}{say}{good}{bad}{tail}'
            f'</section></div>')


def tiles_html(tiles: list[dict]) -> str:
    """Row of chunky number tiles ``{label, value, sub?, tone?: blue|orange|up|down|flat}`` (wraps on phones)."""
    out = []
    for t in tiles:
        tone = t.get("tone") if t.get("tone") in ("blue", "orange", "up", "down", "flat") else ""
        sub = f'<p class="ts">{_e(t["sub"])}</p>' if t.get("sub") else ""
        out.append(f'<div class="lr-tile {tone}"><div class="tl">{_e(t.get("label", ""))}</div>'
                   f'<div class="tv">{_e(t.get("value", ""))}</div>{sub}</div>')
    return f'<div class="lr"><div class="lr-tiles">{"".join(out)}</div></div>'
