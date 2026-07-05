#!/bin/bash
# Cadence agent loop runner — invoked by the scheduler or manually.
# Usage: run-loop.sh <triage|spec|build|revise|advance|roadmap>
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"
# Optional project tooling on PATH (RUNNER_PATH_PREPEND in .env, e.g. a specific PHP so
# bare php/composer resolve to the project's pinned version); auto-includes Herd's bin if
# present when unset. Generic when neither applies.
_pp="${RUNNER_PATH_PREPEND:-}"
[ -z "$_pp" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _pp="$HOME/Library/Application Support/Herd/bin"
export PATH="${_pp:+$_pp:}$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
STAGE="${1:?stage required (triage|spec|build|revise|advance|roadmap)}"
# Expose the stage to every descendant (the orchestrator and any `cadence tasks
# update` / `cadence linear issue-update` it runs) so the engine can refuse a loop
# that tries to strip a human gate label it does not own.
export CADENCE_STAGE="$STAGE"
# Default so a config that legitimately omits PROJECT_DIR (triage/spec-only setups)
# reaches the `cd "$WORKTREE" || ...` handler below rather than crashing on `set -u`.
WORKTREE="${PROJECT_DIR:-}"
LOGDIR="$CADENCE_STATE_DIR/logs"
RUNS="$CADENCE_STATE_DIR/runs"
mkdir -p "$LOGDIR" "$RUNS"

# --- Crash surfacing ---------------------------------------------------------
# A script error after this point (or any early exit before the normal run
# logging) used to die silently: nothing in the stage log or activity feed,
# evidence only in launchd stderr — so the pipeline looked healthy while dead.
# Record any non-zero exit that never reached its normal logging. Failures
# before this line (e.g. lib-env refusing a bad profile) still surface only on
# stderr.
_CADENCE_DONE=0
# shellcheck disable=SC2329  # invoked via the EXIT trap strings below
_crash_log() {
  local _rc=$?
  [ "$_rc" -eq 0 ] && return 0
  [ "${_CADENCE_DONE:-0}" = 1 ] && return 0
  local _ts
  _ts="$(date -u +%FT%TZ)"
  echo "[$_ts] $STAGE — CRASHED (exit $_rc)" >> "$RUNS/activity.log" 2>/dev/null || true
  echo "[$_ts] cadence $STAGE CRASHED (exit $_rc) — see scheduler/launchd stderr" >> "$LOGDIR/$STAGE.log" 2>/dev/null || true
}
trap _crash_log EXIT

# --- Single-instance lock (macOS has no flock) -------------------------------
# Two code-writing runs must never overlap: they'd work issues concurrently and race
# on the shared worktree pool. build + revise share ONE lock so they are mutually
# exclusive (never the same or different issues at once); triage/spec/advance are
# Linear-only (or gate-only) and just need to be self-exclusive. mkdir is atomic; a
# lock whose holder PID is dead is reclaimed. (The implementer now runs synchronously
# in-turn, so the lock is held for the whole build — overlapping launchd ticks during
# a long build are skipped, not collided.)
case "$STAGE" in
  build|revise) _LOCK=worktree ;;   # mutate worktrees/code → mutually exclusive
  *)            _LOCK="$STAGE" ;;    # triage/spec/advance → only self-exclusive
