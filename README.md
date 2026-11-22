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
- `ui/analyse.py`: analysis dashboard
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
The game starts with YOUR status quo (one example data set can pre-fill the form) and runs year by year to retirement
at 65. No achievements, no joy meter, no Money tab (investing + tips live in the analysis, `twin/tipps.py`);
Career = Entry job, Job change, Part-time; Housing = buy a home (UBS mortgage) or rent a luxury flat.
Later real monthly data (CSV: `month,net_transactions_chf[,closing_cash_chf]`) can be replayed as a film ride: the twin is
updated with `twin/daten_update.py` and drives through the months, then shows the updated statements.
The whole GUI (game + analysis) is in English. No XP/levels. A fresh game starts with an intro (fly-over of the island,
how to play, countdown; skippable). The investment style (risk) is not asked at the start but from station 2 in the Money
category. "Get married" plays its own wedding scene (chapel, guests, partner) and the partner then rides along in the car.
