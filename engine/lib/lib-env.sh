#!/usr/bin/env bash
# Shared Cadence env loader. Source this from any engine script:
#   source "$(dirname "$0")/../lib/lib-env.sh"
# Resolves CADENCE_HOME from this file's location, loads .env, applies defaults.
# Never uses unquoted $VAR in for-loops (zsh/bash word-splitting trap).

CADENCE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
export CADENCE_HOME

if [ -n "${CADENCE_PROFILE:-}" ]; then
  case "$CADENCE_PROFILE" in
    *[!A-Za-z0-9_.-]*|"") echo "invalid profile: $CADENCE_PROFILE" >&2; exit 2 ;;
  esac
  _CADENCE_PROFILE_FILE="$CADENCE_HOME/profiles/$CADENCE_PROFILE"
  if [ ! -f "$_CADENCE_PROFILE_FILE" ]; then
    echo "unknown profile: $CADENCE_PROFILE" >&2
    exit 2
  fi
  CADENCE_CONFIG=""
  while IFS= read -r _CADENCE_PROFILE_LINE || [ -n "$_CADENCE_PROFILE_LINE" ]; do
    case "$_CADENCE_PROFILE_LINE" in ""|\#*) continue ;; esac
    CADENCE_CONFIG="$_CADENCE_PROFILE_LINE"
    break
  done < "$_CADENCE_PROFILE_FILE"
  if [ -z "$CADENCE_CONFIG" ]; then
    echo "empty profile: $CADENCE_PROFILE" >&2
    exit 2
  fi
  if [ ! -f "$CADENCE_CONFIG" ] && [ ! -L "$CADENCE_CONFIG" ]; then
    echo "profile config missing: $CADENCE_CONFIG" >&2
    exit 2
  fi
fi

if [ -n "${CADENCE_CONFIG:-}" ]; then
  if [ -f "$CADENCE_CONFIG" ] || [ -L "$CADENCE_CONFIG" ]; then
    CADENCE_CONFIG="$(cd "$(dirname "$CADENCE_CONFIG")" && pwd)/$(basename "$CADENCE_CONFIG")"
  elif [ "${CADENCE_CONFIG#/}" = "$CADENCE_CONFIG" ]; then
    CADENCE_CONFIG="$PWD/$CADENCE_CONFIG"
  fi
elif [ -f "$PWD/cadence/.env" ]; then
  CADENCE_CONFIG="$PWD/cadence/.env"
else
  CADENCE_CONFIG="$CADENCE_HOME/.env"
fi
export CADENCE_CONFIG
_CADENCE_RESOLVED_CONFIG="$CADENCE_CONFIG"

if [ -f "$CADENCE_CONFIG" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$CADENCE_CONFIG"
  set +a
fi
CADENCE_CONFIG="$_CADENCE_RESOLVED_CONFIG"
export CADENCE_CONFIG
unset _CADENCE_RESOLVED_CONFIG
unset _CADENCE_PROFILE_FILE _CADENCE_PROFILE_LINE

: "${BASE_BRANCH:=develop}"
: "${TASK_BACKEND:=linear}"
: "${TASK_FILE:=cadence/tasks.md}"
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
export BASE_BRANCH TASK_BACKEND TASK_FILE WORKTREE_TOOL MODEL_TRIAGE MODEL_SPEC MODEL_BUILD MODEL_REVISE \
       BUILD_IMPLEMENTER NOTIFY MEMORY_BACKEND CADENCE_STATE_DIR \
       ORCHESTRATOR_PROVIDER ORCHESTRATOR_TRIAGE ORCHESTRATOR_SPEC ORCHESTRATOR_BUILD \
       ORCHESTRATOR_REVISE ORCHESTRATOR_ADVANCE REVIEW_PROVIDER REVIEW_MODEL

cadence_runner_path() {
  local _runner_prefix="${RUNNER_PATH_PREPEND:-}"
  [ -z "$_runner_prefix" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _runner_prefix="$HOME/Library/Application Support/Herd/bin"
  printf '%s%s\n' "${_runner_prefix:+$_runner_prefix:}" "$HOME/.kimi-code/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
}

cadence_require_launchd_root_config() {
  local _root_config="$CADENCE_HOME/.env"
  if [ "$CADENCE_CONFIG" = "$_root_config" ]; then
    return 0
  fi
  echo "launchd scheduling currently requires $_root_config; active config is $CADENCE_CONFIG" >&2
  echo "Use the root config fallback for scheduled jobs, or run manual commands against project-local cadence/.env with --config." >&2
  return 1
}

mkdir -p "$CADENCE_STATE_DIR/logs" "$CADENCE_STATE_DIR/runs"
