#!/usr/bin/env bash
# cadence doctor — verify a setup without changing anything.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
_RUNNER_PATH_PREPEND="${RUNNER_PATH_PREPEND:-}"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"
if [ -n "$_RUNNER_PATH_PREPEND" ]; then
  RUNNER_PATH_PREPEND="$_RUNNER_PATH_PREPEND"
  export RUNNER_PATH_PREPEND
fi

RUNNER_PATH="$(cadence_runner_path)"
ok=0; bad=0
pass(){ echo "  ✅ $1"; ok=$((ok+1)); }
fail(){ echo "  ❌ $1"; bad=$((bad+1)); }

provider_from_pair() {
  pair="$1"
  case "$pair" in
    *:*) printf '%s' "${pair%%:*}" ;;
    *) printf '%s' "${ORCHESTRATOR_PROVIDER:-claude}" ;;
  esac
}

check_provider_cli() {
  label="$1"
  provider="$2"
  case "$provider" in
    claude|codex|kimi|opencode)
      if (PATH="$RUNNER_PATH"; command -v "$provider" >/dev/null); then
        pass "$label provider '$provider' found"
      else
        fail "$label provider '$provider' not on PATH"
      fi
      ;;
    *)
      fail "$label provider '$provider' invalid (use claude, codex, kimi, or opencode)"
      ;;
  esac
}

labels_only=0
case "${1:-}" in
  --labels) labels_only=1 ;;
  "") ;;
  *) echo "usage: cadence doctor [--labels]" >&2; exit 2 ;;
esac

check_labels() {
  labels_json="$(python3 "$CADENCE_HOME/engine/linear/cli.py" labels-list 2>/dev/null)" || {
    fail "could not list Linear labels"
    return
  }
  missing="$(LABELS_JSON="$labels_json" python3 - <<'PY'
import importlib.util
import json
import os
import pathlib

path = pathlib.Path(os.environ["CADENCE_HOME"]) / "engine" / "linear" / "cli.py"
spec = importlib.util.spec_from_file_location("linear_cli_labels", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
present = {x.get("name") for x in json.loads(os.environ["LABELS_JSON"] or "[]")}
print("\n".join(label for label in mod.AGENT_LABELS if label not in present))
PY
)"
  if [ -z "$missing" ]; then
    pass "Linear agent label vocabulary present"
  else
    fail "missing Linear label(s): $(printf '%s' "$missing" | paste -sd ',' - | sed 's/,/, /g')"
  fi
}

echo "── cadence doctor ────────────────────────────────"
if [ "$labels_only" = 1 ]; then
  check_labels
  echo
  [ "$bad" -eq 0 ] && echo "doctor: all label checks passed ($ok ok)" || echo "doctor: $bad problem(s), $ok ok"
  exit "$bad"
fi

if [ -f "$CADENCE_CONFIG" ]; then
  pass "config file $CADENCE_CONFIG"
else
  fail "config missing (create cadence/.env or copy .env.example)"
fi
if command -v python3 >/dev/null; then pass "python3 found"; else fail "python3 not on PATH"; fi
if command -v gh >/dev/null; then pass "gh found"; else echo "  ⚠️  gh not found (build PR back-fill needs it)"; fi
check_provider_cli "triage orchestrator" "$(provider_from_pair "$ORCHESTRATOR_TRIAGE")"
check_provider_cli "spec orchestrator" "$(provider_from_pair "$ORCHESTRATOR_SPEC")"
check_provider_cli "build orchestrator" "$(provider_from_pair "$ORCHESTRATOR_BUILD")"
check_provider_cli "revise orchestrator" "$(provider_from_pair "$ORCHESTRATOR_REVISE")"
check_provider_cli "advance orchestrator" "$(provider_from_pair "$ORCHESTRATOR_ADVANCE")"
check_provider_cli "reviewer" "${REVIEW_PROVIDER:-claude}"

if [ -n "${LINEAR_API_KEY:-}" ]; then
  teams="$(python3 "$CADENCE_HOME/engine/linear/cli.py" teams 2>/dev/null)"
  if echo "$teams" | grep -q "\"id\": \"${LINEAR_TEAM_ID:-__none__}\""; then
    pass "Linear API key valid; team ${LINEAR_TEAM_NAME:-?} visible"
  else
    fail "Linear API key invalid OR team ${LINEAR_TEAM_ID:-unset} not in workspace"
  fi
