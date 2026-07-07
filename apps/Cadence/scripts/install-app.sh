#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -n "${HOME:-}" ] || { echo "install-app: HOME is empty" >&2; exit 2; }
[ "$HOME" != "/" ] || { echo "install-app: refusing HOME=/" >&2; exit 2; }
APP="$("$ROOT/scripts/build-app.sh")"
DEST="$HOME/Applications/Cadence.app"
[ "$DEST" = "$HOME/Applications/Cadence.app" ] || { echo "install-app: unexpected destination: $DEST" >&2; exit 2; }

mkdir -p "$HOME/Applications"
pkill -x Cadence >/dev/null 2>&1 || true
rm -rf "$DEST"
cp -R "$APP" "$DEST"
open "$DEST"

echo "$DEST"
