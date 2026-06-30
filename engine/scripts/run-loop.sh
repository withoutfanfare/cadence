#!/bin/bash
# Cadence agent loop runner — invoked by launchd (com.cadence.loop-<stage>).
# Usage: run-loop.sh <triage|spec|build|revise>
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
STAGE="${1:?stage required (triage|spec|build|revise)}"
WORKTREE="$PROJECT_DIR"
LOGDIR="$CADENCE_STATE_DIR/logs"
RUNS="$CADENCE_STATE_DIR/runs"
mkdir -p "$LOGDIR" "$RUNS"

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
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  _holder="$(cat "$LOCKDIR/pid" 2>/dev/null || echo '')"
  if [ -n "$_holder" ] && kill -0 "$_holder" 2>/dev/null; then
    echo "[$(date -u +%FT%TZ)] $STAGE — skipped (run $_holder already in flight)" >> "$LOGDIR/$STAGE.log"
    exit 0
  fi
  rm -rf "$LOCKDIR"   # stale lock — holder is dead
  mkdir "$LOCKDIR" 2>/dev/null || { echo "[$(date -u +%FT%TZ)] $STAGE — skipped (lock race)" >> "$LOGDIR/$STAGE.log"; exit 0; }
fi
echo "$$" > "$LOCKDIR/pid"
trap 'rm -rf "$LOCKDIR"' EXIT

pause_before_launch() {
  reason="$1"
  detail="$2"
  TS="$(date -u +%FT%TZ)"
  DAY="$(date -u +%F)"
  payload="$(STAGE="$STAGE" REASON="$reason" DETAIL="$detail" python3 - <<'PY'
import json, os
print(json.dumps({
    "stage": os.environ["STAGE"],
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
  payload="$(STAGE="$STAGE" REASON="$reason" DETAIL="$detail" python3 - <<'PY'
import json, os
print(json.dumps({
    "stage": os.environ["STAGE"],
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

# Advance loop is opt-in and must not pay for a model launch when idle.
if [ "$STAGE" = "advance" ]; then
  _auto="$(printf '%s' "${AUTONOMOUS:-0}" | tr '[:upper:]' '[:lower:]')"
  case "$_auto" in
    1|on|true|yes) : ;;
    *) pause_before_launch "autonomous-off" "AUTONOMOUS not enabled" ;;
  esac
  _n="$(python3 "$CADENCE_HOME/engine/linear/cli.py" issues-list --label agent:auto --assignee me 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
  [ "$_n" = "0" ] && idle_before_launch "no-auto-work" "no agent:auto issues in scope"
fi

cd "$WORKTREE" || { echo "project dir missing: $WORKTREE" >&2; exit 1; }

case "$STAGE" in
  triage)
    MODE=enrich; [ "$(date +%H)" = "07" ] && MODE=full
    CMD="/cadence-loop-triage --mode=$MODE --since=last-run --live"; MODEL="$MODEL_TRIAGE" ;;
  spec)   CMD="/cadence-loop-spec";   MODEL="$MODEL_SPEC" ;;
  build)  CMD="/cadence-loop-build --implementer=$BUILD_IMPLEMENTER"; MODEL="$MODEL_BUILD" ;;
  revise) CMD="/cadence-loop-revise"; MODEL="$MODEL_REVISE" ;;
  advance)
    DRY=""; [ "${2:-}" = "--dry-run" ] && DRY=" --dry-run"
    CMD="/cadence-loop-advance${DRY}"; MODEL="${MODEL_ADVANCE:-sonnet}" ;;
  *) echo "unknown stage: $STAGE" >&2; exit 2 ;;
esac

