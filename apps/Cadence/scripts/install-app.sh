#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$("$ROOT/scripts/build-app.sh")"
DEST="$HOME/Applications/Cadence.app"

mkdir -p "$HOME/Applications"
pkill -x Cadence >/dev/null 2>&1 || true
rm -rf "$DEST"
cp -R "$APP" "$DEST"
open "$DEST"

echo "$DEST"
