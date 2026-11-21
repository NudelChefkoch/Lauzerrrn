# "YOUR LIFE · YOUR CHOICE" – contract between Python (Streamlit host), the 3D engine and the in-game UI

The whole game runs inside ONE Streamlit custom component (`twin/three_d.py`, mode `"game"`), full-viewport.
Streamlit shows nothing else on the game page. Python is only the simulation backend.

## Files (all in `twin/frontend3d/`, served by Streamlit; also testable with `python3 -m http.server`)
| file | owner | role |
|---|---|---|
| `three.module.js` | vendored | three.js r160, imported as `three` via importmap |
| `fonts/LilitaOne-latin.woff2`, `fonts/LilitaOne-latinext.woff2`, `fonts/Nunito-latin.woff2` | vendored | display font (chunky titles) + UI font (variable weight) |
| `core.js` | shared | THREE re-export, palettes (`SKINS, HAIRC, COLORS`), `OPTIONS`, `CAT_LABEL`, `NICE`, `DEFAULT_CFG`, `M, add, shade, lerp, ease, easeOutBack, sprite, tween, wait, runTasks` |
| `character.js` | 3D | `buildCharacter(cfg, life)`, `addProp`, `removeProp`, `animateCharacter`, `buildCar`, `seat`, `buildPodium` |
| `engine.js` | 3D | renderer + views + life-event animations (API below) |
| `index.html`, `ui.css`, `ui.js`, `main.js` | client | screens, HUD, Streamlit bridge |

## Avatar config (`cfg`)
`{name, gender, skin, hair, hairColor, hat, outfit, color, car}`, values from `core.js` `OPTIONS`:
- gender: frau | mann | divers · skin: hell | rosig | oliv | mittel | braun | dunkel
- hair: kurz | lang | dutt | locken | pferdeschwanz | afro | iro | glatze
- hairColor: schwarz | dunkelbraun | braun | blond | rot | pink | blau | grau
- hat: keiner | cap | beanie | strohhut | partyhut | kopfhoerer · outfit: hoodie | tshirt | hemd | kleid | sport
- color / car: blau | orange | tuerkis | gelb | pink | gruen | violett | rot | weiss | navy

## Engine API (`engine.js`)
- `initEngine(containerEl)` – creates the WebGL canvas filling `containerEl`, starts the render loop. Call once.
- `showCreator(cfg, cat)` – switch to the podium view, character (or car if `cat === 'car'`) on the podium, slowly turning; drag rotates.
- `setCreator(cfg, cat)` – update the podium figure (pop animation).
- `showWorld(worldArgs, {reset})` – switch to the island. First call (or `reset: true`) builds the world; later calls drive the car / queue animations.
  `worldArgs = {avatar, turn, prev_turn, start_age, K, badges: {"<turn>": "emoji"}, life: {suit, kids}, anims: [{id, type, label?, emoji?}], finale}`
  anim types: graduation | job | startup | vacation | house | child | retirement | fate (emoji + label).
  Anim ids are unique; the engine plays each id once. If `prev_turn !== turn` on the FIRST build, it drives from prev_turn.
- `setToastHandler(fn(text, ms))` – engine calls this for event banners ("🎓 Uniabschluss!").
- `setBusyHandler(fn(busy: bool))` – true while the car drives / an animation plays. `isBusy()` returns the current state.

