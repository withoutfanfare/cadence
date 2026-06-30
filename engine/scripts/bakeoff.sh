#!/bin/bash
# bakeoff.sh — run the same brief through each implementer in its own worktree,
# run the configured test gate, tabulate a comparison. All paths come from .env.
# Worktrees go through `cadence worktree` (git by default; grove when WORKTREE_TOOL=grove).
# Usage: bakeoff.sh <brief-file> <test-filter> ["impl1 impl2 ..."]
set -u
SELF="$0"; DIR="$(cd "$(dirname "$SELF")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"   # CADENCE_HOME, PROJECT_DIR, WORKTREE_BASE, GATE_TEST, …

# Self-sufficient PATH: optional project tooling prefix (RUNNER_PATH_PREPEND, e.g. a
# specific PHP) + the kimi vendor bin, then the usual dirs.
_prefix="${RUNNER_PATH_PREPEND:-}"
[ -z "$_prefix" ] && [ -d "$HOME/Library/Application Support/Herd/bin" ] && _prefix="$HOME/Library/Application Support/Herd/bin"
export PATH="${_prefix:+$_prefix:}$HOME/.kimi-code/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

HELPER="$CADENCE_HOME/engine/scripts/run-implementer.sh"
CADENCE="$CADENCE_HOME/bin/cadence"
MAIN="$PROJECT_DIR"
BRIEF="${1:?brief file}"
FILTER="${2:?test filter, e.g. MoneyTest}"
IMPLS="${3:-claude kimi opencode codex}"
OUT="$CADENCE_STATE_DIR/runs/implementer-bakeoff.md"
LOGD="$CADENCE_STATE_DIR/bakeoff"; mkdir -p "$LOGD" "$(dirname "$OUT")"; rm -f "$LOGD/_done"

{ echo "# Implementer bake-off — $(date -u +%FT%TZ)"
  echo
  echo "Brief: \`$(basename "$BRIEF")\` · gate: \`${GATE_TEST:-(none)} $FILTER\` · implementers: $IMPLS"
  echo
  echo "| implementer | impl exit | gate | files | +lines | secs | Opus review issues |"
  echo "|---|---|---|---|---|---|---|"; } > "$OUT"

read -ra _impls <<< "$IMPLS"
for impl in "${_impls[@]}"; do
  br="baketest-$impl"
  echo "===== $impl =====" >> "$LOGD/$impl.log"
  "$CADENCE" worktree remove "$br" >/dev/null 2>&1 || true
  git -C "$MAIN" push origin --delete "$br" >/dev/null 2>&1 || true
  WT="$("$CADENCE" worktree add "$br" "$BASE_BRANCH" 2>>"$LOGD/$impl.log")"
  if [ -z "$WT" ] || [ ! -d "$WT" ]; then echo "| $impl | worktree-add-failed | — | — | — | — | — |" >> "$OUT"; continue; fi

  # Baseline-commit the worktree tool's own setup changes (grove's ai-files hook may
  # rsync project docs over the worktree) so the diff/review reflects ONLY the implementer.
  git -C "$WT" add -A >/dev/null 2>&1
  git -C "$WT" -c user.email=bake@local -c user.name=bakeoff commit -qm "bakeoff baseline" --no-verify >/dev/null 2>&1 || true

  cp "$BRIEF" "$WT/IMPLEMENT.md"
  start=$(date +%s)
  IMPL_TIMEOUT=900 "$HELPER" "$impl" "$WT" "$WT/IMPLEMENT.md" >> "$LOGD/$impl.log" 2>&1
  rc=$?
  secs=$(( $(date +%s) - start ))

  ( cd "$WT" || exit 1
    if [ -n "${GATE_TEST:-}" ] && bash -c "$GATE_TEST \"$FILTER\"" >> "$LOGD/$impl.log" 2>&1; then gate="✅ PASS"; else gate="${GATE_TEST:+❌ FAIL}"; gate="${gate:-—}"; fi
    git add -A -- . ':(exclude)IMPLEMENT.md' >/dev/null 2>&1
    files=$(git diff --cached --numstat 2>/dev/null | grep -c .)
    add=$(git diff --cached --numstat 2>/dev/null | awk '{s+=$1} END{print s+0}')
    review_log="$LOGD/$impl.review.log"
    claude -p "Run \`git diff --cached\` and adversarially review ONLY that diff against this brief: $(tr '\n' ' ' < IMPLEMENT.md). Judge correctness, scope creep (any file/change not asked for), and whether the test genuinely guards the change. End your reply with a final line exactly: REVIEW_ISSUES=<integer> (count of real issues you would block or require fixing)." \
            --model opus --dangerously-skip-permissions > "$review_log" 2>&1
    cat "$review_log" >> "$LOGD/$impl.log"
    rev=$(grep -oE 'REVIEW_ISSUES=[0-9]+' "$review_log" | tail -1 | cut -d= -f2)
    echo "| $impl | $rc | $gate | $files | $add | ${secs}s | ${rev:-?} |" >> "$OUT" )

  "$CADENCE" worktree remove "$br" >> "$LOGD/$impl.log" 2>&1
  git -C "$MAIN" push origin --delete "$br" >/dev/null 2>&1 || true
done

echo >> "$OUT"
echo "_Per-implementer logs: $LOGD/<impl>.log_" >> "$OUT"
touch "$LOGD/_done"
echo "bakeoff complete → $OUT"
