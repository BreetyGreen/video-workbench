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
APP="$ROOT/sync-helper/dist/VideoWorkbench Sync Setup.app"
if [ -e "$APP" ] || [ -L "$APP" ]; then
  echo "Refusing to overwrite existing setup app: $APP" >&2
  exit 2
fi
BUILD_STAGE="$ROOT/sync-helper/macos-build-stage"
if [ -e "$BUILD_STAGE" ] || [ -L "$BUILD_STAGE" ]; then
  echo "Refusing to overwrite existing build staging path: $BUILD_STAGE" >&2
  exit 2
fi
mkdir "$BUILD_STAGE"
python3 -m PyInstaller --noconfirm --clean --onefile --name VideoWorkbenchSetup \
  --distpath "$BUILD_STAGE/setup-dist" \
  "$ROOT/sync-helper/macos_setup.py"
STAGED_APP="$BUILD_STAGE/VideoWorkbench Sync Setup.app"
mkdir -p "$STAGED_APP/Contents/MacOS" "$STAGED_APP/Contents/Resources"
cp "$BUILD_STAGE/setup-dist/VideoWorkbenchSetup" "$STAGED_APP/Contents/MacOS/VideoWorkbenchSetup"
cp "$ROOT/sync-helper/dist/VideoWorkbenchSync" "$STAGED_APP/Contents/Resources/VideoWorkbenchSync"
chmod 755 "$STAGED_APP/Contents/MacOS/VideoWorkbenchSetup" "$STAGED_APP/Contents/Resources/VideoWorkbenchSync"
python3 - "$STAGED_APP/Contents/Info.plist" <<'PY'
import plistlib, sys
with open(sys.argv[1], "wb") as stream:
    plistlib.dump({
        "CFBundleDisplayName": "VideoWorkbench 设置",
        "CFBundleExecutable": "VideoWorkbenchSetup",
        "CFBundleIdentifier": "com.video-workbench.sync-setup",
        "CFBundleName": "VideoWorkbench Sync Setup",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
    }, stream, sort_keys=False)
PY
mv "$STAGED_APP" "$APP"
if [ -n "${MACOS_CODESIGN_IDENTITY:-}" ]; then
  codesign --force --options runtime --timestamp --sign "$MACOS_CODESIGN_IDENTITY" "$APP/Contents/Resources/VideoWorkbenchSync"
  codesign --force --options runtime --timestamp --sign "$MACOS_CODESIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  echo 'Setup app is unsigned. Configure MACOS_CODESIGN_IDENTITY before public distribution.' >&2
fi
ditto -c -k --keepParent "$APP" "$ROOT/sync-helper/dist/VideoWorkbench-Sync-Setup-macOS.zip"
if [ -n "${MACOS_NOTARY_KEYCHAIN_PROFILE:-}" ]; then
  [ -n "${MACOS_CODESIGN_IDENTITY:-}" ] || { echo 'Notarization requires signing first.' >&2; exit 2; }
  xcrun notarytool submit "$ROOT/sync-helper/dist/VideoWorkbench-Sync-Setup-macOS.zip" --keychain-profile "$MACOS_NOTARY_KEYCHAIN_PROFILE" --wait
  xcrun stapler staple "$APP"
  ditto -c -k --keepParent "$APP" "$ROOT/sync-helper/dist/VideoWorkbench-Sync-Setup-macOS.zip"
fi
shasum -a 256 "$ROOT/sync-helper/dist/VideoWorkbench-Sync-Setup-macOS.zip" > "$ROOT/sync-helper/dist/VideoWorkbench-Sync-Setup-macOS.zip.sha256"
cp "$ROOT/sync-helper/install-macos.sh" "$ROOT/sync-helper/com.video-workbench.sync.plist" "$ROOT/sync-helper/dist/"
