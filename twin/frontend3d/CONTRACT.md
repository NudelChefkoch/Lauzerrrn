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


## Update: next round (gap year, skip, retire option, adjustable cards)
Binding for Python (`twin/session.py`, `twin/game.py`), the engine and the UI. Category keys unchanged
(`education | career | housing | family | timeoff`), all labels English.

- **Graduation does not start a job.** Bachelor / master / apprenticeship end in "graduated / looking" = state
  `unemployed` without unemployment benefits (no ALV), income 0 (side income ends); `hud.state` = `"graduated · looking"`
  from the station where the degree is finished. A finished degree emits ONLY `{"type": "graduation", "label": "<degree>"}`
  (no extra `job` anim).
- **New card `grad_job`** (cat `career`, 💼, "Job after your degree"): text names the salary of the best degree
  (master CHF 6'300 / bachelor CHF 5'200 / apprenticeship CHF 5'000; own flat +1'000 / +800 / +600 a month). Locked:
  "Finish a degree first" (no degree), "You are studying right now", "You already have a job", "You are retired".
  Taking it → anim `{"type": "job", "label": "First job!"}`. "Entry job" (`job_start`) stays available too.
  Repeatable (`once` = false): a master after a bachelor job ends "graduated / looking" again and offers the master job.
- **Time off = only `gap_year`** (🎒, "Gap year", "12 months off without pay"; `travel`, `sabbatical3`, `sabbatical12`
  removed). Employed → 12 months without pay, then the same job. Graduated / looking (or any other state) → 12 months
  without income, afterwards as before (still looking: `grad_job` stays available). Anim `{"type": "gapyear", "label": "Gap year"}`.
  Not while studying or retired; can be taken again (`once` = false).
- **Retire is a card** `retire` (cat `career`, 🪑, "Retire", "AHV + pension fund: about 60 % of your last salary").
  Locked "From age 60" before 60, "Already retired" afterwards. Effect: income = 60 % of the last salary (at least the AHV
  minimum CHF 1'260) for the rest of life, expenses unchanged; state RETIRED (= `config.OTHER` = 4, the data's "retired"
  group; `config.RETIRED` is an alias), `hud.state` = `"retired"`. Career / education / gap-year cards then say
  "You are retired". Anim `{"type": "retirement", "label": "Retired!"}` mid-game – the game goes on.
  Not chosen by 70 → forced retirement at 70 (same effect, plan label "Retirement", anim `{"type": "retirement",
  "label": "Retirement"}`).
