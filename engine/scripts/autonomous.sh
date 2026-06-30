#!/usr/bin/env bash
# cadence autonomous on|off|status — flip autonomous mode in one step.
# "on"  sets AUTONOMOUS=on in .env and loads the advance + conduct launchd jobs.
# "off" sets AUTONOMOUS=0 and unloads (and removes) those two jobs.
# The four gated loops (triage/spec/build/revise) are never touched.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

PLISTDIR="$HOME/Library/LaunchAgents"
SCHED_CLI="$CADENCE_HOME/engine/schedule/cli.py"
GUI="gui/$(id -u)"
ADVANCE_PLIST="$PLISTDIR/com.cadence.loop-advance.plist"
CONDUCT_PLIST="$PLISTDIR/com.cadence.conduct.plist"

# Upsert AUTONOMOUS=<value> in .env (in place, preserving the rest of the file).
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

# Timings come from SCHED_ADVANCE / SCHED_CONDUCT in .env (defaults reproduce the
# historical hourly advancer + 3-hourly conductor). Same generator as `cadence schedule`.
render_job() {
  job="$1"
  plist="$2"
  tmp="$(mktemp "$plist.tmp.XXXXXX")" || { echo "could not create temp plist for $job" >&2; exit 1; }
  if ! python3 "$SCHED_CLI" render "$job" > "$tmp" || [ ! -s "$tmp" ]; then
    rm -f "$tmp"
    echo "render $job failed — left $plist untouched" >&2
    exit 1
  fi
  mv "$tmp" "$plist"
}
load()   { launchctl bootout "$GUI" "$1" 2>/dev/null || true; launchctl bootstrap "$GUI" "$1" && echo "  loaded $(basename "$1")" || echo "  FAILED to load $(basename "$1")" >&2; }
unload() { launchctl bootout "$GUI" "$1" 2>/dev/null || true; rm -f "$1"; echo "  unloaded $(basename "$1")"; }

job_state() { # plist-path label -> prints loaded/—
  if launchctl list 2>/dev/null | grep -q "$1"; then echo "loaded"; else echo "—"; fi
}

print_status() {
  _auto="$(printf '%s' "${AUTONOMOUS:-0}" | tr '[:upper:]' '[:lower:]')"
  case "$_auto" in 1|on|true|yes) echo "autonomous: ON  (AUTONOMOUS=$AUTONOMOUS)";; *) echo "autonomous: off";; esac
  echo "  advance job : $(job_state com.cadence.loop-advance)"
  echo "  conduct job : $(job_state com.cadence.conduct)"
  [ -f "$CADENCE_STATE_DIR/runs/PAUSED" ] && echo "  ⚠️  PAUSED flag set — loops will not run until 'cadence resume'."
  echo "  WIP cap CONDUCT_WIP=${CONDUCT_WIP:-1} · max ${AUTO_MAX_ISSUES_PER_RUN:-1}/run · ${AUTO_MAX_REPAIRS:-3} repairs"
}

case "${1:-status}" in
  on)
    python3 "$SCHED_CLI" check || { echo "fix SCHED_* in .env first (cadence schedule show)" >&2; exit 1; }
    set_env_flag on
    AUTONOMOUS=on
    echo "AUTONOMOUS=on written to $CADENCE_CONFIG"
    render_job advance "$ADVANCE_PLIST"; load "$ADVANCE_PLIST"
    render_job conduct "$CONDUCT_PLIST"; load "$CONDUCT_PLIST"
    echo
    print_status
    echo
    echo "Next: the conductor tops up agent:auto every 3h; the advancer grants gates hourly."
    echo "Shadow what it would do first:  cadence conduct --dry-run   ·   cadence run advance --dry-run"
    ;;
  off)
    set_env_flag 0
    AUTONOMOUS=0
    echo "AUTONOMOUS=0 written to $CADENCE_CONFIG"
    unload "$ADVANCE_PLIST"
    unload "$CONDUCT_PLIST"
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
