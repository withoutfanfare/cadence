#!/usr/bin/env bash
# cadence offboard [path] [--purge] — take a project off the scheduler:
# pause, CADENCE_SCHEDULED=0, unregister (python). Deletes nothing without
# --purge. If the registry is now empty, remove the launchd scheduler job too.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# Same root-config forcing as onboard.sh — the registry is global.
CADENCE_CONFIG="$(cd "$DIR/../.." && pwd)/.env"; export CADENCE_CONFIG
unset CADENCE_PROFILE

# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

python3 "$CADENCE_HOME/engine/schedule/cli.py" offboard "$@" || exit 1

# Registry edits take effect on the next tick without reloading the scheduler
# (the plist doesn't embed projects). Only an EMPTY registry warrants launchd
# work: unload the scheduler so nothing ticks for nobody.
if command -v launchctl >/dev/null 2>&1; then
  if python3 "$CADENCE_HOME/engine/schedule/cli.py" status | grep -q '(none)'; then
    PLIST="$HOME/Library/LaunchAgents/com.cadence.scheduler.plist"
    launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "  registry empty — scheduler job removed (cadence schedule apply restores it)"
  fi
fi
