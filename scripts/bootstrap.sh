#!/bin/sh
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This bootstrap is for macOS. On Windows, run scripts/bootstrap.ps1." >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
UV_VERSION="0.12.5"
PYTHON_VERSION="3.12"
DATA_DIR="$HOME/Library/Application Support/VideoWorkbench"
INBOX_DIR="$HOME/Movies/VideoWorkbench Inbox"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

mkdir -p "$DATA_DIR" "$DATA_DIR/run" "$DATA_DIR/logs" "$INBOX_DIR"

if command -v uv >/dev/null 2>&1; then
  UV_BIN=$(command -v uv)
elif [ ! -x "$UV_BIN" ]; then
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
fi
if [ ! -x "$UV_BIN" ] && [ -x "$HOME/.cargo/bin/uv" ]; then
  UV_BIN="$HOME/.cargo/bin/uv"
fi
if [ ! -x "$UV_BIN" ]; then
  echo "uv installation finished but the executable was not found." >&2
  exit 2
fi

"$UV_BIN" python install "$PYTHON_VERSION"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  elif [ -x /opt/homebrew/bin/brew ]; then
    /opt/homebrew/bin/brew install ffmpeg
  elif [ -x /usr/local/bin/brew ]; then
    /usr/local/bin/brew install ffmpeg
  else
    echo "FFmpeg is required. Install Homebrew from https://brew.sh, then run this command again." >&2
    exit 2
  fi
fi

"$UV_BIN" sync \
  --project "$REPO_ROOT/services/control-plane" \
  --python "$PYTHON_VERSION" \
  --locked

UV_BIN="$UV_BIN" exec "$REPO_ROOT/scripts/start-local.sh"
