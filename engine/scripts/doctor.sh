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

model_from_pair() {
  pair="$1"
  case "$pair" in
    *:*) printf '%s' "${pair#*:}" ;;
    *) printf '%s' "$pair" ;;
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

# A provider CLI being on PATH does not mean the configured MODEL exists — e.g.
# `kimi:k2` passes the CLI check but fails at run time because kimi has no `k2`
# model. Validate what we cheaply can (kimi's config.toml lists its models); for
# other providers, surface the resolved model so a wrong name is at least visible.
check_model() {
  label="$1"; pair="$2"
  provider="$(provider_from_pair "$pair")"
  model="$(model_from_pair "$pair")"
  if [ "$provider" = "kimi" ]; then
    kimi_cfg="$HOME/.kimi-code/config.toml"
    if [ ! -f "$kimi_cfg" ]; then
      echo "  ⚠️  $label model '$model': kimi config.toml not found, cannot validate"
    elif grep -qF "[models.\"$model\"]" "$kimi_cfg" || grep -qF "[models.$model]" "$kimi_cfg"; then
      pass "$label model '$model' configured in kimi"
    else
      fail "$label model '$model' not configured in kimi (~/.kimi-code/config.toml has no [models.\"$model\"] — fix the model name)"
    fi
  else
    echo "  •  $label model: $provider:$model"
  fi
}

# Gate commands are per-project shell commands the build/revise loops run (blank =
# skip, which is valid). A gate pointing at a tool this project lacks — a Composer
# gate on a Node repo, say — otherwise only fails mid-build, days later. We can't
# verify a subcommand without running the gate (unsafe, and tool-specific), so:
# hard-fail when the leading executable is missing, and otherwise print the full
# command so a human eyeballing doctor spots a wrong-toolchain gate (composer on a
# Python repo) even when the binary happens to be installed.
# ponytail: no per-tool subcommand probe — `composer test:filter` with composer
# installed is shown, not failed; add a probe only if that class of mistake bites.
check_gate() {
  label="$1"; cmd="$2"
  if [ -z "$cmd" ]; then echo "  •  $label: blank (skipped)"; return; fi
  # Gates are sourced shell, so quoted values are valid (`FOO="a b" tool --all`).
  # Let shlex tokenise honouring quotes, then skip leading VAR=value env
  # assignments — `CI=1 composer test` runs `composer`, so that is what to probe.
  # Prints empty on a parse error (unbalanced quotes).
  exe="$(CADENCE_GATE="$cmd" python3 - <<'PY'
import os, shlex
try:
    toks = shlex.split(os.environ["CADENCE_GATE"])
except ValueError:
    toks = []
for t in toks:
    if "=" in t and t.split("=", 1)[0].isidentifier():
        continue
    print(t)
    break
PY
)"
  if [ -z "$exe" ]; then
    fail "$label '$cmd' — could not parse a command to check (unbalanced quotes?)"
    return
  fi
  # Path-form gates (`./vendor/bin/pint`, `bin/test`) resolve relative to where the
  # gate runs (PROJECT_DIR), not doctor's cwd; only bare names go through PATH.
  case "$exe" in
    /*)  probe="$exe" ;;
    */*) probe="${PROJECT_DIR:-$PWD}/$exe" ;;
    *)   probe="" ;;
  esac
  if [ -n "$probe" ]; then
    if [ -x "$probe" ]; then echo "  •  $label: $cmd"
    else fail "$label '$cmd' — '$exe' not executable at $probe (stale gate? fix the command or blank it)"; fi
  elif (PATH="$RUNNER_PATH"; command -v "$exe" >/dev/null 2>&1); then
    echo "  •  $label: $cmd"
  else
    fail "$label '$cmd' — '$exe' not on PATH (stale gate? fix the command or blank it)"
  fi
}

labels_only=0
case "${1:-}" in
  --labels) labels_only=1 ;;
  "") ;;
  *) echo "usage: cadence doctor [--labels]" >&2; exit 2 ;;
esac

task_backend="$(printf '%s' "${TASK_BACKEND:-linear}" | tr '[:upper:]' '[:lower:]')"

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
  if [ "$task_backend" != "linear" ]; then
    echo "  doctor --labels skipped (TASK_BACKEND=$task_backend)"
    exit 0
  fi
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

# Model-name validation (not just CLI presence) for each configured role.
check_model "triage orchestrator" "$ORCHESTRATOR_TRIAGE"
check_model "spec orchestrator" "$ORCHESTRATOR_SPEC"
check_model "build orchestrator" "$ORCHESTRATOR_BUILD"
check_model "revise orchestrator" "$ORCHESTRATOR_REVISE"
check_model "advance orchestrator" "$ORCHESTRATOR_ADVANCE"
check_model "reviewer" "${REVIEW_PROVIDER:-claude}:${REVIEW_MODEL:-opus}"

case "$task_backend" in
  linear)
    pass "task backend linear"
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
    ;;
  file)
    _task_file="${TASK_FILE:-cadence/tasks.md}"
    case "$_task_file" in
      /*) : ;;
      *) _task_file="${PROJECT_DIR:-$PWD}/$_task_file" ;;
    esac
    if [ -f "$_task_file" ]; then
      _task_problems="$(TASK_FILE="$_task_file" python3 "$CADENCE_HOME/engine/tasks/cli.py" validate 2>&1)"
      _task_rc=$?
      if [ "$_task_rc" -eq 0 ]; then
        pass "task backend file; task file $_task_file"
      elif [ "$_task_rc" -eq 1 ]; then
        fail "task file $_task_file has format problems:"
        printf '%s\n' "$_task_problems" | sed 's/^/      /'
      else
        fail "could not run task-file validator (exit $_task_rc):"
        printf '%s\n' "$_task_problems" | sed 's/^/      /'
      fi
    else
      fail "TASK_BACKEND=file but task file missing: $_task_file"
    fi
    echo "  task backend: local file (no Linear credential check)"
    ;;
  *)
    fail "TASK_BACKEND='${TASK_BACKEND:-}' invalid (use linear or file)"
    ;;
esac

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

# Configured gate commands (build/revise run these; blank = skip). Catch a stale
# gate now rather than when a build aborts on it days later.
check_gate "GATE_LINT" "${GATE_LINT:-}"
check_gate "GATE_ANALYSE" "${GATE_ANALYSE:-}"
check_gate "GATE_TEST" "${GATE_TEST:-}"

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

if [ "$task_backend" = "linear" ]; then
  check_labels
else
  echo "  Linear label check skipped for TASK_BACKEND=$task_backend"
fi

echo
[ "$bad" -eq 0 ] && echo "doctor: all critical checks passed ($ok ok)" || echo "doctor: $bad problem(s), $ok ok"
exit "$bad"
