#!/bin/sh
set -eu

DATA_DIR="$HOME/Library/Application Support/VideoWorkbench"
PID_FILE="$DATA_DIR/run/control-plane.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "VideoWorkbench is not running."
  exit 0
fi

PID=$(tr -d '[:space:]' < "$PID_FILE")
case "$PID" in
  ''|*[!0-9]*)
    echo "Invalid PID file: $PID_FILE" >&2
    exit 2
    ;;
esac

if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "Removed a stale VideoWorkbench PID file."
  exit 0
fi

kill "$PID"
ATTEMPT=0
while [ "$ATTEMPT" -lt 20 ]; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "VideoWorkbench stopped."
    exit 0
  fi
  ATTEMPT=$((ATTEMPT + 1))
  sleep 1
done

echo "PID $PID did not stop after 20 seconds; the PID file was retained." >&2
exit 2