# Housekeeping: before a build/revise launch, remove worktrees whose branch is fully
# merged into origin/<base> (their PR landed) so they don't pile up. Conservative —
# never touches the base worktree, a fresh/unbuilt branch (tip == base), or one with
# local changes; only one loop runs at a time (lock above), so no concurrent worktree ops.
if [ "$STAGE" = "build" ] || [ "$STAGE" = "revise" ]; then
  if [ -n "${WORKTREE_BASE:-}" ] && [ -d "$WORKTREE_BASE" ] \
     && git -C "$PROJECT_DIR" fetch --quiet origin "${BASE_BRANCH:-develop}" 2>/dev/null; then
    _base="${BASE_BRANCH:-develop}"
    _basetip="$(git -C "$PROJECT_DIR" rev-parse "origin/$_base" 2>/dev/null || echo)"
    for _wt in "$WORKTREE_BASE"/*/; do
      _wt="${_wt%/}"
      [ "$_wt" = "$PROJECT_DIR" ] && continue
      _br="$(git -C "$_wt" symbolic-ref --quiet --short HEAD 2>/dev/null)" || continue
      [ "$_br" = "$_base" ] && continue
      _tip="$(git -C "$_wt" rev-parse HEAD 2>/dev/null)" || continue
      [ "$_tip" = "$_basetip" ] && continue                                            # fresh/unbuilt — leave
      if ! git -C "$_wt" diff --quiet 2>/dev/null \
         || ! git -C "$_wt" diff --cached --quiet 2>/dev/null; then
        continue  # dirty — leave
      fi
      git -C "$PROJECT_DIR" merge-base --is-ancestor "$_tip" "origin/$_base" 2>/dev/null || continue          # unmerged — leave
      # Remove via the engine's tool-aware verb (grove rm under WORKTREE_TOOL=grove —
      # which also unregisters the Herd site + deletes the branch; plain git otherwise).
      "$DIR/worktree.sh" remove "$_br" >/dev/null 2>&1 \
        && echo "[$(date -u +%FT%TZ)] $STAGE — pruned merged worktree $_br" >> "$LOGDIR/$STAGE.log"
    done
    git -C "$PROJECT_DIR" worktree prune 2>/dev/null || true
  fi
fi

LOG="$LOGDIR/$STAGE.log"
# Unattended: bypass interactive permission prompts. Safety comes from the loops'
# own guardrails (workspace guard, scope filters, draft-only PRs, human gates) — not
# from the permission layer. Runs as you, on your repo.
echo "[$(date -u +%FT%TZ)] starting cadence $STAGE ($MODEL): $CMD" >> "$LOG"
claude -p "$CMD" --model "$MODEL" --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
echo "[$(date -u +%FT%TZ)] finished cadence $STAGE (exit $RC)" >> "$LOG"

# --- Informative + surfaceable: one-line summary → activity feed → push on activity ---
# Parse this run's JSON summary (triage uses "stage", others use "loop"), build a plain
# one-liner, append it to a single chronological activity feed, and fire a macOS
# notification only when a LIVE run actually did something (or paused / errored).
SUM=$(python3 - "$STAGE" "$LOG" "$RC" <<'PY'
import sys, json
stage, logpath, rc = sys.argv[1], sys.argv[2], int(sys.argv[3])
last = None
try:
    for line in open(logpath, encoding='utf-8', errors='replace'):
        s = line.strip()
        if s.startswith('{') and ('"stage"' in s or '"loop"' in s):
            try: d = json.loads(s)
            except Exception: continue
            if d.get('stage') == stage or d.get('loop') == stage:
                last = d
except Exception:
    pass
if last is None:
    # No parseable summary. A non-zero exit means the loop crashed — alert (flag 2).
    if rc != 0:
        print(f"2|FAILED — exit {rc}, no summary")
    else:
        print(f"0|exit {rc}, no summary")
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
body = ", ".join(parts) if parts else "nothing to do"
prefix = ("LIVE " if not dry else "dry ")
if err: body += f" · {err} ERROR(S)"
if rc != 0: body += f" · exit {rc}"
your_move = stage in ('spec', 'build', 'revise') and bool(parts)
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
    case "$STAGE" in spec) TITLE="Cadence spec — your move";; build) TITLE="Cadence build — review PR";; revise) TITLE="Cadence revise — re-review";; esac
  fi
  osascript -e "display notification \"$MSG\" with title \"$TITLE\" sound name \"$SOUND\"" 2>/dev/null || true
fi
exit $RC
