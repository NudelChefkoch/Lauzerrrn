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
  `worldArgs = {avatar, turn, prev_turn, start_age, K, badges: {"<turn>": "emoji"}, life: {suit, kids, partner}, anims: [{id, type, label?, emoji?}], finale, intro}`
  anim types: graduation | job | startup | vacation | house | child | wedding | retirement | fate (emoji + label).
  `wedding`: a chapel pops up (on the side of the road away from the camera), guests line the aisle, the avatar changes
  into a wedding dress / suit, the partner steps out of the chapel, rings + hearts + confetti + bell, then both drive on.
  `life.partner` keeps the partner seated next to the driver from then on.
  `intro: true` (fresh game, built once): fly-over of the island → course preview along the road → swoop behind the car → countdown.
  Anim ids are unique; the engine plays each id once. If `prev_turn !== turn` on the FIRST build, it drives from prev_turn.
- `setToastHandler(fn(text, ms))` – engine calls this for event banners ("🎓 Uniabschluss!").
- `setBusyHandler(fn(busy: bool))` – true while the car drives / an animation plays. `isBusy()` returns the current state.
- `setIntroHandler(fn(step, data))` – intro steps `title` ({from, to, stations}) → `howto` → `countdown` → `end` ({skipped}).
- `skipIntro()` – jumps the running intro to its end (SKIP button, Space / Enter / Esc).

## Python → JS: component args (every Streamlit rerun)
```json
{
  "height": 860,
  "seq": 17,
  "phase": "boot" | "play" | "end",
  "avatar": { cfg },
  "boot": {
    "profiles": [{"id": "P00001", "name": "Alexia", "age": 20, "status": "in education",
                  "start_capital": 8000.0, "typical_month": -1030.9, "ist": { ist }}],
    "statuses": [{"key": "student", "label": "in education"}, {"key": "employed", "label": "employed"}, ...],
    "ist": { ist }          // default pre-fill of the Ist-Zustand form (= first example profile)
  },
  "play": {
    "turn": 3, "K": 15, "start_age": 20, "age": 23,
    "focus_cat": "money" | null,   // set once the investment style is due (station 2+) and not chosen yet
    "hint": "📊 Time to pick your investment style – see Money" | null,
    "hud": {"name": "Alex", "age": 23, "style": "not chosen yet", "joy": 63, "joy_emoji": "🙂", "net_worth": 3347.0,
            "cash": 3347.0, "portfolio": 0.0, "debt": 0.0, "income": 5304.0, "state": "employed",
            "achievements_got": 4, "achievements_total": 12},
    "world": { worldArgs },
    "categories": [{"key": "education", "label": "Education", "emoji": "🎓", "color": "#2a78d6", "open": 2}, ...6],
    "cards": [{"key": "bachelor", "cat": "education", "emoji": "🎓", "title": "Bachelor", "text": "...",
               "locked": null, "joy": 3, "delta": 749054.0, "median": 510409.0, "p5": 389026.0,
               "p95": 680845.0, "credit": 1.0}],
    "stay": {"key": "stay", "title": "Drive on"},
    "quests": [{"name": "Emergency fund", "current": 8000.0, "target": 12800.0, "by_age": 25, "progress": 0.62, "done": false}],
    "achievements": [{"key": "grad", "emoji": "🎓", "title": "Graduated", "got": true}],
    "new_achievements": [{"emoji": "🐷", "title": "Emergency fund: 3 months of expenses"}],
    "history": [{"age": 20, "emoji": "🎓", "title": "Bachelor"}],
    "fan": {"ages": [20, 21, ...35], "past": [8000, ...] , "p5": [...], "p50": [...], "p95": [...], "now_index": 3}
  },
  "end": {
    "world": { worldArgs with "finale": true },
    "summary": {"name": "Alex", "age_end": 35, "score": 1234, "stars": 4, "joy": 78, "joy_emoji": "🙂",
                "style": "Invest balanced",
                "choices": [{"age": 20, "emoji": "🎓", "title": "Bachelor", "cat_label": "Education", "delta": 749054.0}],
                "achievements": [{"key": "grad", "emoji": "🎓", "title": "Graduated", "got": true}]},
    "facts": {"net_worth": 640000.0, "percentile": 63, "p5": 400000.0, "p95": 900000.0, "lazy_median": -320000.0,
              "cash": 20000.0, "portfolio": 500000.0, "house_equity": 120000.0, "debt": 0.0, "max_credit": 28000.0,
              "months_with_credit": 30, "decisions": 9, "best": {"title": "Bachelor", "delta": 749054.0},
              "fan": {"ages": [...], "past": [...], "p5": [...], "p50": [...], "p95": [...], "lazy": [...], "now_index": 15},
              "disclaimer": "Synthetic data · not a forecast · not investment advice"}
  }
}
```
Only the block matching `phase` is guaranteed (`boot` is always present so the title screen can show the profiles).
All player-facing text is English. No XP, levels or rarities (removed). `ist` = Ist-Zustand form values, all monthly CHF except age:
`{"basis": "P00001" | null, "age": 24, "status": "employed", "income": 5207, "expenses": 2648, "rent": 1404,
"cash": 25000, "portfolio": 13540, "debt": 0}`. Unchanged example values → the calibrated profile is used; anything
else becomes an own person (`twin/ist_zustand.py`).
The investment style is NOT asked at the start: until the player picks one of the Money cards `style_konservativ |
style_ausgewogen | style_risky` (category `money`, unlocked from station 2) nothing new is invested.

