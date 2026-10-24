#!/bin/bash
# Builds Stockholm.app — a SwiftUI menu bar panel that reads the watcher's snapshot.json.
# Needs Xcode Command Line Tools only. Usage:
#   ./build_app.sh [watcher-dir]      build, start now, start at login (default dir: ~/stockholm-syndrome)
#   ./build_app.sh uninstall
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
APP="$REPO/Stockholm.app"
LABEL="com.stockholm.menubar"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WATCH_DIR="${1:-$HOME/stockholm-syndrome}"

if [[ "${1:-}" == "uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; rm -rf "$APP"; echo "removed $LABEL"; exit 0
fi

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Stockholm</string>
  <key>CFBundleDisplayName</key><string>Stockholm</string>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleExecutable</key><string>Stockholm</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PL
cp "$REPO"/icon/MenuIcon*.png "$APP/Contents/Resources/"
if command -v iconutil >/dev/null; then
  ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    cp "$REPO/icon/icon_${s}.png" "$ICONSET/icon_${s}x${s}.png"
    cp "$REPO/icon/icon_${s}@2x.png" "$ICONSET/icon_${s}x${s}@2x.png"
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" || true
fi
echo "compiling…"
swiftc -O -parse-as-library -target arm64-apple-macosx14.0 -o "$APP/Contents/MacOS/Stockholm" "$REPO/menubar/Stockholm.swift" 2>&1 | grep -E "error" || true
[[ -x "$APP/Contents/MacOS/Stockholm" ]] || { echo "build failed"; exit 1; }
codesign --force --sign - "$APP" 2>/dev/null || true; touch "$APP"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/Stockholm</string><string>$WATCH_DIR</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Stockholm panel running (reading $WATCH_DIR) — folding-phone icon in the menu bar"
