#!/bin/bash
# run-reviewer.sh - execute a chosen provider for folded review output.
# Usage: run-reviewer.sh <claude|codex|kimi|opencode> <model> <workdir> <review-brief-file>
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PROVIDER="${1:?provider}"
MODEL="${2:?model}"
WORKDIR="${3:?workdir}"
BRIEF="${4:?review-brief-file}"
TIMEOUT="${REVIEW_TIMEOUT:-1800}"

ORCH_TIMEOUT="$TIMEOUT" "$DIR/run-orchestrator.sh" "$PROVIDER" "$MODEL" "$WORKDIR" "$BRIEF" "review"