esac
LOCKDIR="$LOGDIR/$_LOCK.lock.d"
# A lock older than this is treated as abandoned even if its recorded PID is alive
# again (macOS recycles PIDs), matching the 2h agent:claimed reclaim window.
_LOCK_MAX_AGE="${CADENCE_LOCK_MAX_AGE_SECONDS:-7200}"
_lock_alive() {   # true only if the holder PID is live AND the lock is young enough
  local holder now mtime
  holder="$(cat "$LOCKDIR/pid" 2>/dev/null || echo '')"
  [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null || return 1
  now="$(date +%s)"
  mtime="$(stat -f %m "$LOCKDIR/pid" 2>/dev/null || stat -c %Y "$LOCKDIR/pid" 2>/dev/null || echo "$now")"
  [ "$(( now - mtime ))" -lt "$_LOCK_MAX_AGE" ]
}
if mkdir "$LOCKDIR" 2>/dev/null; then
  :   # acquired cleanly
elif _lock_alive; then
  echo "[$(date -u +%FT%TZ)] $STAGE — skipped (run $(cat "$LOCKDIR/pid" 2>/dev/null) already in flight)" >> "$LOGDIR/$STAGE.log"
  exit 0
elif mkdir "$LOCKDIR.reclaim" 2>/dev/null; then
  # Won the right to reclaim a stale lock. Doing rm+mkdir under this second atomic
  # lock stops two racers both recreating LOCKDIR and each thinking they hold it.
  # ponytail: .reclaim is held only across the adjacent rm+mkdir (µs, no I/O); a hard
  # kill in that gap is vanishingly unlikely and an operator clears it like any lock.
  rm -rf "$LOCKDIR"
  mkdir "$LOCKDIR" 2>/dev/null
  rmdir "$LOCKDIR.reclaim" 2>/dev/null || true
  [ -d "$LOCKDIR" ] || { echo "[$(date -u +%FT%TZ)] $STAGE — skipped (lock race)" >> "$LOGDIR/$STAGE.log"; exit 0; }
else
  echo "[$(date -u +%FT%TZ)] $STAGE — skipped (lock reclaim in progress)" >> "$LOGDIR/$STAGE.log"
  exit 0
fi
echo "$$" > "$LOCKDIR/pid"
# Keep a live holder's lock fresh so the 2h reclaim only ever fires on a genuinely
# dead/wedged run — a legitimate build past the max-age must not be stolen mid-flight.
( while :; do sleep 600; touch "$LOCKDIR/pid" 2>/dev/null || exit; done ) >/dev/null 2>&1 &
_HB=$!
# PROMPT_FILE is removed on the normal path too; the trap covers signal interruption
# (SIGTERM mid-orchestrator) so an orphan prompt is never left in $RUNS.
PROMPT_FILE=""
trap '_crash_log; kill "$_HB" 2>/dev/null; rm -f "$PROMPT_FILE"; rm -rf "$LOCKDIR"' EXIT

pause_before_launch() {
  reason="$1"
  detail="$2"
  TS="$(date -u +%FT%TZ)"
  DAY="$(date -u +%F)"
  payload="$(STAGE="$STAGE" TS="$TS" REASON="$reason" DETAIL="$detail" python3 - <<'PY'
import json, os
print(json.dumps({
    "stage": os.environ["STAGE"],
    "ts": os.environ["TS"],
    "paused": True,
    "reason": os.environ["REASON"],
    "detail": os.environ["DETAIL"],
}, separators=(",", ":")))
PY
)"
  echo "[$TS] cadence $STAGE paused — $reason ($detail)" >> "$LOGDIR/$STAGE.log"
  echo "[$TS] $STAGE — PAUSED ($reason: $detail)" >> "$RUNS/activity.log"
  echo "⏸ $STAGE paused — $reason ($detail) · $TS" >> "$RUNS/$DAY.md"
  echo "$payload" >> "$RUNS/runs.jsonl"
  echo "$payload"
  if [ "${NOTIFY:-on}" = "on" ]; then
    osascript -e "display notification \"$reason: $detail\" with title \"$STAGE loop paused\" sound name \"Funk\"" 2>/dev/null || true
  fi
  exit 0
}

idle_before_launch() {
  reason="$1"
  detail="$2"
  TS="$(date -u +%FT%TZ)"
  payload="$(STAGE="$STAGE" TS="$TS" REASON="$reason" DETAIL="$detail" python3 - <<'PY'
import json, os
print(json.dumps({
    "stage": os.environ["STAGE"],
    "ts": os.environ["TS"],
    "dry_run": False,
    "idle": True,
    "reason": os.environ["REASON"],
    "detail": os.environ["DETAIL"],
}, separators=(",", ":")))
PY
)"
  echo "[$TS] cadence $STAGE idle — $reason ($detail)" >> "$LOGDIR/$STAGE.log"
  echo "[$TS] $STAGE — idle ($reason: $detail)" >> "$RUNS/activity.log"
  echo "$payload" >> "$RUNS/runs.jsonl"
  echo "$payload"
  exit 0
}

