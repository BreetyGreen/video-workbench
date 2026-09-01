#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then echo "Usage: $0 https://server.example.com" >&2; exit 2; fi
case "$1" in https://*) ;; *) echo 'HTTPS server URL required.' >&2; exit 2;; esac
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE="$ROOT/VideoWorkbenchSync"
[ -f "$SOURCE" ] || SOURCE="$ROOT/dist/VideoWorkbenchSync"
[ -f "$SOURCE" ] || { echo 'Build VideoWorkbenchSync first.' >&2; exit 2; }
INSTALL="$HOME/Applications/VideoWorkbenchSync"
DATA="$HOME/Library/Application Support/VideoWorkbench Sync"
PLIST="$HOME/Library/LaunchAgents/com.video-workbench.sync.plist"
mkdir -p "$HOME/Applications" "$DATA" "$HOME/Library/LaunchAgents"
cp "$SOURCE" "$INSTALL"; chmod 755 "$INSTALL"
echo '首次配对：请粘贴服务器配置助手刚生成的一次性配对码。'
"$INSTALL" --server-url "$1" --data-dir "$DATA"
sed -e "s|__EXECUTABLE__|$INSTALL|g" -e "s|__SERVER_URL__|$1|g" -e "s|__DATA_DIR__|$DATA|g" \
  "$ROOT/com.video-workbench.sync.plist" > "$PLIST"
launchctl bootout "gui/$(id -u)/com.video-workbench.sync" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo 'Public distribution requires Developer ID signing and Apple notarization.' >&2
