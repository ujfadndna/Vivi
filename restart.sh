#!/bin/bash
set -euo pipefail

APP_DIR=/data/Her
PID_FILE="$APP_DIR/server.pid"
LOG_FILE="$APP_DIR/server.log"
PORT=8000
PYTHON=/data/miniconda/envs/torch/bin/python

port_pids() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -ti TCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
        return
    fi

    if command -v netstat >/dev/null 2>&1; then
        netstat -ltnp 2>/dev/null \
            | awk -v port=":$PORT" '$4 ~ port"$" && $7 ~ /^[0-9]+\// { split($7, a, "/"); print a[1] }' \
            | sort -u
        return
    fi

    return 0
}

wait_for_port_free() {
    local deadline=$((SECONDS + 10))
    local pids

    while true; do
        pids="$(port_pids | sort -u | tr '\n' ' ')"
        if [ -z "${pids// }" ]; then
            return 0
        fi

        if [ "$SECONDS" -ge "$deadline" ]; then
            return 1
        fi

        sleep 1
    done
}

kill_pids() {
    local pids=("$@")
    if [ "${#pids[@]}" -eq 0 ]; then
        return
    fi

    echo "[restart] killing PID(s): ${pids[*]}"
    kill "${pids[@]}" 2>/dev/null || true
}

kill_leftover_processes() {
    echo "[restart] killing leftover flashhead workers and stale uvicorn processes"
    pkill -f "flashhead_worker.py" 2>/dev/null || true
    pkill -f "[p]ython.*uvicorn" 2>/dev/null || true
    pkill -f "[u]vicorn" 2>/dev/null || true
}

wait_for_related_processes_exit() {
    local deadline=$((SECONDS + 10))

    while true; do
        if ! pgrep -f "flashhead_worker.py|[p]ython.*uvicorn|[u]vicorn" >/dev/null 2>&1; then
            return 0
        fi

        if [ "$SECONDS" -ge "$deadline" ]; then
            return 1
        fi

        sleep 1
    done
}

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE")"
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[restart] killing old uvicorn PID=$OLD_PID and its children"
        # Kill the entire process group to catch flashhead_worker children.
        PGID=$(ps -o pgid= -p "$OLD_PID" 2>/dev/null | tr -d ' ') || true
        if [ -n "$PGID" ] && [ "$PGID" != "0" ]; then
            kill -- "-$PGID" 2>/dev/null || kill_leftover_processes
        else
            kill "$OLD_PID" 2>/dev/null || kill_leftover_processes
        fi
    fi
fi

# Also kill any orphaned flashhead workers and stale uvicorn processes.
kill_leftover_processes

if ! wait_for_port_free; then
    mapfile -t OCCUPYING_PIDS < <(port_pids | sort -u)
    kill_pids "${OCCUPYING_PIDS[@]}"
    if ! wait_for_port_free; then
        mapfile -t OCCUPYING_PIDS < <(port_pids | sort -u)
        if [ "${#OCCUPYING_PIDS[@]}" -gt 0 ]; then
            echo "[restart] force killing PID(s): ${OCCUPYING_PIDS[*]}"
            kill -9 "${OCCUPYING_PIDS[@]}" 2>/dev/null || true
        fi
        wait_for_port_free || {
            echo "[restart] port $PORT is still occupied; aborting"
            exit 1
        }
    fi
fi

if ! wait_for_related_processes_exit; then
    kill_leftover_processes
    pkill -9 -f "flashhead_worker.py" 2>/dev/null || true
    pkill -9 -f "[p]ython.*uvicorn" 2>/dev/null || true
    pkill -9 -f "[u]vicorn" 2>/dev/null || true
    wait_for_related_processes_exit || {
        echo "[restart] related flashhead/uvicorn processes are still running; aborting"
        exit 1
    }
fi

find "$APP_DIR" -path "*/__pycache__/*.pyc" -type f -delete

cd "$APP_DIR"
nohup "$PYTHON" -m uvicorn app.main:app \
    --host 0.0.0.0 --port "$PORT" \
    >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "[restart] started PID=$NEW_PID"
echo "[restart] waiting for service on port $PORT ..."
DEADLINE=$((SECONDS + 30))
while [ "$SECONDS" -lt "$DEADLINE" ]; do
    if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
        echo "[restart] service is up (PID=$NEW_PID)"
        exit 0
    fi
    sleep 1
done
echo "[restart] ERROR: service did not become healthy within 30s"
exit 1
