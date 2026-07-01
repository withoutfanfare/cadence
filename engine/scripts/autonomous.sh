#!/usr/bin/env bash
# cadence autonomous on|off|status — flip autonomous mode in one step.
# "on"  sets AUTONOMOUS=on in the active config.
# "off" sets AUTONOMOUS=0 and removes any legacy autonomous launchd jobs.
# The four gated loops (triage/spec/build/revise) are never touched.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

PLISTDIR="$HOME/Library/LaunchAgents"
GUI="gui/$(id -u)"
SCHEDULER_PLIST="$PLISTDIR/com.cadence.scheduler.plist"
ADVANCE_PLIST="$PLISTDIR/com.cadence.loop-advance.plist"
CONDUCT_PLIST="$PLISTDIR/com.cadence.conduct.plist"

# Upsert AUTONOMOUS=<value> in the active config (in place, preserving the rest of the file).
set_env_flag() {
  AENV="$CADENCE_CONFIG" AVAL="$1" python3 - <<'PY'
import os, re
path, val = os.environ["AENV"], os.environ["AVAL"]
try:
    txt = open(path, encoding="utf-8").read()
except FileNotFoundError:
    txt = ""
line = f"AUTONOMOUS={val}"
if re.search(r'(?m)^\s*AUTONOMOUS=', txt):
    txt = re.sub(r'(?m)^\s*AUTONOMOUS=.*$', line, txt)
else:
    if txt and not txt.endswith("\n"):
        txt += "\n"
    txt += line + "\n"
open(path, "w", encoding="utf-8").write(txt)
PY
}

unload() { launchctl bootout "$GUI" "$1" 2>/dev/null || true; rm -f "$1"; echo "  unloaded $(basename "$1")"; }

job_state() { # plist-path label -> prints loaded/—
  if launchctl list 2>/dev/null | grep -q "$1"; then echo "loaded"; else echo "—"; fi
}

print_status() {
  _auto="$(printf '%s' "${AUTONOMOUS:-0}" | tr '[:upper:]' '[:lower:]')"
  case "$_auto" in 1|on|true|yes) echo "autonomous: ON  (AUTONOMOUS=$AUTONOMOUS)";; *) echo "autonomous: off";; esac
  echo "  scheduler job : $(job_state com.cadence.scheduler)"
  echo "  legacy advance job : $(job_state com.cadence.loop-advance)"
  echo "  legacy conduct job : $(job_state com.cadence.conduct)"
  [ -f "$CADENCE_STATE_DIR/runs/PAUSED" ] && echo "  ⚠️  PAUSED flag set — loops will not run until 'cadence resume'."
  echo "  WIP cap CONDUCT_WIP=${CONDUCT_WIP:-1} · max ${AUTO_MAX_ISSUES_PER_RUN:-1}/run · ${AUTO_MAX_REPAIRS:-3} repairs"
}

case "${1:-status}" in
  on)
    set_env_flag on
    AUTONOMOUS=on
    echo "AUTONOMOUS=on written to $CADENCE_CONFIG"
    echo
    print_status
    echo
    echo "Next: enable scheduling with CADENCE_SCHEDULED=1 and cadence schedule apply."
    echo "The scheduler tops up agent:auto via conduct and grants gates via advance."
    echo "Shadow what it would do first:  cadence conduct --dry-run   ·   cadence run advance --dry-run"
    ;;
  off)
    set_env_flag 0
    AUTONOMOUS=0
    echo "AUTONOMOUS=0 written to $CADENCE_CONFIG"
    unload "$ADVANCE_PLIST"
    unload "$CONDUCT_PLIST"
    [ -f "$SCHEDULER_PLIST" ] && echo "  scheduler left loaded; disable this project with CADENCE_SCHEDULED=0 if needed"
    echo
    print_status
    ;;
  status)
    print_status
    ;;
  *)
    echo "usage: cadence autonomous on|off|status" >&2
    exit 2
    ;;
esac
