#!/usr/bin/env bash
# cadence schedule [show|apply] — config-driven launchd timings (SCHED_* in .env).
#   show   print each job's configured cadence (read-only)
#   apply  regenerate the plists from .env and reload them
# Generation lives in engine/schedule/cli.py; this script orchestrates files+launchd.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

CLI="$CADENCE_HOME/engine/schedule/cli.py"
PLISTDIR="$HOME/Library/LaunchAgents"
GUI="gui/$(id -u)"

plist_path() { # stage -> file
  case "$1" in conduct) echo "$PLISTDIR/com.cadence.conduct.plist" ;;
               *)       echo "$PLISTDIR/com.cadence.loop-$1.plist" ;; esac
}

case "${1:-show}" in
  show|"")
    exec python3 "$CLI" show ;;
  apply)
    cadence_require_launchd_root_config || exit 1
    python3 "$CLI" check || { echo "Fix the SCHED_* values in the active config, then re-run." >&2; exit 1; }
    # Core loops are always (re)written; advance/conduct only when already installed
    # (i.e. autonomous is on) — apply never enables autonomous on its own.
    jobs=(triage spec build revise)
    [ -f "$(plist_path advance)" ] && jobs+=(advance)
    [ -f "$(plist_path conduct)" ] && jobs+=(conduct)
    for j in "${jobs[@]}"; do
      f="$(plist_path "$j")"
      tmp="$(mktemp "$f.tmp.XXXXXX")" || { echo "could not create temp plist for $j" >&2; exit 1; }
      if ! python3 "$CLI" render "$j" > "$tmp" || [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        echo "render $j failed — left $f untouched" >&2
        exit 1
      fi
      mv "$tmp" "$f"
      launchctl bootout "$GUI" "$f" 2>/dev/null || true
      launchctl bootstrap "$GUI" "$f" && echo "  applied $j" || echo "  FAILED to load $j" >&2
    done
    echo
    python3 "$CLI" show ;;
  *)
    echo "usage: cadence schedule [show|apply]" >&2
    exit 2 ;;
esac
