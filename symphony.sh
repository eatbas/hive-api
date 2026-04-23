#!/usr/bin/env bash
# Symphony API — tmux session manager
# Usage: ./symphony.sh [start|stop|restart|attach|status|logs]

SESSION="symphony"
DIR="/root/symphony-api"
VENV="$DIR/.venv"
UVICORN="$VENV/bin/uvicorn"
LOG="$DIR/symphony.log"

start() {
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "[symphony] Already running (session: $SESSION)"
        return 0
    fi
    echo "[symphony] Starting in tmux session '$SESSION'..."
    tmux new-session -d -s "$SESSION" -x 220 -y 50
    tmux send-keys -t "$SESSION" \
        "cd $DIR && $UVICORN symphony.main:app --host 0.0.0.0 --port 8080 2>&1 | tee -a $LOG" \
        Enter
    echo "[symphony] Started. Attach with:  tmux attach -t $SESSION"
}

stop() {
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "[symphony] Not running."
        return 0
    fi
    echo "[symphony] Stopping session '$SESSION'..."
    tmux kill-session -t "$SESSION"
    echo "[symphony] Stopped."
}

attach() {
    if ! tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "[symphony] Not running. Start it first with: $0 start"
        exit 1
    fi
    tmux attach -t "$SESSION"
}

status() {
    if tmux has-session -t "$SESSION" 2>/dev/null; then
        echo "[symphony] RUNNING (tmux session: $SESSION)"
        echo "[symphony] API: http://127.0.0.1:8080  Docs: http://127.0.0.1:8080/docs"
    else
        echo "[symphony] STOPPED"
    fi
}

logs() {
    if [[ -f "$LOG" ]]; then
        tail -f "$LOG"
    else
        echo "[symphony] No log file yet at $LOG"
    fi
}

case "${1:-start}" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; sleep 1; start ;;
    attach)  attach ;;
    status)  status ;;
    logs)    logs ;;
    *)
        echo "Usage: $0 {start|stop|restart|attach|status|logs}"
        exit 1
        ;;
esac
