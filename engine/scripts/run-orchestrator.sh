#!/bin/bash
# run-orchestrator.sh - execute a chosen loop orchestrator provider.
# Usage: run-orchestrator.sh <claude|codex|kimi|opencode> <model> <workdir> <prompt-file> <stage>
set -u

_pp="${RUNNER_PATH_PREPEND:-}"
[ -z "$_pp" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _pp="$HOME/Library/Application Support/Herd/bin"
_base_path="$HOME/.kimi-code/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export PATH="${_pp:+$_pp:}${PATH:+$PATH:}$_base_path"

if [ "$#" -ne 5 ]; then
  echo "run-orchestrator: bad args" >&2
  exit 3
fi

PROVIDER="${1:?provider}"
MODEL="${2:?model}"
WORKDIR="${3:?workdir}"
PROMPT_FILE="${4:?prompt file}"
STAGE="${5:?stage}"
TIMEOUT="${ORCH_TIMEOUT:-3600}"

[ -d "$WORKDIR" ] || { echo "run-orchestrator: workdir not found: $WORKDIR" >&2; exit 3; }
[ -f "$PROMPT_FILE" ] || { echo "run-orchestrator: prompt not found: $PROMPT_FILE" >&2; exit 3; }
PROMPT="$(cat "$PROMPT_FILE")"

echo "run-orchestrator: $PROVIDER $STAGE model=$MODEL workdir=$WORKDIR timeout=${TIMEOUT}s" >&2

case "$PROVIDER" in
  claude)
    cd "$WORKDIR" || exit 3
    timeout "$TIMEOUT" claude -p "$PROMPT" --model "$MODEL" --dangerously-skip-permissions
    ;;
  codex)
    timeout "$TIMEOUT" codex exec --model "$MODEL" --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WORKDIR" --skip-git-repo-check "$PROMPT"
    ;;
  kimi)
    cd "$WORKDIR" || exit 3
    timeout "$TIMEOUT" kimi -p "$PROMPT" -m "$MODEL"
    ;;
  opencode)
    timeout "$TIMEOUT" opencode run --model "$MODEL" --dir "$WORKDIR" --dangerously-skip-permissions "$PROMPT"
    ;;
  *)
    echo "run-orchestrator: unknown provider: $PROVIDER" >&2
    exit 2
    ;;
esac
RC=$?
[ "$RC" = 124 ] && echo "run-orchestrator: $PROVIDER timed out after ${TIMEOUT}s" >&2
exit "$RC"
