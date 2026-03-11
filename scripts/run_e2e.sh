#!/usr/bin/env bash
set -euo pipefail

# run_e2e.sh - start uvicorn from .venv, wait for readiness, run pytest, stop server

VENV_DIR=".venv"
PY="$VENV_DIR/bin/python"
UVICORN_LOG="$(pwd)/uvicorn_e2e.log"
PID_FILE=".run_e2e_uvicorn.pid"
HOST="127.0.0.1"
PORT=8000
WAIT_RETRIES=300   # 300 * 0.1s = 30s total wait
WAIT_INTERVAL=0.1

if [ ! -x "$PY" ]; then
  echo "Error: Python executable not found at $PY"
  echo "Make sure you created the virtualenv and installed dependencies (e.g. .venv)."
  exit 2
fi

PYTEST_ARGS=("${@:-tests/test_e2e.py}")

cleanup() {
  if [ -n "${UVICORN_PID:-}" ]; then
    echo "Stopping uvicorn (PID $UVICORN_PID)"
    kill "$UVICORN_PID" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
}
trap cleanup EXIT

echo "Starting uvicorn (logging -> $UVICORN_LOG)"
nohup "$PY" -m uvicorn src.app:app --host "$HOST" --port "$PORT" > "$UVICORN_LOG" 2>&1 &
UVICORN_PID=$!
echo "$UVICORN_PID" > "$PID_FILE"
echo "uvicorn PID: $UVICORN_PID"

echo -n "Waiting for $HOST:$PORT to accept connections"
COUNT=0
if command -v nc >/dev/null 2>&1; then
  while ! nc -z "$HOST" "$PORT"; do
    sleep "$WAIT_INTERVAL"
    printf "."
    COUNT=$((COUNT+1))
    if [ "$COUNT" -ge "$WAIT_RETRIES" ]; then
      echo
      echo "Timed out waiting for uvicorn to start. See $UVICORN_LOG"
      tail -n 100 "$UVICORN_LOG" || true
      exit 3
    fi
  done
else
  while true; do
    "$PY" - <<'PY' >/dev/null 2>&1
import socket, sys
try:
    s=socket.create_connection(("127.0.0.1", 8000), timeout=1)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
PY
    if [ $? -eq 0 ]; then
      break
    fi
    sleep "$WAIT_INTERVAL"
    printf "."
    COUNT=$((COUNT+1))
    if [ "$COUNT" -ge "$WAIT_RETRIES" ]; then
      echo
      echo "Timed out waiting for uvicorn to start. See $UVICORN_LOG"
      tail -n 100 "$UVICORN_LOG" || true
      exit 3
    fi
  done
fi
echo
echo "uvicorn is up. Running pytest: ${PYTEST_ARGS[*]}"

"$PY" -m pytest "${PYTEST_ARGS[@]}"
TEST_EXIT=$?

exit $TEST_EXIT
