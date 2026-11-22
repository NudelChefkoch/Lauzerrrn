"""Original avatar kit: chunky, rounded, softly shaded cartoon figures and their car, as SVG.

Every part is a parameter, so the same code draws the character creator, the gallery
and the little figure that drives along the board.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, replace

SKIN = {"hell": "#f6d3b8", "rosig": "#f2c2a2", "oliv": "#d9a77c", "mittel": "#c68a5c",
        "braun": "#9a6340", "dunkel": "#6b4129"}
HAIR_COLORS = {"schwarz": "#2b2523", "dunkelbraun": "#5a3826", "braun": "#8a5a36", "blond": "#e5bd62",
               "rot": "#c4502b", "pink": "#ef7fb0", "blau": "#4c7be0", "grau": "#b9b6b0"}
HAIR_STYLES = ["kurz", "seitenscheitel", "undercut", "locken", "lang", "dutt", "pferdeschwanz", "afro", "glatze"]
OUTFITS = ["hoodie", "tshirt", "hemd", "jacke"]
GLASSES = ["keine", "rund", "eckig", "sonnenbrille"]
HATS = ["keine", "beanie", "cap", "kopfhoerer"]
COLORS = {"blau": "#2a78d6", "orange": "#eb6834", "tuerkis": "#1baf7a", "gelb": "#eda100",
          "pink": "#e87ba4", "gruen": "#2f9e44", "violett": "#6250d6", "rot": "#e34948",
          "weiss": "#f4f2ee", "navy": "#24365c", "oliv": "#7b8a3a", "mint": "#7fd6c2"}


@dataclass(frozen=True)
class Avatar:
    name: str = "Alex"
    skin: str = "rosig"
    hair: str = "kurz"
    hair_color: str = "braun"
    outfit: str = "hoodie"
    outfit_color: str = "blau"
    glasses: str = "keine"
    hat: str = "keine"
    hat_color: str = "orange"
    car_color: str = "rot"
    tie: bool = False


# ---------------------------------------------------------------- colour helpers
def _mix(hex_: str, other: str, f: float) -> str:
    a = [int(hex_[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def light(c: str, f: float = 0.35) -> str:
    return _mix(c, "#ffffff", f)


def dark(c: str, f: float = 0.25) -> str:
    return _mix(c, "#000000", f)


def _grad(gid: str, base: str) -> str:
    return (f'<radialGradient id="{gid}" cx="38%" cy="30%" r="75%">'
            f'<stop offset="0" stop-color="{light(base, .45)}"/><stop offset=".55" stop-color="{base}"/>'
            f'<stop offset="1" stop-color="{dark(base, .22)}"/></radialGradient>')


# ---------------------------------------------------------------- parts
def _hair_back(a: Avatar, u: str) -> str:
    f = f"url(#{u}hair)"
    return {
        # two strands left and right of the face (one closed shape under the chin reads as a beard)
        "lang": (f'<path d="M38 92 C26 150 34 188 70 190 L80 186 C60 168 50 140 52 100 Z" fill="{f}"/>'
                 f'<path d="M162 92 C174 150 166 188 130 190 L120 186 C140 168 150 140 148 100 Z" fill="{f}"/>'),
        "afro": f'<circle cx="100" cy="82" r="74" fill="{f}"/>',
        "pferdeschwanz": f'<ellipse cx="166" cy="118" rx="18" ry="34" transform="rotate(-18 166 118)" fill="{f}"/>',
        "dutt": f'<circle cx="100" cy="30" r="22" fill="{f}"/>',
        "locken": "".join(f'<circle cx="{x}" cy="{y}" r="16" fill="{f}"/>' for x, y in
                          [(44, 108), (156, 108), (40, 86), (160, 86)]),
    }.get(a.hair, "")


def _hair_front(a: Avatar, u: str) -> str:
    f = f"url(#{u}hair)"
    cap = f'<path d="M41 98 C34 40 166 40 159 98 C150 70 124 60 100 64 C76 60 50 70 41 98 Z" fill="{f}"/>'
    return {
        "kurz": cap,
        "seitenscheitel": f'<path d="M41 100 C30 36 170 34 159 96 C146 66 110 56 70 74 C58 80 48 88 41 100 Z" fill="{f}"/>'
                          f'<path d="M70 74 C96 52 140 56 156 80" stroke="{dark(HAIR_COLORS[a.hair_color], .2)}" stroke-width="3" fill="none" opacity=".5"/>',
        "undercut": f'<path d="M48 78 C52 38 150 34 154 76 C150 66 126 58 100 60 C74 58 54 66 48 78 Z" fill="{f}"/>'
                    f'<path d="M44 96 C42 84 46 76 50 74 L50 92 Z M156 96 C158 84 154 76 150 74 L150 92 Z" fill="{f}" opacity=".45"/>',
        "locken": "".join(f'<circle cx="{x}" cy="{y}" r="17" fill="{f}"/>' for x, y in
                          [(52, 70), (74, 50), (100, 42), (126, 50), (148, 70), (64, 62), (136, 62), (88, 48), (112, 48)]),
        "lang": cap,
        "dutt": cap,
        "pferdeschwanz": cap,
        "afro": f'<path d="M40 96 C30 30 170 30 160 96 C150 64 50 64 40 96 Z" fill="{f}"/>',
        "glatze": '<ellipse cx="80" cy="58" rx="16" ry="8" fill="#fff" opacity=".35"/>',
    }[a.hair]


def _face(a: Avatar) -> str:
    eyes = ('<ellipse cx="80" cy="104" rx="6" ry="8" fill="#2b2523"/><ellipse cx="120" cy="104" rx="6" ry="8" fill="#2b2523"/>'
            '<circle cx="82" cy="101" r="2.2" fill="#fff"/><circle cx="122" cy="101" r="2.2" fill="#fff"/>')
    brows = (f'<path d="M71 90 Q80 85 89 89" stroke="{dark(HAIR_COLORS[a.hair_color], .1)}" stroke-width="3.5" fill="none" stroke-linecap="round"/>'
             f'<path d="M111 89 Q120 85 129 90" stroke="{dark(HAIR_COLORS[a.hair_color], .1)}" stroke-width="3.5" fill="none" stroke-linecap="round"/>')
    cheeks = '<ellipse cx="68" cy="120" rx="9" ry="5.5" fill="#ff8a8a" opacity=".35"/><ellipse cx="132" cy="120" rx="9" ry="5.5" fill="#ff8a8a" opacity=".35"/>'
    mouth = '<path d="M88 124 Q100 136 112 124" stroke="#7a3b2e" stroke-width="4" fill="none" stroke-linecap="round"/>'
    g = {
        "keine": "",
        "rund": '<g fill="none" stroke="#2b2523" stroke-width="3.5"><circle cx="80" cy="104" r="14"/><circle cx="120" cy="104" r="14"/><path d="M94 104 L106 104"/></g>',
        "eckig": '<g fill="none" stroke="#2b2523" stroke-width="3.5"><rect x="64" y="93" width="31" height="22" rx="5"/><rect x="105" y="93" width="31" height="22" rx="5"/><path d="M95 103 L105 103"/></g>',
        "sonnenbrille": '<g><rect x="63" y="92" width="33" height="22" rx="9" fill="#1d1d24"/><rect x="104" y="92" width="33" height="22" rx="9" fill="#1d1d24"/>'
                        '<path d="M96 100 L104 100" stroke="#1d1d24" stroke-width="4"/><path d="M69 97 L78 97" stroke="#fff" stroke-width="3" opacity=".5" stroke-linecap="round"/></g>',
    }[a.glasses]
    return (brows if a.glasses != "sonnenbrille" else "") + (eyes if a.glasses != "sonnenbrille" else "") + cheeks + mouth + g


def _hat(a: Avatar, u: str) -> str:
    c = COLORS[a.hat_color]
    f = f"url(#{u}hat)"
    return {
        "keine": "",
        "beanie": f'<path d="M40 86 C38 26 162 26 160 86 Z" fill="{f}"/><rect x="36" y="76" width="128" height="20" rx="10" fill="{dark(c, .12)}"/>'
                  f'<circle cx="100" cy="26" r="13" fill="{light(c, .4)}"/>'
                  + "".join(f'<path d="M{x} 78 L{x} 94" stroke="{dark(c, .3)}" stroke-width="2" opacity=".4"/>' for x in range(48, 160, 12)),
        "cap": f'<path d="M42 84 C40 30 160 30 158 84 Z" fill="{f}"/><path d="M96 82 C120 74 168 76 182 90 C160 92 120 92 96 88 Z" fill="{dark(c, .15)}"/>'
               f'<circle cx="100" cy="36" r="5" fill="{dark(c, .2)}"/>',
        "kopfhoerer": f'<path d="M36 104 C30 24 170 24 164 104" stroke="{dark(c, .1)}" stroke-width="9" fill="none" stroke-linecap="round"/>'
                      f'<rect x="24" y="92" width="22" height="36" rx="10" fill="{f}"/><rect x="154" y="92" width="22" height="36" rx="10" fill="{f}"/>',
    }[a.hat]


def _body(a: Avatar, u: str) -> str:
    c = COLORS[a.outfit_color]
    f = f"url(#{u}cloth)"
    skin = SKIN[a.skin]
    base = (f'<path d="M52 228 C50 186 62 160 100 158 C138 160 150 186 148 228 Z" fill="{f}"/>'
            f'<ellipse cx="50" cy="200" rx="13" ry="22" fill="{f}"/><ellipse cx="150" cy="200" rx="13" ry="22" fill="{f}"/>'
            f'<circle cx="50" cy="222" r="9" fill="{skin}"/><circle cx="150" cy="222" r="9" fill="{skin}"/>')
    extra = {
        "hoodie": f'<path d="M70 162 C78 180 122 180 130 162" stroke="{dark(c, .2)}" stroke-width="6" fill="none"/>'
                  f'<path d="M92 176 L90 198 M108 176 L110 198" stroke="{light(c, .6)}" stroke-width="3" stroke-linecap="round"/>'
                  f'<rect x="76" y="204" width="48" height="16" rx="6" fill="{dark(c, .12)}"/>',
        "tshirt": f'<path d="M84 160 Q100 172 116 160" stroke="{dark(c, .25)}" stroke-width="4" fill="none"/>',
        "hemd": f'<path d="M84 160 L100 178 L116 160 L110 156 L100 166 L90 156 Z" fill="#fff"/>'
                + (f'<path d="M100 176 L94 186 L100 214 L106 186 Z" fill="{COLORS["navy"]}"/>' if a.tie else
                   f'<circle cx="100" cy="190" r="2.5" fill="{dark(c, .3)}"/><circle cx="100" cy="204" r="2.5" fill="{dark(c, .3)}"/>'),
        "jacke": f'<path d="M86 160 L100 228 L114 160 Z" fill="{light("#ffffff", 0)}" opacity=".9"/>'
                 f'<path d="M86 160 L98 200 M114 160 L102 200" stroke="{dark(c, .3)}" stroke-width="3" fill="none"/>',
    }[a.outfit]
    return base + extra


def _defs(a: Avatar, u: str) -> str:
    return ("<defs>" + _grad(f"{u}skin", SKIN[a.skin]) + _grad(f"{u}hair", HAIR_COLORS[a.hair_color])
            + _grad(f"{u}cloth", COLORS[a.outfit_color]) + _grad(f"{u}hat", COLORS[a.hat_color])
            + _grad(f"{u}car", COLORS[a.car_color]) + "</defs>")


def head(a: Avatar, u: str) -> str:
    """Head group in the 200x240 avatar coordinate system."""
    skin = f"url(#{u}skin)"
    return (_hair_back(a, u)
            + f'<circle cx="43" cy="108" r="11" fill="{SKIN[a.skin]}"/><circle cx="157" cy="108" r="11" fill="{SKIN[a.skin]}"/>'
            + f'<circle cx="100" cy="100" r="60" fill="{skin}"/>'
            + _hair_front(a, u) + _face(a) + _hat(a, u))


def avatar_svg(a: Avatar, size: int = 200, uid: str = "a") -> str:
    u = f"{uid}_"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 240" width="{size}" height="{size * 1.2:.0f}" '
            f'role="img" aria-label="Avatar {html.escape(a.name)}">' + _defs(a, u)
            + '<ellipse cx="100" cy="232" rx="58" ry="7" fill="#000" opacity=".12"/>'
            + _body(a, u) + head(a, u) + "</svg>")


def car_group(a: Avatar, u: str) -> str:
    """Car (side view, facing right) with the avatar's head in the window; 220x150 box, wheels at y~128."""
    c = COLORS[a.car_color]
    f = f"url(#{u}car)"
    return (f'<ellipse cx="110" cy="142" rx="92" ry="7" fill="#000" opacity=".15"/>'
            f'<path d="M58 70 C66 36 136 34 150 66 L160 72 Z" fill="{light(c, .55)}" opacity=".9"/>'
            f'<g transform="translate(70 4) scale(.42)">{head(a, u)}</g>'
            f'<path d="M48 76 C62 34 140 30 156 70" stroke="{dark(c, .1)}" stroke-width="7" fill="none" stroke-linecap="round"/>'
            f'<path d="M14 118 C10 92 24 78 50 74 L172 72 C198 74 212 90 208 118 C208 126 202 130 194 130 L26 130 C18 130 14 126 14 118 Z" fill="{f}"/>'
            f'<rect x="196" y="92" width="12" height="10" rx="4" fill="#ffe7a3"/><rect x="12" y="94" width="10" height="9" rx="4" fill="#ff8f8f"/>'
            f'<path d="M30 100 L190 100" stroke="{light(c, .35)}" stroke-width="3" opacity=".6"/>'
            + "".join(f'<circle cx="{x}" cy="128" r="20" fill="#2b2b30"/><circle cx="{x}" cy="128" r="9" fill="#d9d9de"/>'
                      for x in (56, 166)))


