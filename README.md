# Lauzerrrn
Repo für Falsch und gefälschtes Geld in Lauzern

## Financial Twin engine (`twin/`)

Regime-switching cash-flow SDE + Merton jump-diffusion portfolio + Monte Carlo, calibrated per person from the challenge data.

Quick start (creates `venv/`, installs missing packages, frees the port, opens the browser):

```bash
./start.sh          # or ./start.sh 8600 for another port
```

With uv:

```bash
uv sync
uv run twin P00001 master --years 10 --market standard --strategy ausgewogen --job-loss 0.025
uv run pytest -q
uv run streamlit run app.py   # http://localhost:8501  (Spiel + Analyse)
```

The challenge data is **not** in this repo. By default it is read from `../ai-financial-twin-lauzhack-2026/Data`; override with `TWIN_DATA_DIR`.

- `twin/config.py`: all assumptions with defaults and presets (market, strategy, macro, shortfall rule, shocks, Swiss rules)
- `twin/calibration.py`: per-person mean and noise, seasonality and month-specific noise per status group
- `twin/scenarios.py`: life events (study, job, job change, unemployment, self-employment, house purchase, one-off) and presets
- `twin/engine.py`: monthly simulation, shortfall rule (sell, then cut spending, then credit), metrics, accounting identity check
- `twin/analysis.py`: tornado sensitivity with common random numbers
- `app.py`: Streamlit UI (profile, life plan editor, fan chart, sensitivity, assumptions)
- `ui/spiel.py`: game mode "Lebensweg": avatar creator, animated road board, yearly decision cards with twin previews, fate cards
- `ui/analyse.py`: analysis dashboard ("Your twin" chat with the player's avatar, editable plan timeline, life chart,
  tips; the expected-net-worth chart is always the last element of the page)
- `twin/lifechart/`: offline Streamlit custom component (plain HTML/JS, no build step): net worth over age with p5–p95
  band, a comparison life path ("two life paths"), event markers and a per-month hover readout
