#!/usr/bin/env bash
# Clio hygiene "dream" pass — runs /cadence-tend --apply for the configured namespace.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
LOG="$CADENCE_STATE_DIR/logs/tend.log"; mkdir -p "$(dirname "$LOG")"
[ "$MEMORY_BACKEND" = "clio" ] || { echo "tend: MEMORY_BACKEND != clio, nothing to do"; exit 0; }
[ -n "${MEMORY_NAMESPACE:-}" ] || { echo "tend: MEMORY_NAMESPACE unset" >&2; exit 1; }
cd "$PROJECT_DIR" 2>/dev/null || cd "$HOME" || exit 1
{
  echo "[$(date -u +%FT%TZ)] cadence-tend $MEMORY_NAMESPACE"
  claude -p "/cadence-tend $MEMORY_NAMESPACE --apply" --model "$MODEL_REVISE" --dangerously-skip-permissions
  echo "[$(date -u +%FT%TZ)] cadence-tend done (exit $?)"
} >> "$LOG" 2>&1
