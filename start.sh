#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

cd "$ROOT_DIR"

if [ ! -d "$VENV_DIR" ]; then
  echo "Missing .venv. Run ./setup.sh first."
  exit 1
fi

if [ ! -f .env ]; then
  echo "Missing .env. Run ./setup.sh first."
  exit 1
fi

set -a
source .env
set +a

: "${HOST:=127.0.0.1}"
: "${PORT:=8000}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "ERROR: OPENAI_API_KEY is missing in .env"
  exit 1
fi

if [ -z "${API_TOKEN:-}" ]; then
  echo "ERROR: API_TOKEN is missing in .env"
  exit 1
fi

PY="$VENV_DIR/bin/python"

echo "Generating initial report..."
"$PY" generate_report.py || true

echo "Starting FastAPI..."
"$PY" -m uvicorn app:app --host "$HOST" --port "$PORT" &
API_PID=$!

echo "Starting worker..."
"$PY" worker.py &
WORKER_PID=$!

cleanup() {
  echo
  echo "Stopping Job Ranker..."
  kill "$API_PID" "$WORKER_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

REPORT_URL="http://$HOST:$PORT/report"

sleep 1

if command -v open >/dev/null 2>&1; then
  open "$REPORT_URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$REPORT_URL"
fi

echo
echo "Job Ranker is running:"
echo "$REPORT_URL"
echo
echo "Press Ctrl+C to stop."

wait