# Pause and workspace checks are enforced here, not just in the prompt: an
# unsafe system must not pay for a model invocation or run tools before the agent
# honours the flag.
if [ -f "$RUNS/PAUSED" ]; then
  pause_before_launch "manual" "PAUSED present"
fi

_task_backend="$(printf '%s' "${TASK_BACKEND:-linear}" | tr '[:upper:]' '[:lower:]')"
case "$_task_backend" in
  linear)
    if [ -z "${LINEAR_TEAM_ID:-}" ]; then
      pause_before_launch "wrong-workspace" "LINEAR_TEAM_ID unset"
    fi
    teams_json="$(python3 "$CADENCE_HOME/engine/linear/cli.py" teams 2>&1)" || {
      pause_before_launch "wrong-workspace" "cadence linear teams failed"
    }
    if ! TEAM_JSON="$teams_json" TEAM_ID="$LINEAR_TEAM_ID" python3 - <<'PY'
import json, os, sys
try:
    teams = json.loads(os.environ["TEAM_JSON"])
except Exception:
    sys.exit(1)
needle = os.environ["TEAM_ID"]
for team in teams:
    if team.get("id") == needle:
        sys.exit(0)
sys.exit(1)
PY
    then
      pause_before_launch "wrong-workspace" "team $LINEAR_TEAM_ID not visible"
    fi
    ;;
  file)
    _task_file="${TASK_FILE:-cadence/tasks.md}"
    case "$_task_file" in
      /*) : ;;
      *) _task_file="$PROJECT_DIR/$_task_file" ;;
    esac
    if [ ! -f "$_task_file" ]; then
      pause_before_launch "missing-task-file" "$_task_file"
    fi
    TASK_FILE="$_task_file"
    export TASK_FILE
    ;;
  *)
    pause_before_launch "invalid-task-backend" "TASK_BACKEND=${TASK_BACKEND:-} (use linear or file)"
    ;;
esac

# Advance loop is opt-in and must not pay for a model launch when idle.
if [ "$STAGE" = "advance" ]; then
  _auto="$(printf '%s' "${AUTONOMOUS:-0}" | tr '[:upper:]' '[:lower:]')"
  case "$_auto" in
    1|on|true|yes) : ;;
    *) pause_before_launch "autonomous-off" "AUTONOMOUS not enabled" ;;
  esac
  case "$_task_backend" in
    file) _n="$(python3 "$CADENCE_HOME/engine/tasks/cli.py" list --label agent:auto 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)" ;;
    *)    _n="$(python3 "$CADENCE_HOME/engine/linear/cli.py" issues-list --label agent:auto --assignee me --limit 1 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)" ;;
  esac
  [ "$_n" = "0" ] && idle_before_launch "no-auto-work" "no agent:auto issues in scope"
fi

# The roadmap loop is opt-in per project via SCHED_ROADMAP (default off), not via
# a stated goal: a goal only steers it, and its absence is normal (the loop falls
# back to a standing quality rubric). So there is no no-goal idle gate here — a
# scheduled run only fires where the operator enabled the schedule, and a manual
# `run roadmap` is an explicit opt-in by definition.

cd "$WORKTREE" || { echo "project dir missing: $WORKTREE" >&2; exit 1; }

provider_from_pair() {
  pair="$1"
  case "$pair" in
    *:*) printf '%s\n' "${pair%%:*}" ;;
    *) printf '%s\n' "${ORCHESTRATOR_PROVIDER:-claude}" ;;
  esac
}

model_from_pair() {
  pair="$1"
  case "$pair" in
    *:*) printf '%s\n' "${pair#*:}" ;;
    *) printf '%s\n' "$pair" ;;
  esac
}

case "$STAGE" in
  triage)
    MODE=enrich; [ "$(date +%H)" = "07" ] && MODE=full
    CMD_ARGS=("--mode=$MODE" "--since=last-run" "--live"); PAIR="$ORCHESTRATOR_TRIAGE" ;;
  spec)   CMD_ARGS=(); PAIR="$ORCHESTRATOR_SPEC" ;;
  build)  CMD_ARGS=("--implementer=$BUILD_IMPLEMENTER"); PAIR="$ORCHESTRATOR_BUILD" ;;
  revise) CMD_ARGS=(); PAIR="$ORCHESTRATOR_REVISE" ;;
  advance)
    CMD_ARGS=(); [ "${2:-}" = "--dry-run" ] && CMD_ARGS=("--dry-run")
    PAIR="$ORCHESTRATOR_ADVANCE" ;;
  roadmap)
    CMD_ARGS=(); [ "${2:-}" = "--dry-run" ] && CMD_ARGS=("--dry-run")
    PAIR="$ORCHESTRATOR_ROADMAP" ;;
  *) echo "unknown stage: $STAGE" >&2; exit 2 ;;
esac
PROVIDER="$(provider_from_pair "$PAIR")"
MODEL="$(model_from_pair "$PAIR")"

# Housekeeping: before a build/revise launch, remove clean worktrees whose branch
# is fully merged into origin/<base> (their PR landed) so they don't pile up.
if [ "$STAGE" = "build" ] || [ "$STAGE" = "revise" ]; then
  "$DIR/worktree.sh" cleanup "${BASE_BRANCH:-develop}" 2>/dev/null \
    | while IFS= read -r _br; do
        echo "[$(date -u +%FT%TZ)] $STAGE — pruned merged worktree $_br" >> "$LOGDIR/$STAGE.log"
      done
fi

LOG="$LOGDIR/$STAGE.log"
_LOG_START=$(wc -c < "$LOG" 2>/dev/null || echo 0)   # scan only THIS run's output for a summary
PROMPT_FILE="$RUNS/prompt-$STAGE-$(date -u +%Y%m%dT%H%M%SZ)-$$.md"
# ${arr[@]+…} guard: macOS /bin/bash 3.2 treats an empty array as unbound under set -u
python3 "$CADENCE_HOME/engine/prompts/render.py" "$STAGE" ${CMD_ARGS[@]+"${CMD_ARGS[@]}"} --output "$PROMPT_FILE" >> "$LOG" 2>&1
RC=$?
if [ "$RC" -ne 0 ]; then
  echo "[$(date -u +%FT%TZ)] failed to render cadence $STAGE prompt (exit $RC)" >> "$LOG"
else
  echo "[$(date -u +%FT%TZ)] starting cadence $STAGE ($PROVIDER:$MODEL): ${CMD_ARGS[*]:-(none)}" >> "$LOG"
  "$DIR/run-orchestrator.sh" "$PROVIDER" "$MODEL" "$WORKTREE" "$PROMPT_FILE" "$STAGE" >> "$LOG" 2>&1
  RC=$?
fi
echo "[$(date -u +%FT%TZ)] finished cadence $STAGE (exit $RC)" >> "$LOG"
rm -f "$PROMPT_FILE"

# --- Informative + surfaceable: one-line summary → activity feed → push on activity ---
# Parse this run's JSON summary (triage uses "stage", others use "loop"), build a plain
# one-liner, append it to a single chronological activity feed, and fire a macOS
# notification only when a LIVE run actually did something (or paused / errored).
SUM=$(python3 - "$STAGE" "$LOG" "$RC" "$_LOG_START" <<'PY'
import sys, json
stage, logpath, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
try:
    start = int(sys.argv[4])
except (IndexError, ValueError):
    start = 0
MARKER = 'CADENCE_SUMMARY '   # skills print the summary on its own marked line
last = None
read_err = None
try:
    with open(logpath, 'rb') as f:
        f.seek(start)          # skip prior runs' output so a no-summary run isn't
        chunk = f.read()       # mislabelled with the previous run's stale counts
    lines = chunk.decode('utf-8', 'replace').splitlines()
    # Prefer the explicit marker (robust against prose around the JSON); fall back
    # to the bare-JSON heuristic for older skill output.
    for line in lines:
        s = line.strip()
        if s.startswith(MARKER):
            try: d = json.loads(s[len(MARKER):].strip())
            except Exception: continue
            # The marker is authoritative for this run's own stdout, so accept it
            # even when the summary carries no stage/loop key (triage uses 'mode').
            # Only reject a marker that explicitly names a different stage.
            st, lp = d.get('stage'), d.get('loop')
            if (st is None and lp is None) or st == stage or lp == stage:
                last = d
    if last is None:
        for line in lines:
            s = line.strip()
            if s.startswith('{') and ('"stage"' in s or '"loop"' in s):
                try: d = json.loads(s)
                except Exception: continue
                if d.get('stage') == stage or d.get('loop') == stage:
                    last = d
except Exception as e:
    read_err = str(e)
if last is None:
    # A log-read failure is itself a failure to surface, not something to swallow.
    if read_err is not None:
        print(f"2|FAILED — could not read log: {read_err}")
    elif rc != 0:
        print(f"2|FAILED — exit {rc}, no summary")
    else:
        # Exit 0 but nothing parseable = a silently-degraded run. Flag 1 (notable)
        # so the lost activity surfaces in the feed rather than passing as quiet.
        print(f"1|exit {rc}, no summary")
    sys.exit()
d = last
if d.get('paused'):
    print(f"1|PAUSED — {d.get('reason','?')}"); sys.exit()
dry = bool(d.get('dry_run'))
err = int(d.get('errors', 0) or 0)
parts = []
def add(k, label):
    v = d.get(k, 0) or 0
    if v: parts.append(f"{v} {label}")
if stage == 'triage':
    for k, l in [('triaged','triaged'),('cycled','cycled'),('labelled','labelled'),
                 ('stubbed','AC-stubbed'),('dupe_candidates','dupe-flagged'),
                 ('stale','stale'),('backfilled','back-filled'),('parked','parked')]:
        add(k, l)
elif stage == 'spec':
    add('specced', 'specced'); add('superseded', 'superseded')
elif stage == 'build':
    b = int(d.get('built', 0) or 0)
    if b: parts.append(f"{b} built")
    prs = d.get('pr_numbers') or []
    if prs: parts.append("draft PR " + ", ".join(f"#{p}" for p in prs))
elif stage == 'revise':
    add('revised', 'revised')
elif stage == 'advance':
    for k, l in [('advanced','advanced'),('accepted','accepted'),
                 ('repaired','repaired'),('escalated','escalated')]:
        add(k, l)
elif stage == 'roadmap':
    add('proposed', 'proposed')
body = ", ".join(parts) if parts else "nothing to do"
prefix = ("LIVE " if not dry else "dry ")
if err: body += f" · {err} ERROR(S)"
if rc != 0: body += f" · exit {rc}"
your_move = stage in ('spec', 'build', 'revise', 'roadmap') and bool(parts)
failed = rc != 0 or err > 0
# 2 = failure (alert), 1 = notable activity (your move), 0 = quiet
flag = 2 if failed else (1 if ((not dry and parts) or your_move) else 0)
print(f"{flag}|{prefix}{body}")
PY
)
FLAG="${SUM%%|*}"; MSG="${SUM#*|}"
mkdir -p "$RUNS"
echo "[$(date -u +%FT%TZ)] $STAGE — $MSG" >> "$RUNS/activity.log"
# A failed run (non-zero exit or reported errors) is also recorded in the dated
# digest, so the failure survives in the human record — not just a transient alert.
[ "$FLAG" = "2" ] && echo "❌ $STAGE — $MSG · $(date -u +%FT%TZ)" >> "$RUNS/$(date -u +%F).md"
if [ "$FLAG" != "0" ] && [ "$NOTIFY" = "on" ]; then
  if [ "$FLAG" = "2" ]; then
    TITLE="Cadence $STAGE — FAILED"; SOUND="Basso"
  else
    TITLE="Cadence $STAGE"; SOUND="Glass"
    case "$STAGE" in spec) TITLE="Cadence spec — your move";; build) TITLE="Cadence build — review PR";; revise) TITLE="Cadence revise — re-review";; roadmap) TITLE="Cadence roadmap — review proposals";; esac
  fi
  osascript -e "display notification \"$MSG\" with title \"$TITLE\" sound name \"$SOUND\"" 2>/dev/null || true
fi
_CADENCE_DONE=1   # run reached its normal logging; a non-zero RC here is already surfaced
exit $RC
