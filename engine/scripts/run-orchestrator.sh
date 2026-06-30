#!/bin/bash
# run-orchestrator.sh - execute a chosen loop orchestrator provider.
# Usage: run-orchestrator.sh <claude|codex|kimi|opencode> <model> <workdir> <prompt-file> <stage>
set -u

DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_RUNNER_PATH_PREPEND="${RUNNER_PATH_PREPEND:-}"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"
if [ -n "$_RUNNER_PATH_PREPEND" ]; then
  RUNNER_PATH_PREPEND="$_RUNNER_PATH_PREPEND"
  export RUNNER_PATH_PREPEND
fi

if [ "$#" -ne 5 ]; then
  echo "run-orchestrator: bad args" >&2
  exit 3
fi

RUNNER_PATH="$(cadence_runner_path)"
export PATH="$RUNNER_PATH"

PROVIDER="${1:?provider}"
MODEL="${2:?model}"
WORKDIR="${3:?workdir}"
PROMPT_FILE="${4:?prompt file}"
STAGE="${5:?stage}"
TIMEOUT="${ORCH_TIMEOUT:-3600}"

[ -d "$WORKDIR" ] || { echo "run-orchestrator: workdir not found: $WORKDIR" >&2; exit 3; }
[ -f "$PROMPT_FILE" ] || { echo "run-orchestrator: prompt not found: $PROMPT_FILE" >&2; exit 3; }

echo "run-orchestrator: $PROVIDER $STAGE model=$MODEL workdir=$WORKDIR timeout=${TIMEOUT}s" >&2

_run_with_timeout() {
  local timeout="$1"
  local workdir="$2"
  local stdin_file="$3"
  shift 3

  python3 - "$timeout" "$workdir" "$stdin_file" "$@" <<'PY'
import subprocess
import sys

timeout = float(sys.argv[1])
workdir = sys.argv[2]
stdin_path = sys.argv[3]
cmd = sys.argv[4:]

stdin_handle = None
try:
    if stdin_path:
        stdin_handle = open(stdin_path, "rb")
    proc = subprocess.Popen(cmd, cwd=workdir, stdin=stdin_handle)
except FileNotFoundError:
    print(f"run-orchestrator: command not found: {cmd[0]}", file=sys.stderr)
    sys.exit(127)

try:
    rc = proc.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait()
    sys.exit(124)
except Exception as exc:  # pragma: no cover - runtime guardrail
    print(f"run-orchestrator: unexpected error running provider: {exc}", file=sys.stderr)
    sys.exit(1)
finally:
    if stdin_handle is not None:
        stdin_handle.close()

sys.exit(rc)
PY
}

case "$PROVIDER" in
  claude)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "$PROMPT_FILE" claude -p "Follow the stdin brief exactly." --model "$MODEL" --dangerously-skip-permissions
    ;;
  codex)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "$PROMPT_FILE" codex exec --model "$MODEL" --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WORKDIR" --skip-git-repo-check -
    ;;
  kimi)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "$PROMPT_FILE" kimi -m "$MODEL" -p "Follow the stdin brief exactly."
    ;;
  opencode)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "" opencode run --model "$MODEL" --dir "$WORKDIR" --dangerously-skip-permissions -f "$PROMPT_FILE" --prompt "Follow the attached brief exactly."
    ;;
  *)
    echo "run-orchestrator: unknown provider: $PROVIDER" >&2
    exit 2
    ;;
esac
RC=$?
[ "$RC" = 124 ] && echo "run-orchestrator: $PROVIDER timed out after ${TIMEOUT}s" >&2
exit "$RC"
