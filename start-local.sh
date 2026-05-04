#!/usr/bin/env bash
# Starts Symphony bound to all interfaces (0.0.0.0) so Docker containers
# and other local network clients can reach it.
#
# Usage:
#   bash start-local.sh              # binds 0.0.0.0:8080
#   SYMPHONY_PORT=9000 bash start-local.sh   # custom port
#   SYMPHONY_HOST=172.21.0.1 bash start-local.sh  # Docker bridge only

export SYMPHONY_HOST="${SYMPHONY_HOST:-0.0.0.0}"
export SYMPHONY_PORT="${SYMPHONY_PORT:-8080}"

exec "$(dirname "$0")/start.sh"