- **Life runs to 85**: `game.life_span(age)` → `(1, K, K)` with `K = min(85 − age, 70)` stations (one station = one year);
  `play.end_age` = `summary.age_end` = 85; `engine.simulate` accepts up to 70 years (`engine.MAX_YEARS`). The end (phase
  `end`, life summary, `world.finale: true`) is at 85; `summary.score` = net worth at 85 in k CHF.
  `boot` gains `end_age: 85`, `retire_from: 60`, `forced_retire_age: 70`; `boot.retire_age` stays 65 (statutory AHV age,
  horizon of the film ride's statements).
- **Adjustable cards** – a card MAY carry `params` (only cards that have values carry the key):
  `"params": {"<name>": {"label", "min", "max", "step", "default", "unit", "value"}}`, `value` = the current chosen value.
  | card | param | label | min | max | step | default |
  |---|---|---|---|---|---|---|
  | `buy_house` | `price` | Price | 400'000 | 2'000'000 | 50'000 | 850'000 |
  | `child` | `cost` | Cost per month | 300 | 3'000 | 100 | 1'100 |
  | `costs` | `delta` | Change per month | −2'000 | 2'000 | 100 | −300 |
  Lock, preview (`median/p5/p95/credit/delta`) and `text` follow the chosen values (house: down payment 20 % + 2 % fees
  of the chosen price at that year's price level, plus one month of costs, vs. liquid money; text shows the price in
  today's CHF). If the purchase would still fail in the played life (path 0: the market moved that month) the card is
  locked "Down payment not enough this year (prices and markets move)" and `choose` is rejected – no house anim for a
  purchase the twin never makes.
- **Child**: CHF 3'000 at birth, then `cost` per month for 216 months (until 18) – `ExpenseChange(months=216)`. At +216
  months anim `{"type": "child_leaves", "label": "Your child moves out"}`. At most 2 children, age 22–50.
- **New card `costs`** (cat `housing`, 🧾, "Adjust monthly costs", repeatable): `ExpenseChange(t, delta, "Monthly costs")`
  from now on. Locked "Pick a change first" (delta 0) or "Costs can't go below CHF 500/month". Note: an uploaded CSV is
  only the PAST net flow per month; future costs come from the status quo (start form) and the decisions in the game.
- **Skip**: `play.skip = [{"years": 5, "label": "+5 years"}, {"years": 10, "label": "+10 years"},
  {"until": "event", "label": "Next event"}]` (entries with more years than are left are omitted).
  After a skip: `world.prev_turn` = turn before the skip, `world.turn` = new turn, `world.skipped` = n stations driven
  (0 for a normal step; present in `play.world` and `end.world`) – the engine drives all stations in one go.
  `world.anims` holds the anims of all skipped years (ids unique), each with `"brief": true` when `skipped >= 2`.
  "Next event" stops at the first station with an animated event (degree, child moves out, forced retirement, …), at most 10 years.
  Anims of a skip also carry `"turn": <station where it happened>` (prev_turn < turn ≤ world.turn): the engine's drive
  pauses there for the short version; without `turn` the short anims play at the end of the drive.
- **`world.life`** gains `kids_home` (children still at home; `kids` stays the number born – each child moves out at 18)
  and `retired` (true from retirement on: grey hair, cane, also when the world is rebuilt). Both are authoritative for
  the engine; older payloads without them still work (the engine then counts `child_leaves` anims).

### JS → Python (new / extended actions, all with `nonce`, deduped)
- `{"action": "card_params", "key": "buy_house", "params": {"price": 600000}, "nonce": n}` – stores the values in the
  session (clamped to min/max, snapped to step), recomputes that card's lock / preview / text, bumps `seq` (also when the
  key is unknown, so the waiting overlay clears).
- `{"action": "choose", "key": "child", "params": {"cost": 1500}, "nonce": n}` – `params` optional; fallback: the stored
  values, then the defaults. The values used are remembered for the card.
- `{"action": "skip", "years": 5, "nonce": n}` (years ≥ 1, clipped to the end of life) or
  `{"action": "skip", "until": "event", "nonce": n}` = n × `choose("stay")` in one step. A rejected skip (game over,
  years < 1) changes nothing but bumps `seq`.


## Update: arrows, status tile, end -> review
Binding for Python (`twin/session.py`, `twin/game.py`, `twin/three_d.py`), the engine and the UI. Supersedes the
card preview chips, the side-panel fan chart, the life summary screen and the film-ride entry described above.

- **No film ride in the game UI.** The start panel has the status-quo form, the example-data loader and LET'S GO only
  (flow: status quo → LET'S GO → intro → play). The Python side (`action: "ride"`, phase `ride`, `twin.daten_update`)
  still works for tests / the analysis; a `ride` payload is shown like `boot` by the client.
- **Decision cards show ONE arrow, no numbers.** Every card with a preview carries `"impact": "up" | "down" | "flat"`
  (`None` when locked), from `game.impact(delta, stay_median)`: `"flat"` only if |delta| < 1 % of |stay median| and
  < CHF 20'000, else the sign of `delta`. The client draws a 40 px circle badge in the band corner – green ▲ "Better for
  your money", red ▼ "Costs you money", grey ● "About the same" – plus the same words under the text. The numbers
  (`delta, median, p5, p95, credit`) stay in the payload for the end (facts, analysis) but are not rendered in the game.
  Lock reasons, sliders (`params`) and the card look are unchanged. `summary.choices[]` gains `impact` too.
- **"Where you stand" tile** replaces the side panel's net-worth fan (canvas + legend; `play.fan` is still sent but not
  drawn). `hud` gains:
  `net_worth_prev` (net worth at the previous stop = `world.prev_turn`, i.e. one station ago or where a skip started;
  `null` at the start), `prev_age` (age at that stop, `null` at the start), `expenses` (planned monthly expenses, month-0
  CHF) and `health`: `"credit"` (consumer credit or a personal loan open – the mortgage does not count), else `"ok"`
  (cash ≥ 3 months of `expenses`) or `"thin"`. The tile shows the net worth today (big), the change since `prev_age`
  with a green ▲ / red ▼ arrow and a badge 🟢 Buffer OK / 🟡 Thin buffer / 🔴 On credit. Goals and the stations strip stay.
  Why: the 60-year fan forecast spoiled the ending, contradicted the no-numbers cards and its median (tens of millions)
  confused players – during the game they need "where am I now", not a forecast.
- **End of the game:** phase `end` → screen **finale** (the island plays the retirement finale; tag "THE FINISH LINE",
  RESULTS ▶▶ / Space skips; when the engine is idle again the client moves on) → **FINANCIAL FACTS** (tiles, percentile
  gauge, "your life vs. just driving on" chart). Buttons: **YOUR LIFE REVIEW ▶** (biggest, sends `{"action":
  "analyse"}`) and PLAY AGAIN. The life summary screen is gone (`end.summary` stays in the payload for the analysis).
  `facts.disclaimer` may stay in the payload but is never rendered.
- **Podium mode** (`three_d.podium(avatar, bubble=None, height=420, key="podium")` → component args
  `{mode: "podium", avatar, bubble, height}`): only the player's 3D character on its podium (engine `showPodium(cfg,
  {wave})` = creator scene + `buildCharacter`, slow idle turn, gentle bob, waves once on load and again whenever
  `bubble` changes; drag rotates), game-style rounded frame with the sunburst background, optional speech bubble with
  `bubble` above the character (HTML overlay, white, ink border, drop shadow), no other UI, frame height = `height`.
  Standalone demo: `index.html?mode=podium`; `index.html` alone is the game demo as before.
