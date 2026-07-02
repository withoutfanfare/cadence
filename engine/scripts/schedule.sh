#!/usr/bin/env bash
# cadence schedule [show|status|register|tick|apply] — one launchd scheduler for project configs.
#   show      print each job's configured cadence (read-only)
#   register  add a project (dir or config .env) to the scheduler registry
#   apply     regenerate the single scheduler plist and reload it
# Generation lives in engine/schedule/cli.py; this script orchestrates files+launchd.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

CLI="$CADENCE_HOME/engine/schedule/cli.py"
PLISTDIR="$HOME/Library/LaunchAgents"
GUI="gui/$(id -u)"
SCHEDULER_PLIST="$PLISTDIR/com.cadence.scheduler.plist"

plist_path() { # stage -> file
  case "$1" in conduct) echo "$PLISTDIR/com.cadence.conduct.plist" ;;
               *)       echo "$PLISTDIR/com.cadence.loop-$1.plist" ;; esac
}

unload_legacy_jobs() {
  for j in triage spec build revise advance conduct; do
    f="$(plist_path "$j")"
    launchctl bootout "$GUI" "$f" 2>/dev/null || true
    rm -f "$f"
  done
}

case "${1:-show}" in
  show|"")
    exec python3 "$CLI" show ;;
  status)
    exec python3 "$CLI" status ;;
  register)
    shift 2>/dev/null || true
    exec python3 "$CLI" register "$@" ;;
  tick)
    exec python3 "$CLI" tick ;;
  apply)
    cadence_require_launchd_root_config || exit 1
    python3 "$CLI" check || { echo "Fix the SCHED_* values in the active config, then re-run." >&2; exit 1; }
    tmp="$(mktemp "$SCHEDULER_PLIST.tmp.XXXXXX")" || { echo "could not create temp scheduler plist" >&2; exit 1; }
    if ! python3 "$CLI" render-scheduler > "$tmp" || [ ! -s "$tmp" ]; then
      rm -f "$tmp"
      echo "render scheduler failed — left $SCHEDULER_PLIST untouched" >&2
      exit 1
    fi
    mv "$tmp" "$SCHEDULER_PLIST"
    launchctl bootout "$GUI" "$SCHEDULER_PLIST" 2>/dev/null || true
    if launchctl bootstrap "$GUI" "$SCHEDULER_PLIST"; then
      unload_legacy_jobs
      echo "  applied scheduler"
    else
      echo "  FAILED to load scheduler" >&2
      exit 1
    fi
    echo
    python3 "$CLI" status ;;
  *)
    echo "usage: cadence schedule [show|status|register [path]|tick|apply]" >&2
    exit 2 ;;
esac
