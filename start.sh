#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  python -m venv "$VENV_DIR"
fi

# Activate
if [ -f "$VENV_DIR/Scripts/activate" ]; then
  # Windows (Git Bash / MSYS)
  source "$VENV_DIR/Scripts/activate"
else
  source "$VENV_DIR/bin/activate"
fi

# Install the package if uvicorn isn't available yet
if ! command -v uvicorn &>/dev/null; then
  echo "Installing dependencies..."
  pip install --quiet -e ".[dev]"
fi

HOST="${AI_CLI_API_HOST:-127.0.0.1}"
PORT="${AI_CLI_API_PORT:-8000}"

echo "Starting AI CLI API on http://${HOST}:${PORT}"
exec uvicorn ai_cli_api.main:app --host "$HOST" --port "$PORT"
