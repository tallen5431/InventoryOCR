#!/usr/bin/env bash
# InventoryOCR App Launcher (portable, venv-safe)

set -euo pipefail

# --- App root (this folder) ---
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

# --- Prefer per-project venv ---
VENV_DIR="$APP_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"

# Optional override: export PY_EXE=/usr/bin/python3 before calling
PY_CMD=""

# 1) Use venv if present
if [[ -x "$VENV_PY" ]]; then
  PY_CMD="$VENV_PY"
fi

# 2) Else create venv with a real Python
if [[ -z "$PY_CMD" ]]; then
  if [[ -n "${PY_EXE:-}" && -x "$PY_EXE" ]]; then
    SYS_PY="$PY_EXE"
  else
    SYS_PY="$(command -v python3 || true)"
  fi

  if [[ -z "${SYS_PY:-}" ]]; then
    echo "[ERROR] No real Python found. Install python3 or set PY_EXE, then retry."
    exit 1
  fi

  echo "[SETUP] No venv found, creating at $VENV_DIR..."
  "$SYS_PY" -m venv "$VENV_DIR" || { echo "[ERROR] venv creation failed"; exit 1; }
  PY_CMD="$VENV_PY"
fi

# --- Ensure dependencies once venv exists ---
if [[ -f "$APP_DIR/requirements.txt" ]]; then
  echo "[SETUP] Ensuring dependencies from requirements.txt..."
  "$PY_CMD" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$PY_CMD" -m pip install -r "$APP_DIR/requirements.txt"
fi

# --- Network env from caller (Server Manager passes HOST/PORT in env) ---
# Default to 8001 to match Caddy backend and config.json
PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"

export FLASK_RUN_PORT="$PORT"
export FLASK_RUN_HOST="$HOST"

# --- Vision model (default to llava:13b; override with OLLAMA_VISION_MODEL env var) ---
export OLLAMA_VISION_MODEL="${OLLAMA_VISION_MODEL:-llava:13b}"

# --- URL prefix: serve at the site root by default. The HTTP_Server manager
# accesses the app directly at http://<host>:<port>/, so an empty prefix is
# correct here. Override (e.g. URL_PREFIX="/inventory") only when running behind
# a reverse proxy that mounts the app under a subpath. ---
export URL_PREFIX="${URL_PREFIX:-}"

# --- Start the app ---
if [[ -f "$APP_DIR/app.py" ]]; then
  echo "[RUN] Starting app.py with $PY_CMD (HOST=$HOST PORT=$PORT)"
  exec "$PY_CMD" "$APP_DIR/app.py"
elif [[ -f "$APP_DIR/run.py" ]]; then
  echo "[RUN] Starting run.py with $PY_CMD (HOST=$HOST PORT=$PORT)"
  exec "$PY_CMD" "$APP_DIR/run.py"
else
  echo "[INFO] No app.py or run.py found in $APP_DIR."
  echo "       Update Start.sh or set 'cmd' in services.json accordingly."
  exit 0
fi