## Python → JS: component args (every Streamlit rerun)
```json
{
  "height": 860,
  "seq": 17,
  "phase": "boot" | "play" | "end",
  "avatar": { cfg },
  "boot": {
    "profiles": [{"id": "P00001", "name": "Alexia", "age": 20, "status_de": "in Ausbildung",
                  "start_capital": 8000.0, "typical_month": -1030.9}],
    "risks": [{"key": "konservativ", "title": "Konservativ", "emoji": "🛡️", "text": "25 % Aktien, 6 Monate Notgroschen"}, ...3]
  },
  "play": {
    "turn": 3, "K": 15, "start_age": 20, "age": 23,
    "hud": {"name": "Alex", "age": 23, "level": 2, "level_title": "Durchstarter/in", "xp_in_level": 130,
            "xp_per_level": 400, "xp_total": 530, "joy": 63, "joy_emoji": "🙂", "net_worth": 3347.0,
            "cash": 3347.0, "portfolio": 0.0, "debt": 0.0, "income": 5304.0, "state_de": "angestellt",
            "achievements_got": 4, "achievements_total": 12},
    "world": { worldArgs },
    "categories": [{"key": "bildung", "label": "Bildung", "emoji": "🎓", "color": "#2a78d6", "open": 2}, ...6],
    "cards": [{"key": "bachelor", "cat": "bildung", "emoji": "🎓", "title": "Bachelor", "text": "...",
               "locked": null, "xp": 100, "joy": 3, "delta": 749054.0, "median": 510409.0, "p5": 389026.0,
               "p95": 680845.0, "credit": 1.0, "rarity": "RARE"}],
    "stay": {"key": "stay", "title": "Weiterfahren", "xp": 10},
    "quests": [{"name": "Notgroschen", "current": 8000.0, "target": 12800.0, "by_age": 25, "progress": 0.62, "done": false}],
    "achievements": [{"key": "grad", "emoji": "🎓", "title": "Abschluss geschafft", "got": true}],
    "new_achievements": [{"emoji": "🐷", "title": "Notgroschen: 3 Monatsausgaben", "xp": 150}],
    "history": [{"age": 20, "emoji": "🎓", "title": "Bachelor"}],
    "fan": {"ages": [20, 21, ...35], "past": [8000, ...] , "p5": [...], "p50": [...], "p95": [...], "now_index": 3}
  },
  "end": {
    "world": { worldArgs with "finale": true },
    "summary": {"name": "Alex", "age_end": 35, "score": 1234, "stars": 4, "level": 5, "level_title": "Legende",
                "joy": 78, "joy_emoji": "🙂", "xp_total": 2100,
                "choices": [{"age": 20, "emoji": "🎓", "title": "Bachelor", "cat_label": "Bildung", "rarity": "RARE", "xp": 100}],
                "achievements": [{"key": "grad", "emoji": "🎓", "title": "Abschluss geschafft", "got": true}]},
    "facts": {"net_worth": 640000.0, "percentile": 63, "p5": 400000.0, "p95": 900000.0, "lazy_median": -320000.0,
              "cash": 20000.0, "portfolio": 500000.0, "house_equity": 120000.0, "debt": 0.0, "max_credit": 28000.0,
              "months_with_credit": 30, "decisions": 9, "best": {"title": "Bachelor", "delta": 749054.0},
              "fan": {"ages": [...], "past": [...], "p5": [...], "p50": [...], "p95": [...], "lazy": [...], "now_index": 15},
              "disclaimer": "Synthetische Daten · keine Prognose · keine Anlageberatung"}
  }
}
```
Only the block matching `phase` is guaranteed (`boot` is always present so the title screen can show the profiles).
Rarity: COMMON (xp ≤ 50) · UNCOMMON (≤ 90) · RARE (≤ 140) · EPIC (≤ 199) · LEGENDARY (≥ 200).

## JS → Python: `setComponentValue(value)` (dataType json)
Every value carries a strictly increasing `nonce` (use `Date.now()`); Python ignores a nonce it has already handled.
- `{"action": "start", "nonce": n, "avatar": {cfg}, "pid": "P00001", "risk": "ausgewogen"}`
- `{"action": "choose", "nonce": n, "key": "bachelor"}` (or `"stay"`)
- `{"action": "restart", "nonce": n}` → back to `phase: "boot"`
- `{"action": "analyse", "nonce": n}` → Python switches to the analysis page

## Client screens (all inside the component, nothing in Streamlit)
1. **Loading** – "YOUR LIFE · YOUR CHOICE" in Lilita One with thick outline + drop shadow, progress bar, rotating tips; ~2–3 s and until fonts + three.js are ready.
2. **Title** – big title, "SPIELEN" + "ANALYSE" buttons, figure turning on the podium behind.
3. **Creator** – figure on the podium, big ◀ ▶ beside it, category chips, value plate, name field, 🎲; right panel "START-LEBEN" (profile cards + 3 risk cards); "LOSFAHREN".
4. **Play** – island full-screen; HUD (name/age, level + XP bar, 💰, joy, 🏆); bottom: 6 category cards (blue header with title, big emoji body, count of open options) – the SELECTED one is shown by recolouring its background/header (no check mark); above it the decision cards of that category (rarity tag, preview chips, 🔒 reason when locked), "WEITERFAHREN" button; side panel with quests, achievements and a small fan chart (canvas). Buttons disabled while `busy`. New achievements → celebration popup.
5. **Life summary** (end) – "RESULTS" corner tag, "LIFE SUMMARY" heading, dark rows per choice with rarity tag + XP reward tile, score/stars/joy; "WEITER".
6. **Financial facts** – big stat tiles, percentile gauge, fan chart with "dein Leben" vs "nur weitergefahren", disclaimer; "NOCHMAL SPIELEN" + "ANALYSE".
