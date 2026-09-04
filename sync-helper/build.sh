#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 -m pip install --disable-pip-version-check -r "$ROOT/sync-helper/requirements-build.txt"
python3 -m PyInstaller --noconfirm --clean --onefile --name VideoWorkbenchSync \
  --paths "$ROOT/services/control-plane" \
  --hidden-import ctypes --hidden-import datetime --hidden-import platform --hidden-import shutil --hidden-import typing \
  --add-data "$ROOT/scripts/jianying-host-helper.py:scripts" \
  --distpath "$ROOT/sync-helper/dist" \
  "$ROOT/scripts/sync-jianying-device.py"
shasum -a 256 "$ROOT/sync-helper/dist/VideoWorkbenchSync" > "$ROOT/sync-helper/dist/VideoWorkbenchSync.sha256"
cp "$ROOT/sync-helper/install-macos.sh" "$ROOT/sync-helper/com.video-workbench.sync.plist" "$ROOT/sync-helper/dist/"
echo 'Local build is unsigned and not notarized. Sign and notarize it before public distribution.' >&2
