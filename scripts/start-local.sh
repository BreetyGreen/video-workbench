#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SERVICE_ROOT="$REPO_ROOT/services/control-plane"
DATA_DIR="$HOME/Library/Application Support/VideoWorkbench"
INBOX_DIR="$HOME/Movies/VideoWorkbench Inbox"
RUN_DIR="$DATA_DIR/run"
LOG_DIR="$DATA_DIR/logs"
PID_FILE="$RUN_DIR/control-plane.pid"
HEALTH_URL="http://127.0.0.1:8130/health"
APP_URL="http://127.0.0.1:8130/"
UV_BIN="${UV_BIN:-}"

if [ -z "$UV_BIN" ] && command -v uv >/dev/null 2>&1; then
  UV_BIN=$(command -v uv)
fi
if [ -z "$UV_BIN" ] && [ -x "$HOME/.local/bin/uv" ]; then
  UV_BIN="$HOME/.local/bin/uv"
fi
if [ -z "$UV_BIN" ] || [ ! -x "$UV_BIN" ]; then
  echo "uv was not found. Run scripts/bootstrap.sh first." >&2
  exit 2
fi

mkdir -p "$DATA_DIR" "$INBOX_DIR" "$RUN_DIR" "$LOG_DIR"

"$UV_BIN" run python "$SCRIPT_DIR/jianying-host-helper.py" \
  --data-dir "$DATA_DIR" --container-draft-root "__host__" --watch \
  >> "$LOG_DIR/jianying-host-helper.log" 2>&1 &

if [ -f "$PID_FILE" ]; then
  EXISTING_PID=$(tr -d '[:space:]' < "$PID_FILE")
  case "$EXISTING_PID" in
    ''|*[!0-9]*)
      echo "Ignoring an invalid PID file: $PID_FILE" >&2
      ;;
    *)
      if kill -0 "$EXISTING_PID" 2>/dev/null; then
        if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
          echo "VideoWorkbench is already running at $APP_URL"
          open "$APP_URL"
          exit 0
        fi
        echo "PID $EXISTING_PID is alive but the service is not healthy; refusing to start a duplicate." >&2
        exit 2
      fi
      ;;
  esac
fi

export VIDEO_WORKBENCH_DATA_DIR="$DATA_DIR"
export VIDEO_WORKBENCH_DATABASE_URL="sqlite:///$DATA_DIR/control-plane.db"
export VIDEO_WORKBENCH_FFMPEG_BIN="$(command -v ffmpeg)"
export VIDEO_WORKBENCH_FFPROBE_BIN="$(command -v ffprobe)"
export VIDEO_WORKBENCH_AUTOMATION_SCHEDULER_ENABLED="true"

cd "$SERVICE_ROOT"
nohup "$UV_BIN" run uvicorn app.main:app --host 127.0.0.1 --port 8130 \
  >> "$LOG_DIR/control-plane.log" 2>&1 &
SERVICE_PID=$!
printf '%s\n' "$SERVICE_PID" > "$PID_FILE.tmp"
mv "$PID_FILE.tmp" "$PID_FILE"

ATTEMPT=0
while [ "$ATTEMPT" -lt 120 ]; do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "VideoWorkbench is ready at $APP_URL"
    open "$APP_URL"
    exit 0
  fi
  if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
    echo "VideoWorkbench exited before becoming healthy. See $LOG_DIR/control-plane.log" >&2
    exit 2
  fi
  ATTEMPT=$((ATTEMPT + 1))
  sleep 1
done

echo "VideoWorkbench did not become healthy within 120 seconds. See $LOG_DIR/control-plane.log" >&2
exit 2