def car_svg(a: Avatar, size: int = 220, uid: str = "c") -> str:
    u = f"{uid}_"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 152" width="{size}" height="{size * 152 / 220:.0f}" '
            f'role="img" aria-label="Auto von {html.escape(a.name)}">' + _defs(a, u) + car_group(a, u) + "</svg>")


# ---------------------------------------------------------------- 8 proposals
PRESET_AVATARS: list[tuple[Avatar, str]] = [
    (Avatar("Lea", "hell", "lang", "braun", "hoodie", "violett", "rund", "kopfhoerer", "mint", "tuerkis"),
     "Die Studentin: Uni, Nebenjob, knappes Budget"),
    (Avatar("Noah", "mittel", "kurz", "schwarz", "tshirt", "orange", "keine", "cap", "blau", "blau"),
     "Der Lehrling: früh eigenes Geld, erste Versicherungen"),
    (Avatar("Amina", "dunkel", "dutt", "schwarz", "jacke", "tuerkis", "eckig", "keine", "gelb", "gelb"),
     "Die Gründerin: hohes Risiko, hohe Schwankung"),
    (Avatar("Luca", "hell", "seitenscheitel", "blond", "hemd", "weiss", "keine", "keine", "navy", "navy", True),
     "Der Pendler: sicherer Job, 13. Monatslohn"),
    (Avatar("Mia", "rosig", "locken", "rot", "tshirt", "gelb", "keine", "beanie", "mint", "pink"),
     "Die Kreative: Freelance, unregelmässiges Einkommen"),
    (Avatar("Jonas", "braun", "undercut", "dunkelbraun", "hoodie", "rot", "keine", "keine", "orange", "orange"),
     "Der Sportler: Teilzeit plus Training, sparsam"),
    (Avatar("Sofia", "oliv", "pferdeschwanz", "braun", "jacke", "oliv", "sonnenbrille", "keine", "pink", "gruen"),
     "Die Weltenbummlerin: Gap Year, dann Berufseinstieg"),
    (Avatar("Elias", "dunkel", "afro", "schwarz", "hoodie", "gruen", "keine", "kopfhoerer", "violett", "violett"),
     "Der Gamer: Tech-Job, investiert gern risky"),
]


