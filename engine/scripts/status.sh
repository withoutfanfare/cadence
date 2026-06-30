#!/usr/bin/env bash
# cadence status — glanceable agent-loop status.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"
RUNS="$CADENCE_STATE_DIR/runs"; LOGD="$CADENCE_STATE_DIR/logs"

echo "── Cadence loops${LINEAR_TEAM_NAME:+ · $LINEAR_TEAM_NAME} ──────────────"
if [ -f "$RUNS/PAUSED" ]; then
  echo "  ⏸  PAUSED  (cadence resume to continue)"
else
  echo "  ▶  live · stages staggered (~one every 15 min; see launchd jobs below)"
fi
echo; echo "launchd jobs (last exit code):"
launchctl list 2>/dev/null | awk '/cadence\.(loop|conduct)/{printf "  %-32s %s\n",$3,$2}' || echo "  (none loaded)"
echo; echo "Last run per stage:"
for s in triage spec build revise advance conduct; do
  st=$(grep "starting .* $s " "$LOGD/$s.log" 2>/dev/null | tail -1 | grep -oE '^\[[^]]+\]')
  [ -z "$st" ] && [ "$s" = "conduct" ] && st=$(grep "conduct —" "$RUNS/activity.log" 2>/dev/null | tail -1 | grep -oE '^\[[^]]+\]')
  printf "  %-7s %s\n" "$s" "${st:-—}"
done
echo; echo "Recent activity (newest last):"
tail -15 "$RUNS/activity.log" 2>/dev/null | sed 's/^/  /' || echo "  (none yet)"
echo; echo "Today's full digest → $RUNS/$(date -u +%F).md"
