#!/usr/bin/env bash
# Shared Cadence env loader. Source this from any engine script:
#   source "$(dirname "$0")/../lib/lib-env.sh"
# Resolves CADENCE_HOME from this file's location, loads .env, applies defaults.
# Never uses unquoted $VAR in for-loops (zsh/bash word-splitting trap).

CADENCE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
export CADENCE_HOME

if [ -n "${CADENCE_CONFIG:-}" ]; then
  :
elif [ -f "$PWD/cadence/.env" ]; then
  CADENCE_CONFIG="$PWD/cadence/.env"
else
  CADENCE_CONFIG="$CADENCE_HOME/.env"
fi
export CADENCE_CONFIG

if [ -f "$CADENCE_CONFIG" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$CADENCE_CONFIG"
  set +a
fi

: "${BASE_BRANCH:=develop}"
: "${WORKTREE_TOOL:=git}"
: "${MODEL_TRIAGE:=sonnet}"
: "${MODEL_SPEC:=opus}"
: "${MODEL_BUILD:=opus}"
: "${MODEL_REVISE:=sonnet}"
: "${ORCHESTRATOR_PROVIDER:=claude}"
: "${ORCHESTRATOR_TRIAGE:=${ORCHESTRATOR_PROVIDER}:${MODEL_TRIAGE}}"
: "${ORCHESTRATOR_SPEC:=${ORCHESTRATOR_PROVIDER}:${MODEL_SPEC}}"
: "${ORCHESTRATOR_BUILD:=${ORCHESTRATOR_PROVIDER}:${MODEL_BUILD}}"
: "${ORCHESTRATOR_REVISE:=${ORCHESTRATOR_PROVIDER}:${MODEL_REVISE}}"
: "${ORCHESTRATOR_ADVANCE:=${ORCHESTRATOR_PROVIDER}:${MODEL_ADVANCE:-sonnet}}"
: "${REVIEW_PROVIDER:=claude}"
: "${REVIEW_MODEL:=opus}"
: "${BUILD_IMPLEMENTER:=claude}"
: "${NOTIFY:=on}"
: "${MEMORY_BACKEND:=markdown}"
: "${CADENCE_STATE_DIR:=$HOME/.cadence}"
export BASE_BRANCH WORKTREE_TOOL MODEL_TRIAGE MODEL_SPEC MODEL_BUILD MODEL_REVISE \
       BUILD_IMPLEMENTER NOTIFY MEMORY_BACKEND CADENCE_STATE_DIR \
       ORCHESTRATOR_PROVIDER ORCHESTRATOR_TRIAGE ORCHESTRATOR_SPEC ORCHESTRATOR_BUILD \
       ORCHESTRATOR_REVISE ORCHESTRATOR_ADVANCE REVIEW_PROVIDER REVIEW_MODEL

cadence_runner_path() {
  local _runner_prefix="${RUNNER_PATH_PREPEND:-}"
  [ -z "$_runner_prefix" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _runner_prefix="$HOME/Library/Application Support/Herd/bin"
  printf '%s%s\n' "${_runner_prefix:+$_runner_prefix:}" "$HOME/.kimi-code/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
}

mkdir -p "$CADENCE_STATE_DIR/logs" "$CADENCE_STATE_DIR/runs"
