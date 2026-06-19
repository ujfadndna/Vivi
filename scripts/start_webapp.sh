#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/frontend"
API_PORT="${API_PORT:-8100}"
WEB_PORT="${WEB_PORT:-5173}"
HOST="${HOST:-127.0.0.1}"

cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not available on PATH. Install Node.js 20+ first." >&2
  exit 1
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
  (cd "$FRONTEND" && npm install)
fi

cleanup() {
  if [ -n "${API_PID:-}" ]; then kill "$API_PID" 2>/dev/null || true; fi
  if [ -n "${WEB_PID:-}" ]; then kill "$WEB_PID" 2>/dev/null || true; fi
}
trap cleanup INT TERM EXIT

python -m uvicorn app.main:app --host "$HOST" --port "$API_PORT" --reload &
API_PID=$!

(cd "$FRONTEND" && npm run dev -- --host "$HOST" --port "$WEB_PORT") &
WEB_PID=$!

echo "Her Web app: http://localhost:$WEB_PORT/chat"
echo "API health:  http://localhost:$API_PORT/health"

wait
