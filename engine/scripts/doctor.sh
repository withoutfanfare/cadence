#!/usr/bin/env bash
# cadence doctor — verify a setup without changing anything.
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"

ok=0; bad=0
pass(){ echo "  ✅ $1"; ok=$((ok+1)); }
fail(){ echo "  ❌ $1"; bad=$((bad+1)); }

echo "── cadence doctor ────────────────────────────────"
if [ -f "$CADENCE_HOME/.env" ]; then pass ".env present"; else fail ".env missing (copy .env.example)"; fi
if command -v claude >/dev/null; then pass "claude found"; else fail "claude not on PATH"; fi
if command -v python3 >/dev/null; then pass "python3 found"; else fail "python3 not on PATH"; fi
if command -v gh >/dev/null; then pass "gh found"; else echo "  ⚠️  gh not found (build PR back-fill needs it)"; fi

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

# Selected implementer must be runnable when it isn't the bundled `claude`.
if [ "${BUILD_IMPLEMENTER:-claude}" = "claude" ] || command -v "${BUILD_IMPLEMENTER}" >/dev/null; then
  pass "implementer '${BUILD_IMPLEMENTER:-claude}' available"
else
  fail "implementer '${BUILD_IMPLEMENTER}' not on PATH"
fi

# Autonomous mode (optional; off unless explicitly enabled). Match config()'s
# case-insensitive truthy set: 1/on/true/yes.
_auto="$(printf '%s' "${AUTONOMOUS:-0}" | tr '[:upper:]' '[:lower:]')"
if [ "$_auto" = "1" ] || [ "$_auto" = "on" ] || [ "$_auto" = "true" ] || [ "$_auto" = "yes" ]; then
  echo "  autonomous: ON  (max ${AUTO_MAX_ISSUES_PER_RUN:-1}/run, ${AUTO_MAX_REPAIRS:-3} repairs)"
else
  echo "  autonomous: off"
fi

if [ -d "$CADENCE_STATE_DIR" ]; then pass "state dir $CADENCE_STATE_DIR"; else fail "state dir missing"; fi

for s in triage spec build revise; do
  p="$HOME/Library/LaunchAgents/com.cadence.loop-$s.plist"
  [ -f "$p" ] && pass "schedule loop-$s present" || echo "  ⚠️  no plist for loop-$s (schedule this loop when ready)"
done

# Autonomous jobs exist only after 'cadence autonomous on'. Warn if the mode is on
# but the jobs were never scheduled (the flag alone schedules nothing).
if [ "$_auto" = "1" ] || [ "$_auto" = "on" ] || [ "$_auto" = "true" ] || [ "$_auto" = "yes" ]; then
  [ -f "$HOME/Library/LaunchAgents/com.cadence.loop-advance.plist" ] && pass "schedule advance present" || echo "  ⚠️  autonomous on but no advance plist (run: cadence autonomous on)"
  [ -f "$HOME/Library/LaunchAgents/com.cadence.conduct.plist" ] && pass "schedule conduct present" || echo "  ⚠️  autonomous on but no conduct plist (run: cadence autonomous on)"
fi

echo
[ "$bad" -eq 0 ] && echo "doctor: all critical checks passed ($ok ok)" || echo "doctor: $bad problem(s), $ok ok"
exit "$bad"
