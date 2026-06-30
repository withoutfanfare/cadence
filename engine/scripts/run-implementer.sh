#!/bin/bash
# run-implementer.sh — execute a chosen coding agent on a brief, inside a worktree.
# The ONLY place that knows how to invoke each vendor (claude|kimi|opencode|codex).
# The build loop calls it and never branches on vendor itself — add/swap implementers here.
#
# Usage: run-implementer.sh <claude|kimi|opencode|codex> <worktree-path> <brief-file>
# Exit:  0 = ran clean · 124 = timed out · 2 = unknown implementer · 3 = bad args
set -u
# Self-sufficient PATH — callers use a restricted PATH. kimi lives in ~/.kimi-code/bin.
# Optional project tooling prefix (RUNNER_PATH_PREPEND, e.g. a specific PHP); auto-falls
# back to Herd's bin if present, so the implementer's php/composer match the project.
_pp="${RUNNER_PATH_PREPEND:-}"
[ -z "$_pp" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _pp="$HOME/Library/Application Support/Herd/bin"
export PATH="${_pp:+$_pp:}$HOME/.kimi-code/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
IMPL="${1:?implementer (claude|kimi|opencode|codex)}"
WT="${2:?worktree path}"
BRIEF="${3:?brief file}"
TIMEOUT="${IMPL_TIMEOUT:-1200}"   # 20 min; override via IMPL_TIMEOUT

[ -d "$WT" ]    || { echo "run-implementer: worktree not found: $WT" >&2; exit 3; }
[ -f "$BRIEF" ] || { echo "run-implementer: brief not found: $BRIEF" >&2; exit 3; }
cd "$WT" || exit 3
PROMPT="$(cat "$BRIEF")"

echo "run-implementer: $IMPL in $WT (timeout ${TIMEOUT}s)" >&2
# Auto-approve in headless mode differs per vendor:
#  claude   → --dangerously-skip-permissions
#  kimi     → plain `-p` auto-approves (REJECTS --yolo/--auto, which are interactive)
#  opencode → `run` auto-approves; model pinned (its config default `glm-5` is stale)
#  codex    → --dangerously-bypass-approvals-and-sandbox (externally sandboxed here);
#             -c 'mcp_servers={}' disables its MCP servers (serena/playwright/copilot),
#             which otherwise hang a headless run trying to connect/authenticate.
case "$IMPL" in
  claude)   timeout "$TIMEOUT" claude -p "$PROMPT" --model sonnet --dangerously-skip-permissions ;;
  kimi)     timeout "$TIMEOUT" kimi   -p "$PROMPT" ;;
  opencode) timeout "$TIMEOUT" opencode run --model "${OPENCODE_MODEL:-zai-coding-plan/glm-5.2}" "$PROMPT" ;;
  codex)    timeout "$TIMEOUT" codex exec --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WT" --skip-git-repo-check "$PROMPT" ;;
  *) echo "run-implementer: unknown implementer: $IMPL" >&2; exit 2 ;;
esac
RC=$?
[ "$RC" = 124 ] && echo "run-implementer: $IMPL timed out after ${TIMEOUT}s" >&2
exit $RC
