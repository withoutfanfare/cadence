#!/usr/bin/env bash
# Shared Cadence env loader. Source this from any engine script:
#   source "$(dirname "$0")/../lib/lib-env.sh"
# Resolves CADENCE_HOME from this file's location, loads .env, applies defaults.
# Never uses unquoted $VAR in for-loops (zsh/bash word-splitting trap).

CADENCE_HOME="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
export CADENCE_HOME

if [ -f "$CADENCE_HOME/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$CADENCE_HOME/.env"
  set +a
fi

: "${BASE_BRANCH:=develop}"
: "${WORKTREE_TOOL:=git}"
: "${MODEL_TRIAGE:=sonnet}"
: "${MODEL_SPEC:=opus}"
: "${MODEL_BUILD:=opus}"
: "${MODEL_REVISE:=sonnet}"
: "${BUILD_IMPLEMENTER:=claude}"
: "${NOTIFY:=on}"
: "${MEMORY_BACKEND:=markdown}"
: "${CADENCE_STATE_DIR:=$HOME/.cadence}"
export BASE_BRANCH WORKTREE_TOOL MODEL_TRIAGE MODEL_SPEC MODEL_BUILD MODEL_REVISE \
       BUILD_IMPLEMENTER NOTIFY MEMORY_BACKEND CADENCE_STATE_DIR

mkdir -p "$CADENCE_STATE_DIR/logs" "$CADENCE_STATE_DIR/runs"
