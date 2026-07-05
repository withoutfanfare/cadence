#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

swift build -c release >&2

APP="$ROOT/dist/Cadence.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$ROOT/.build/release/Cadence" "$APP/Contents/MacOS/Cadence"
cp "$ROOT/Resources/Info.plist" "$APP/Contents/Info.plist"
cp "$ROOT/Resources/Cadence.icns" "$APP/Contents/Resources/Cadence.icns"
cp "$ROOT/Resources/CadenceMenuBarIcon.svg" "$APP/Contents/Resources/CadenceMenuBarIcon.svg"
chmod +x "$APP/Contents/MacOS/Cadence"

echo "$APP"
