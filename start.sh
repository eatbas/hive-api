#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv"

if command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
  PYTHON_BIN="python"
else
  echo "Error: neither 'python3' nor 'python' was found on PATH."
  exit 1
fi

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
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
  python -m pip install --quiet -e ".[dev]"
fi

HOST="${AI_CLI_API_HOST:-127.0.0.1}"
PORT="${AI_CLI_API_PORT:-8000}"

echo "Checking CLI availability..."
for cli in claude gemini codex kimi copilot opencode; do
  if command -v "$cli" &>/dev/null; then
    echo "  $cli: $(command -v "$cli")"
  else
    echo "  $cli: not found"
  fi
done
echo ""

echo "Starting AI CLI API on http://${HOST}:${PORT}"
exec python -m uvicorn ai_cli_api.main:app --host "$HOST" --port "$PORT"
