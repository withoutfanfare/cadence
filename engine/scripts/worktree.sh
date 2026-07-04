#!/usr/bin/env bash
# worktree.sh — create/remove the isolated build worktree, abstracting the tool.
# WORKTREE_TOOL=git (default, portable) | grove (the author's Laravel Herd sites).
# Verbs:
#   add <branch> [base]   ensure a worktree for <branch> off [base|BASE_BRANCH]; print its path
#   remove <branch>       remove the worktree and delete its branch
#   path <branch>         print the worktree path (no side effects)
# Paths come from .env (PROJECT_DIR, WORKTREE_BASE, BASE_BRANCH, WORKTREE_TOOL).
# WORKTREE_REPO overrides the grove repo name when it differs from the project
# directory's basename (e.g. a `stuntrocketv3` worktree off a `stuntrocket` repo).
# `add` prints ONLY the worktree path on stdout; all tool chatter goes to stderr,
# so callers can do:  WT="$(cadence worktree add stu-1799 develop)"; cd "$WT"
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"   # PROJECT_DIR, WORKTREE_BASE, BASE_BRANCH, WORKTREE_TOOL

verb="${1:?verb: add|remove|path}"
branch="${2:?branch}"
base="${3:-$BASE_BRANCH}"

: "${PROJECT_DIR:?PROJECT_DIR not set in .env}"
: "${WORKTREE_BASE:?WORKTREE_BASE not set in .env}"
WT="$WORKTREE_BASE/$branch"
# The grove repo name. Defaults to the project dir's basename, but a project
# whose directory differs from its bare repo (grove `repos` name) sets
# WORKTREE_REPO. Only grove uses this; the git backend works off PROJECT_DIR.
SITE="${WORKTREE_REPO:-$(basename "$PROJECT_DIR")}"
tool="${WORKTREE_TOOL:-git}"

case "$tool" in
  git|grove) ;;
  *) echo "worktree: unknown WORKTREE_TOOL '$tool' (use git or grove)" >&2; exit 2 ;;
esac

assert_worktree_dir() {
  git -C "$WT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || { echo "worktree: existing directory is not a git worktree: $WT" >&2; exit 1; }
}

case "$verb" in
  path) echo "$WT" ;;

  add)
    # Idempotent: an existing worktree dir is re-used (revise re-runs the same branch).
    if [ -d "$WT" ]; then assert_worktree_dir; echo "$WT"; exit 0; fi
    case "$tool" in
      grove)
        grove add "$SITE" "$branch" "$base" -f 1>&2 \
          || { echo "worktree: 'grove add' failed" >&2; exit 1; }
        ;;
      git)
        mkdir -p "$(dirname "$WT")"
        if git -C "$PROJECT_DIR" show-ref --verify --quiet "refs/heads/$branch"; then
          # Existing local branch — the normal build→revise case on the same machine.
          git -C "$PROJECT_DIR" worktree add "$WT" "$branch" 1>&2 \
            || { echo "worktree: 'git worktree add' (existing branch) failed" >&2; exit 1; }
        else
          # No local branch. Recover the PR branch from origin if it exists (revise
          # after a cleaned-up worktree, so we don't silently re-base off develop and
          # lose the PR commits); otherwise branch off base for a fresh build.
          git -C "$PROJECT_DIR" fetch --quiet origin \
            "+refs/heads/$branch:refs/remotes/origin/$branch" 2>/dev/null || true
          if git -C "$PROJECT_DIR" rev-parse --verify --quiet "refs/remotes/origin/$branch" >/dev/null; then
            start="origin/$branch"
          else
            start="$base"
          fi
          git -C "$PROJECT_DIR" worktree add "$WT" -b "$branch" "$start" 1>&2 \
            || { echo "worktree: 'git worktree add' (new branch off $start) failed" >&2; exit 1; }
        fi
        ;;
    esac
    [ -d "$WT" ] || { echo "worktree: expected $WT after add" >&2; exit 1; }
    echo "$WT"
    ;;

  remove)
    case "$tool" in
      grove)
        grove rm "$SITE" "$branch" -f --no-backup --delete-branch >/dev/null 2>&1 || true
        ;;
      git)
        git -C "$PROJECT_DIR" worktree remove --force "$WT" >/dev/null 2>&1 || true
        git -C "$PROJECT_DIR" branch -D "$branch"            >/dev/null 2>&1 || true
        git -C "$PROJECT_DIR" worktree prune                 >/dev/null 2>&1 || true
        ;;
    esac
    ;;

  *) echo "worktree: verb must be add|remove|path" >&2; exit 2 ;;
esac