def gallery_html(items: list[tuple[Avatar, str]] = PRESET_AVATARS) -> str:
    cards = "".join(
        f'<figure class="card"><div class="pic">{avatar_svg(a, 150, f"g{i}")}</div>'
        f'<div class="car">{car_svg(a, 150, f"k{i}")}</div>'
        f'<figcaption><b>{html.escape(a.name)}</b><span>{desc}</span>'
        f'<small>{a.hair} · {a.hair_color} · {a.outfit} {a.outfit_color} · Brille {a.glasses} · Hut {a.hat}</small></figcaption></figure>'
        for i, (a, desc) in enumerate(items))
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Avatar-Vorschläge</title><style>
:root{{--bg:#f6f4ef;--card:#fffdf8;--ink:#1f1d1a;--muted:#6b675f;--line:#e6e1d6}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#16161a;--card:#202026;--ink:#f0efec;--muted:#b4b1a8;--line:#33333b}}}}
:root[data-theme="dark"]{{--bg:#16161a;--card:#202026;--ink:#f0efec;--muted:#b4b1a8;--line:#33333b}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,-apple-system,sans-serif;padding:24px 16px}}
h1{{font-size:24px;margin:0 0 4px}} p.lead{{color:var(--muted);margin:0 0 20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;max-width:1100px}}
.card{{margin:0;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px;display:flex;flex-direction:column;align-items:center;gap:6px}}
.pic{{background:radial-gradient(circle at 50% 40%,#ffffff22,transparent 70%);border-radius:14px}}
figcaption{{display:flex;flex-direction:column;gap:2px;text-align:center}} figcaption span{{color:var(--muted)}}
figcaption small{{color:var(--muted);font-size:12px}}
svg{{max-width:100%;height:auto}}
</style></head><body><h1>Avatar-Vorschläge</h1>
<p class="lead">8 Startfiguren aus dem Baukasten. Alles ist frei kombinierbar: 6 Hauttöne, 9 Frisuren, 8 Haarfarben, 4 Outfits, 4 Brillen, 4 Kopfbedeckungen, 12 Farben.</p>
<div class="grid">{cards}</div></body></html>"""


def random_avatar(rng, name: str = "Alex") -> Avatar:
    pick = lambda xs: xs[int(rng.integers(len(xs)))]
    return Avatar(name, pick(list(SKIN)), pick(HAIR_STYLES), pick(list(HAIR_COLORS)), pick(OUTFITS),
                  pick(list(COLORS)), pick(GLASSES), pick(HATS), pick(list(COLORS)), pick(list(COLORS)))


__all__ = ["Avatar", "avatar_svg", "car_svg", "car_group", "head", "gallery_html", "PRESET_AVATARS",
           "random_avatar", "SKIN", "HAIR_COLORS", "HAIR_STYLES", "OUTFITS", "GLASSES", "HATS", "COLORS", "replace"]
