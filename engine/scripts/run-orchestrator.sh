#!/bin/bash
# run-orchestrator.sh - execute a chosen loop orchestrator provider.
# Usage: run-orchestrator.sh <claude|codex|kimi|opencode> <model[:effort]> <workdir> <prompt-file> <stage>
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
# Optional reasoning-effort suffix (ORCHESTRATOR_*=provider:model:effort). Split it
# off here so scheduled runs pin their own effort instead of inheriting whatever
# the machine's CLI default happens to be.
EFFORT=""
case "$MODEL" in
  *:*) EFFORT="${MODEL##*:}"; MODEL="${MODEL%:*}" ;;
esac
WORKDIR="${3:?workdir}"
PROMPT_FILE="${4:?prompt file}"
STAGE="${5:?stage}"
# Default cap on any single orchestrator run (all stages, all projects). Bounds a
# hung/wedged run (e.g. a model idling in a self-monitoring loop) so it cannot hold
# the shared build/revise worktree lock indefinitely. Override per project with
# ORCH_TIMEOUT. 45m gives an honest build in a fresh worktree (cargo/pnpm install +
# gates) room while still killing anything genuinely stuck.
TIMEOUT="${ORCH_TIMEOUT:-2700}"

[ -d "$WORKDIR" ] || { echo "run-orchestrator: workdir not found: $WORKDIR" >&2; exit 3; }
[ -f "$PROMPT_FILE" ] || { echo "run-orchestrator: prompt not found: $PROMPT_FILE" >&2; exit 3; }

echo "run-orchestrator: $PROVIDER $STAGE model=$MODEL${EFFORT:+ effort=$EFFORT} workdir=$WORKDIR timeout=${TIMEOUT}s" >&2

_run_with_timeout() {
  local timeout="$1"
  local workdir="$2"
  local stdin_file="$3"
  shift 3

  python3 - "$timeout" "$workdir" "$stdin_file" "$@" <<'PY'
import os
import signal
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
    # Own session/process group: a provider (claude/codex) spawns gate children
    # (cargo, pnpm, git). Killing only the direct child on timeout would orphan
    # those grandchildren, which keep mutating the worktree after run-loop.sh
    # releases the build/revise lock and the next run starts. start_new_session
    # makes the child the group leader (pid == pgid) so we can kill the whole tree.
    proc = subprocess.Popen(cmd, cwd=workdir, stdin=stdin_handle,
                            start_new_session=True)
except FileNotFoundError:
    print(f"run-orchestrator: command not found: {cmd[0]}", file=sys.stderr)
    sys.exit(127)


def _kill_group(sig):
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass


try:
    rc = proc.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    _kill_group(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        _kill_group(signal.SIGKILL)  # escalate if the group ignores SIGTERM
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

claude_allowed_tools() {
  local stage="$1"
  python3 - "$CADENCE_HOME/skills/cadence-loop-$stage/SKILL.md" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    text = path.read_text(encoding="utf-8")
except FileNotFoundError:
    # The folded "review" stage has no loop skill — its prompt is the brief file,
    # passed directly — so there is no allowed-tools frontmatter to read. Fall back
    # to the read-only set a diff review needs (git/gh + read/search); without this
    # the reviewer runs with no tools and can never confirm review_clean.
    print("Bash,Read,Grep,Glob")
    sys.exit(0)
tools = []
in_tools = False
for line in text.splitlines():
    if line == "---" and in_tools:
        break
    if line == "allowed-tools:":
        in_tools = True
        continue
    if in_tools:
        if line.startswith("  - "):
            tools.append(line.removeprefix("  - ").strip())
            continue
        if line and not line.startswith(" "):
            break
print(",".join(tools))
PY
}

case "$PROVIDER" in
  claude)
    ALLOWED_TOOLS="$(claude_allowed_tools "$STAGE")"
    CMD=(claude -p --model "$MODEL" --allowedTools "$ALLOWED_TOOLS" --dangerously-skip-permissions)
    [ -n "$EFFORT" ] && CMD+=(--effort "$EFFORT")
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "$PROMPT_FILE" "${CMD[@]}"
    ;;
  codex)
    CMD=(codex exec --model "$MODEL" --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WORKDIR" --skip-git-repo-check)
    [ -n "$EFFORT" ] && CMD+=(-c "model_reasoning_effort=\"$EFFORT\"")
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "$PROMPT_FILE" "${CMD[@]}" -
    ;;
  kimi)
    [ -n "$EFFORT" ] && echo "run-orchestrator: effort '$EFFORT' not supported for kimi — ignored" >&2
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "" kimi -m "$MODEL" --add-dir "$(dirname "$PROMPT_FILE")" -p "Read and follow the brief in this file: $PROMPT_FILE"
    ;;
  opencode)
    [ -n "$EFFORT" ] && echo "run-orchestrator: effort '$EFFORT' not supported for opencode — ignored" >&2
    _run_with_timeout "$TIMEOUT" "$WORKDIR" "" opencode run --model "$MODEL" --dir "$WORKDIR" --dangerously-skip-permissions -f "$PROMPT_FILE" "Follow the attached brief exactly."
    ;;
  *)
    echo "run-orchestrator: unknown provider: $PROVIDER" >&2
    exit 2
    ;;
esac
RC=$?
[ "$RC" = 124 ] && echo "run-orchestrator: $PROVIDER timed out after ${TIMEOUT}s" >&2
exit "$RC"