## JS → Python: `setComponentValue(value)` (dataType json)
Every value carries a strictly increasing `nonce` (use `Date.now()`); Python ignores a nonce it has already handled.
- `{"action": "start", "nonce": n, "avatar": {cfg}, "ist": { ist }}` (`"pid"` alone still works: unchanged example)
- `{"action": "choose", "nonce": n, "key": "bachelor"}` (or `"stay"`)
- `{"action": "restart", "nonce": n}` → back to `phase: "boot"`
- `{"action": "analyse", "nonce": n}` → Python switches to the analysis page

## Client screens (all inside the component, nothing in Streamlit)
1. **Loading** – "YOUR LIFE · YOUR CHOICE" in Lilita One with thick outline + drop shadow, progress bar, rotating tips; ~2–3 s and until fonts + three.js are ready.
2. **Title** – big title, "SPIELEN" + "ANALYSE" buttons, figure turning on the podium behind.
3. **Creator** – figure on the podium, big ◀ ▶ beside it, category chips, value plate, name field, 🎲; right panel "YOUR START" (example chips that pre-fill + Ist-Zustand form: age, situation, income, expenses, rent, cash, investments, debt); "LET'S GO".
4. **Play** – starts with the intro on a fresh game (banner "<NAME>'S LIFE · AGE a → b", HOW TO PLAY card, READY? 3-2-1-GO!, SKIP button), HUD hidden meanwhile; then island full-screen; HUD (name/age, 📊 investment style, 💰, joy, 🏆); on `focus_cat` the tray jumps once to that category and shows `hint`; bottom: 6 category cards (blue header with title, big emoji body, count of open options) – the SELECTED one is shown by recolouring its background/header (no check mark); above it the decision cards of that category (category colour, preview chips, 🔒 reason when locked), "WEITERFAHREN" button; side panel with quests, achievements and a small fan chart (canvas). Buttons disabled while `busy`. New achievements → celebration popup.
5. **Life summary** (end) – "RESULTS" corner tag, "LIFE SUMMARY" heading, dark rows per choice with its 💰 effect tile, score/stars/joy/Anlagestil; "WEITER".
6. **Financial facts** – big stat tiles, percentile gauge, fan chart with "dein Leben" vs "nur weitergefahren", disclaimer; "NOCHMAL SPIELEN" + "ANALYSE".


## Update: status quo, life span to 65, film ride (no achievements, no joy)
- **Boot**: `boot = {example: {id, name, age, status, ist}, statuses: [...], retire_age: 65}` – the player enters their own
  status quo; ONE example data set can pre-fill the form. Optional one-shot `error` (top level) for a client toast.
- **Life span**: from the entered age to retirement at 65. `play.step` = years per station (e.g. 3), `play.K` stations,
  `play.end_age` = 65, `world.labels` = the age at every station (last = 65). Ages in `hud`, `history`, `fan` follow it.
- **Removed**: achievements (`achievements`, `new_achievements`, popup), joy (`hud.joy`, card `joy`). Summary now has
  `score` (net worth at 65 in k CHF), `stars` (from the percentile), `percentile`, `decisions`, `style`, `choices`.
- **Career** offers only Entry job, Job change and Part-time 80 %.
- **Film ride** (phase `ride`): `{"action": "ride", "ist": {...}, "avatar": {...}, "csv": "<text>" | null}` – null = generated
  sample months. Python runs `twin.daten_update.aktualisiere_aus_daten` and answers with
  `ride = {world: {..., K, labels: ["Today", "Jan 27", ...], ride: true, ride_tags: [{text, good, note}]}, stations: [{label,
  short, flow, balance, note}], statements: [...], before, after, typical_before, typical_after, source, months, name}`.
  The engine drives station by station with a follow camera (`setRideHandler(fn(step, data))`: `start` → `station {i}` → `end`;
  `skipIntro()` also skips the ride). `{"action": "ride_play"}` starts a normal game from the updated status quo.
- **Map**: snowy mountains across the lake, sailboats, clouds, flowers/bushes/rocks, curbs, START / RETIREMENT signs,
  a UBS branch near the start. **Women** wear an A-line dress like the restroom pictogram (`buildDressed`).


## Update: one-year stations, no Money tab, example data ride, tips in the analysis
- **Stations**: one per year from the entered age to 65 (`play.step` = 1, `play.K` = 65 − age). Only the film ride runs
  month by month (quarters only beyond 36 months).
- **Categories**: education, career, housing, family, timeoff (no `money`). Housing = `buy_house` (UBS mortgage) and
  `flat` (rent a luxury flat). No investment cards, no `focus_cat`/`hint`, no `hud.style`/`summary.style`: the game uses
  the balanced default; investing is compared on the analysis page.
- **Film ride**: `{"action": "ride", "example": true}` rides through the example data set's recorded months
  (challenge data, 24 stations); with `csv` it rides through the player's own months.
- **Analysis** (`ui/analyse.py`): "🙋 Your data" (the game's status quo, updated by the film ride) comes first;
  tab "💡 Tips & investing" (`twin/tipps.py`): rule-based tips + cash / cautious / balanced / bold compared.
- **Engine**: no countdown in the intro; buildings take free spots (`spot()` avoids earlier buildings – fixes the office of
  the first job landing inside the university); house purchase = UBS branch + mortgage, then the house lands.