- `twin/analysis_chat.py`: the twin's chat. Our model computes every number (house at age X for price Y, strategy
  comparison, pillar 3a, job loss / crash, tornado, tips); a local open-source LLM via Ollama only picks the tool.
  Tool `edit_plan`: tell the twin what should happen ("I buy a house at 35 for 800k", "add a child at 30", "move the
  house to 40", "remove the gap year", "Ich gehe mit 62 in Rente") – it adds / moves / removes that life event on your
  plan, says what it does to your net worth at the end (same seed) and returns `plan_edit` `[{op, key, age, params}]`,
  which the page applies (the chat never changes state itself); the event is then draggable on the timeline. The LLM
  only routes and parses (JSON schema: op, key, age, price, amount); the offline parser (English + German, 800k /
  800'000 / 1.2M, "at 35" / "mit 35") is the fallback. Invalid requests (age outside the plan, unknown event) are
  answered, not applied.
  Env: `TWIN_OLLAMA_URL` (default `http://127.0.0.1:11434`), `TWIN_OLLAMA_MODEL` (default `qwen3:4b`),
  `TWIN_OLLAMA_TIMEOUT` (default 8 s), `TWIN_CHAT_PHRASE=1` (optional rewording). Without Ollama a keyword router
  answers (English/German questions), so the demo never hangs. Answers end with "Not investment advice."
- `twin/avatar.py`, `twin/game.py`: avatar kit (SVG) and game logic
- `twin/ist_zustand.py`: the game starts by asking the current state (Ist-Zustand); example profiles only pre-fill the form
- `twin/daten_update.py`: `aktualisiere_aus_daten(person, csv)` reads later monthly data, recalibrates mu/sigma and the
  current balances, and recomputes the twin's statements (old → new). Not wired into the UI yet
  (`GameSession.aktualisiere_mit_daten` is the hook)

### YOUR LIFE · YOUR CHOICE (game)
`uv run streamlit run app.py` opens straight into the game (full screen, everything in-game). Streamlit is only the
simulation backend: `twin/session.py` (GameSession) produces the payload, `twin/frontend3d/` is the client
(three.js bundled locally, fonts Lilita One + Nunito under OFL). Contract: `twin/frontend3d/CONTRACT.md`.
The analysis dashboard is reachable from the title screen ("ANALYSE").
The game starts with YOUR status quo (one example data set can pre-fill the form) and runs year by year to age 85
(at most 70 stations). No achievements, no joy meter, no Money tab (investing + tips live in the analysis, `twin/tipps.py`);
Career = Job after your degree, Entry job, Job change, Part-time, Retire; Housing = buy a home (UBS mortgage, price
adjustable), rent a luxury flat, adjust monthly costs; Family = wedding, child (costs adjustable, end at 18);
Time off = gap year.
Later real monthly data (CSV: `month,net_transactions_chf[,closing_cash_chf]`) updates the twin with
`twin/daten_update.py` (`GameSession.ride` / `aktualisiere_mit_daten`); the film ride is no longer offered in the game UI.
The whole GUI (game + analysis) is in English. No XP/levels. A fresh game starts with an intro (fly-over of the island,
how to play, countdown; skippable). The game invests with the balanced default; investment styles are compared
on the analysis page. "Get married" plays its own wedding scene (chapel, guests, partner) and the partner then rides along in the car.

**Next round** (details in `CONTRACT.md`, section "Update: next round"):
- A degree no longer starts a job: the player is "graduated / looking" (no income, no ALV) and picks
  "Job after your degree" (bachelor CHF 5'200, master CHF 6'300, apprenticeship CHF 5'000) or a gap year.
- Retirement is a card from 60 (about 60 % of the last salary, AHV + pension fund); at 70 it happens anyway.
  Life (and the engine horizon, max. 70 years) runs to 85.
- Adjustable cards (`params`): house price, child costs per month (end after 216 months), monthly costs (±).
  Action `card_params` updates lock, preview and text.
- Skip: `{"action": "skip", "years": n}` or `{"until": "event"}` drives several years in one step.
- The uploaded CSV is only the past net flow per month; future costs come from the status quo and the game's decisions.

**End of the game → life review** (analysis page):
- The game ends with the financial facts; "YOUR LIFE REVIEW ▶" sends `{"action": "analyse"}` and the analysis page
  (`ui/analyse.py`) starts with the review, in the game's style (Lilita One / Nunito, chunky ink-bordered cards):
  1. **Your timeline** from your starting age to 85 with every choice AND its follow-up events (degree finished, child
     moves out, retirement at 70, …): green ▲ = better for your money, red ▼ = costs you money, grey ● = about the
     same. It is editable (`twin/lifereview`): drag a choice to another age (its events move along, a ghost stays at
     the played age), press Delete to take it out, "+ Add event" for another life decision (age + card values).
  2. **Your twin says**: your own 3D character on its podium (`twin.three_d.podium`, SVG fallback) delivers the
     verdict (grade A–E), "Here's what went well …" and "Where you can do better …" (every negative with a BETTER
     tip) as a game-style speech panel; the chat sits underneath ("Did I do well?" → tool `review`, "Suggest another
     path" → tool `suggest`). Every change of the new path is announced by the twin in the chat.
  3. **Try another path**: the twin's suggestions (`twin.alt_path.suggestions`: move a choice ±3/±5 years, drop a
     costly one, add one you did not take) – the best ▲ ones and at least two instructive ▼ ones, each with its CHF
     effect at 85. "Try it" puts it on the timeline; "↺ Reset" brings the played life back.
  4. **Expected net worth** (Juli's chart), at the very bottom of the page (after "Explore more"): median with the
     p5–p95 band of your played path, the life you saw (pink) and, once you edited something (on the timeline or by
     telling the twin), the new path (orange), event markers, hover readout per age and the line
     "New path: +CHF X at 85 vs. your path". Same seed for both paths (common random numbers).
  The alternative path is a plain JSON dict in `st.session_state["alt_path"]` (`{"moves": {id: age}, "removed": [id],
  "added": [{id, key, age, params}]}`), reset when a new game is played. If `twin.alt_path` or the component is missing
  the page falls back to the read-only HTML timeline. Below, under "Explore more", the full dashboard stays as before.
  Without a played game the page starts with **YOUR PLAN**: this page's life plan (`st.session_state.events`, the
  same list as "Explore more → Life plan") as the same editable timeline (drag, ✕, "+ Add event" with the game's
  options via `twin.alt_path.option_events`), the chat (which can edit the plan too), and at the very bottom the
  plan's expected net worth over the sidebar horizon – compared with "no events" once the plan has events.
- `twin/review.py`: `review(game_session)` → `{verdict, timeline, positives, negatives, facts}`. The arrow and amount
  of a choice are the ones its card showed in the game (median at 85 with the choice minus "drive on" at that moment,
  same seed), so the timeline never contradicts the cards; `effect` = the whole-life effect (all played decisions WITH
  vs WITHOUT that one, same seed = common random numbers, whole life re-simulated) is kept per item; life-wide checks on the played life (months on credit, biggest loan, buffer, savings rate, retirement,
  gap years, children, house purchases that would often fail). Cached, well under a second for a typical game.
- `twin/lifechart/review_view.py`: the game-style HTML blocks (hero, read-only timeline, the twin's speech panel,
  number tiles; fonts embedded from `twin/frontend3d/fonts`, offline).
- `twin/alt_path.py`: the alternative life (moved / removed / added decisions → events, `simulate_paths`,
  `suggestions`); `twin/lifereview/`: the offline component (editable timeline, suggestion cards, net-worth chart).