else
  fail "LINEAR_API_KEY not set"
fi

# Required scope ids — blank values silently widen scope or break filters.
if [ -n "${LINEAR_PROJECT_ID:-}" ]; then pass "LINEAR_PROJECT_ID set"; else fail "LINEAR_PROJECT_ID not set (loops would not be project-scoped)"; fi
if [ -n "${LINEAR_ASSIGNEE_ID:-}" ]; then pass "LINEAR_ASSIGNEE_ID set"; else fail "LINEAR_ASSIGNEE_ID not set"; fi

# Paths the build/revise loops need (warn-only: a triage-only setup may skip them).
if [ -n "${PROJECT_DIR:-}" ] && [ -d "$PROJECT_DIR" ]; then pass "PROJECT_DIR exists"
else echo "  ⚠️  PROJECT_DIR unset or missing (spec/build/revise cd here)"; fi
if [ -n "${WORKTREE_BASE:-}" ] && [ -w "$(dirname "$WORKTREE_BASE")" ]; then pass "WORKTREE_BASE parent writable"
else echo "  ⚠️  WORKTREE_BASE unset or parent not writable (build/revise create worktrees here)"; fi

# Worktree tool: git needs nothing extra; grove must be installed when selected.
case "${WORKTREE_TOOL:-git}" in
  git)   pass "worktree tool: git (default)" ;;
  grove) if command -v grove >/dev/null; then pass "worktree tool: grove found"; else fail "WORKTREE_TOOL=grove but grove not on PATH"; fi ;;
  *)     fail "WORKTREE_TOOL='${WORKTREE_TOOL}' invalid (use git or grove)" ;;
esac

# Selected implementer must be runnable on the same runner PATH as the loops.
case "${BUILD_IMPLEMENTER:-claude}" in
  claude|codex|kimi|opencode)
    if (PATH="$RUNNER_PATH"; command -v "${BUILD_IMPLEMENTER:-claude}" >/dev/null); then
      pass "implementer '${BUILD_IMPLEMENTER:-claude}' available"
    else
      fail "implementer '${BUILD_IMPLEMENTER:-claude}' not on PATH"
    fi
    ;;
  *)
    fail "implementer '${BUILD_IMPLEMENTER:-claude}' invalid (use claude, codex, kimi, or opencode)"
    ;;
esac

# Autonomous mode (optional; off unless explicitly enabled). Match config()'s
# case-insensitive truthy set: 1/on/true/yes.
_auto="$(printf '%s' "${AUTONOMOUS:-0}" | tr '[:upper:]' '[:lower:]')"
if [ "$_auto" = "1" ] || [ "$_auto" = "on" ] || [ "$_auto" = "true" ] || [ "$_auto" = "yes" ]; then
  echo "  autonomous: ON  (max ${AUTO_MAX_ISSUES_PER_RUN:-1}/run, ${AUTO_MAX_REPAIRS:-3} repairs)"
else
  echo "  autonomous: off"
fi

if [ -d "$CADENCE_STATE_DIR" ]; then pass "state dir $CADENCE_STATE_DIR"; else fail "state dir missing"; fi

_scheduled="$(printf '%s' "${CADENCE_SCHEDULED:-0}" | tr '[:upper:]' '[:lower:]')"
_scheduler_plist="$HOME/Library/LaunchAgents/com.cadence.scheduler.plist"
if [ -f "$_scheduler_plist" ]; then
  pass "scheduler plist present"
elif [ "$_scheduled" = "1" ] || [ "$_scheduled" = "on" ] || [ "$_scheduled" = "true" ] || [ "$_scheduled" = "yes" ]; then
  echo "  ⚠️  CADENCE_SCHEDULED is on but no scheduler plist (run: cadence schedule apply)"
else
  echo "  schedule: off for this project"
fi

check_labels

echo
[ "$bad" -eq 0 ] && echo "doctor: all critical checks passed ($ok ok)" || echo "doctor: $bad problem(s), $ok ok"
exit "$bad"
