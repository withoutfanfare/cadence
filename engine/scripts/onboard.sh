#!/usr/bin/env bash
# cadence onboard [path] — put a project on the scheduler in one step:
# config checks + state dir + registry (python), launchd scheduler, doctor.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

# The registry and the launchd scheduler live with the ROOT config — force it
# regardless of cwd or --config, or the registry lands in a project-local state
# dir the scheduler tick never reads. The project itself is the path argument.
CADENCE_CONFIG="$(cd "$DIR/../.." && pwd)/.env"; export CADENCE_CONFIG
unset CADENCE_PROFILE

# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

TARGET="${1:-$PWD}"

python3 "$CADENCE_HOME/engine/schedule/cli.py" onboard "$TARGET" || exit 1

if command -v launchctl >/dev/null 2>&1; then
  bash "$DIR/schedule.sh" apply
else
  echo "  launchctl not found — scheduling is macOS-only; registry updated all the same"
fi

case "$TARGET" in
  *"/.env") CONFIG="$TARGET" ;;
  *)        CONFIG="$TARGET/cadence/.env" ;;
esac
echo
echo "== doctor =="
"$CADENCE_HOME/bin/cadence" --config "$CONFIG" doctor
echo
echo "Onboarded (paused if new). When ready:  cadence --config $CONFIG resume"
