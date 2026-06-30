#!/bin/bash
# run-reviewer.sh - execute a chosen provider for folded review output.
# Usage: run-reviewer.sh <claude|codex|kimi|opencode> <model> <workdir> <review-brief-file>
set -u

_pp="${RUNNER_PATH_PREPEND:-}"
[ -z "$_pp" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _pp="$HOME/Library/Application Support/Herd/bin"
export PATH="${_pp:+$_pp:}$PATH:$HOME/.kimi-code/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

if [ "$#" -ne 4 ]; then
  echo "run-reviewer: bad args" >&2
  exit 3
fi

PROVIDER="${1:?provider}"
MODEL="${2:?model}"
WORKDIR="${3:?workdir}"
BRIEF="${4:?review brief}"
TIMEOUT="${REVIEW_TIMEOUT:-1800}"

[ -d "$WORKDIR" ] || { echo "run-reviewer: workdir not found: $WORKDIR" >&2; exit 3; }
[ -f "$BRIEF" ] || { echo "run-reviewer: brief not found: $BRIEF" >&2; exit 3; }
PROMPT="$(cat "$BRIEF")"

echo "run-reviewer: $PROVIDER model=$MODEL workdir=$WORKDIR timeout=${TIMEOUT}s" >&2

_run_with_timeout() {
  local timeout="$1"
  local workdir="$2"
  shift 2

  python3 - "$timeout" "$workdir" "$@" <<'PY'
import subprocess
import sys

timeout = float(sys.argv[1])
workdir = sys.argv[2]
cmd = sys.argv[3:]

try:
    proc = subprocess.Popen(cmd, cwd=workdir)
except FileNotFoundError:
    print(f"run-reviewer: command not found: {cmd[0]}", file=sys.stderr)
    sys.exit(127)

try:
    rc = proc.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait()
    sys.exit(124)
except Exception as exc:  # pragma: no cover - runtime guardrail
    print(f"run-reviewer: unexpected error running provider: {exc}", file=sys.stderr)
    sys.exit(1)

sys.exit(rc)
PY
}

case "$PROVIDER" in
  claude)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" claude -p "$PROMPT" --model "$MODEL" --dangerously-skip-permissions
    ;;
  codex)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" codex exec --model "$MODEL" --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WORKDIR" --skip-git-repo-check "$PROMPT"
    ;;
  kimi)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" kimi -p "$PROMPT" -m "$MODEL"
    ;;
  opencode)
    _run_with_timeout "$TIMEOUT" "$WORKDIR" opencode run --model "$MODEL" --dir "$WORKDIR" --dangerously-skip-permissions "$PROMPT"
    ;;
  *)
    echo "run-reviewer: unknown provider: $PROVIDER" >&2
    exit 2
    ;;
esac
RC=$?
[ "$RC" = 124 ] && echo "run-reviewer: $PROVIDER timed out after ${TIMEOUT}s" >&2
exit "$RC"
