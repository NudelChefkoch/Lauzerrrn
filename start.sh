#!/usr/bin/env bash
# Starts "YOUR LIFE · YOUR CHOICE" (Streamlit) with one command:   ./start.sh   [PORT]
# - creates the venv if needed and installs missing packages (incl. watchdog)
# - checks that the challenge data can be found
# - stops an older instance of this app on the port instead of falling back to a new port
# - opens the browser (disable with NO_BROWSER=1)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8501}"
VENV="venv"
PKGS=(numpy pandas streamlit plotly watchdog)

say() { printf '\033[1;34m▶\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }

# 1. virtual environment
if [[ ! -x "$VENV/bin/python" ]]; then
  say "Creating the Python environment ($VENV) ..."
  python3 -m venv "$VENV"
fi
PY="$VENV/bin/python"

# 2. packages
missing=()
for p in "${PKGS[@]}"; do
  "$PY" -c "import $p" 2>/dev/null || missing+=("$p")
done
if (( ${#missing[@]} )); then
  say "Installing missing packages: ${missing[*]}"
  "$PY" -m pip install -q --disable-pip-version-check "${missing[@]}"
fi

# 3. data
DATA="${TWIN_DATA_DIR:-../ai-financial-twin-lauzhack-2026/Data}"
if [[ ! -f "$DATA/synthetic-profiles.csv" ]]; then
  warn "Challenge data not found in: $DATA"
  warn "Put the folder there or set TWIN_DATA_DIR=/path/to/Data."
  exit 1
fi

# 4. free the port (only an old Streamlit instance is stopped, anything else aborts)
pids="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)"
for pid in $pids; do
  if ps -o command= -p "$pid" | grep -q "streamlit"; then
    say "Stopping the old app instance on port $PORT (PID $pid) ..."
    kill "$pid" 2>/dev/null || true
  else
    warn "Port $PORT is used by another program (PID $pid). Pick another port: ./start.sh 8600"
    exit 1
  fi
done
for _ in {1..20}; do
  lsof -ti "tcp:$PORT" -sTCP:LISTEN >/dev/null 2>&1 || break
  sleep 0.25
done

# 5. start
URL="http://localhost:$PORT"
say "Starting the app: $URL   (stop with Ctrl+C)"
if [[ -z "${NO_BROWSER:-}" ]] && command -v open >/dev/null; then
  (sleep 3; open "$URL") >/dev/null 2>&1 &
fi
exec "$PY" -m streamlit run app.py --server.port "$PORT"
