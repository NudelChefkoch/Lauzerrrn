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
- `app.py`: Streamlit UI (profile, life plan editor, Apollo-13 crisis buttons, fan chart, sensitivity, assumptions)
- `ui/spiel.py`: game mode "Lebensweg": avatar creator, animated road board, yearly decision cards with twin previews, fate cards
- `ui/analyse.py`: analysis dashboard ("Your twin" chat with the player's avatar, life chart, tips & investing)
- `twin/lifechart/`: offline Streamlit custom component (plain HTML/JS, no build step): net worth over age with p5–p95
  band, a comparison life path ("two life paths"), event markers and a per-month hover readout
- `twin/analysis_chat.py`: the twin's chat. Our model computes every number (house at age X for price Y, strategy
  comparison, pillar 3a, job loss / crash, tornado, tips); a local open-source LLM via Ollama only picks the tool.
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
Later real monthly data (CSV: `month,net_transactions_chf[,closing_cash_chf]`) can be replayed as a film ride: the twin is
updated with `twin/daten_update.py` and drives through the months, then shows the updated statements.
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
