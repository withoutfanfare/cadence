#!/usr/bin/env bash
# worktree.sh — create/remove the isolated build worktree, abstracting the tool.
# WORKTREE_TOOL=git (default, portable) | grove (the author's Laravel Herd sites).
# Verbs:
#   add <branch> [base]   ensure a worktree for <branch> off [base|BASE_BRANCH]; print its path
#   remove <branch>       remove the worktree and delete its branch
#   path <branch>         print the worktree path (no side effects)
#   merged <branch> [base] true if the worktree is clean and merged into origin/<base>
#   cleanup [base]        remove clean worktrees already merged into origin/<base>
# Paths come from .env (PROJECT_DIR, WORKTREE_BASE, BASE_BRANCH, WORKTREE_TOOL).
# WORKTREE_REPO overrides the grove repo name when it differs from the project
# directory's basename (e.g. a `stuntrocketv3` worktree off a `stuntrocket` repo).
# `add` prints ONLY the worktree path on stdout; all tool chatter goes to stderr,
# so callers can do:  WT="$(cadence worktree add stu-1799 develop)"; cd "$WT"
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/../lib/lib-env.sh"   # PROJECT_DIR, WORKTREE_BASE, BASE_BRANCH, WORKTREE_TOOL

verb="${1:?verb: add|remove|path|merged|cleanup}"
branch="${2:-}"
if [ "$verb" = "cleanup" ]; then
  base="${2:-$BASE_BRANCH}"
  branch=""
else
  [ -n "$branch" ] || { echo "worktree: $verb needs a branch" >&2; exit 2; }
  base="${3:-$BASE_BRANCH}"
fi

# Branch names become path components under WORKTREE_BASE; a `..` segment (or an
# absolute/option-like name) would compute a $WT outside the pool — up to and
# including the main checkout — so reject it before any path is built.
if [ -n "$branch" ]; then
  case "/$branch/" in
    *"/../"*) echo "worktree: branch must not contain '..' segments: $branch" >&2; exit 2 ;;
  esac
  case "$branch" in
    /*|-*) echo "worktree: invalid branch name: $branch" >&2; exit 2 ;;
  esac
fi

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

resolve_dir() {   # physical path of an existing directory; empty if missing
  [ -n "${1:-}" ] || return 1   # `cd ""` is a no-op that would return $PWD
  (cd "$1" 2>/dev/null && pwd -P)
}

# The isolation contract: a path the loops may hand to an implementer must be
# the ROOT of a LINKED git worktree, checked out on the expected branch, and
# never the main checkout ($PROJECT_DIR) or anything inside it. A bare
# `rev-parse --is-inside-work-tree` is true for ANY directory inside ANY
# checkout — including a stale plain directory sitting inside $PROJECT_DIR —
# which would hand the build loop the main working tree to edit. Enforced for
# both tools: git builds correct worktrees by construction, but grove is an
# external command, so its result is verified the same way.
assert_isolated_worktree() {
  local wt_real proj_real top cur gitdir commondir proj_common wt_origin proj_origin
  wt_real="$(resolve_dir "$WT")"
  proj_real="$(resolve_dir "$PROJECT_DIR")"
  if [ -n "$proj_real" ]; then
    case "$wt_real/" in
      "$proj_real/"*)
        echo "worktree: $WT is the main checkout or inside it ($PROJECT_DIR) — refusing; fix WORKTREE_BASE" >&2
        exit 1 ;;
    esac
  fi
  top="$(git -C "$WT" rev-parse --show-toplevel 2>/dev/null)" \
    || { echo "worktree: existing directory is not a git worktree: $WT" >&2; exit 1; }
  if [ "$(resolve_dir "$top")" != "$wt_real" ]; then
    echo "worktree: $WT is a plain directory inside the checkout at $top, not a worktree root — remove it or fix WORKTREE_BASE" >&2
    exit 1
  fi
  gitdir="$(resolve_dir "$(git -C "$WT" rev-parse --absolute-git-dir 2>/dev/null)")"
  commondir="$(git -C "$WT" rev-parse --git-common-dir 2>/dev/null)"
  case "$commondir" in /*) ;; *) commondir="$WT/$commondir" ;; esac
  commondir="$(resolve_dir "$commondir")"
  if [ -z "$gitdir" ] || [ "$gitdir" = "$commondir" ]; then
    echo "worktree: $WT is a standalone checkout, not a linked worktree of the project repo — refusing" >&2
    exit 1
  fi
  # ...and linked to the SAME repo as the project. With a shared WORKTREE_BASE,
  # a leftover linked worktree of some OTHER repo would otherwise be re-used as
  # ours. Same git common dir means same repo (always true for the git backend,
  # whose worktrees hang off $PROJECT_DIR). Grove links worktrees to its own
  # bare repo — a different common dir — so when the dirs differ, accept only a
  # worktree whose `origin` URL matches the project's; anything else is foreign.
  proj_common="$(git -C "$PROJECT_DIR" rev-parse --git-common-dir 2>/dev/null)"
  case "$proj_common" in ""|/*) ;; *) proj_common="$PROJECT_DIR/$proj_common" ;; esac
  proj_common="$(resolve_dir "$proj_common")"
  if [ -n "$proj_common" ] && [ "$commondir" != "$proj_common" ]; then
    wt_origin="$(git -C "$WT" remote get-url origin 2>/dev/null || echo)"
    proj_origin="$(git -C "$PROJECT_DIR" remote get-url origin 2>/dev/null || echo)"
    if [ -z "$wt_origin" ] || [ "$wt_origin" != "$proj_origin" ]; then
      echo "worktree: $WT belongs to a different repository (git dir $commondir, project $proj_common) — refusing" >&2
      exit 1
    fi
  fi
  cur="$(git -C "$WT" symbolic-ref --quiet --short HEAD 2>/dev/null || echo)"
  if [ "$cur" != "$branch" ]; then
    echo "worktree: $WT is checked out on '${cur:-detached HEAD}', expected '$branch' — remove it or fix the checkout" >&2
    exit 1
  fi
}

is_merged_worktree() {
  local wt="$1" br="$2" base="$3" basetip tip
  [ -d "$wt" ] || return 1
  [ "$wt" = "$PROJECT_DIR" ] && return 1
  [ "$br" = "$base" ] && return 1
  git -C "$PROJECT_DIR" fetch --quiet origin "$base" 2>/dev/null || return 1
  basetip="$(git -C "$PROJECT_DIR" rev-parse "origin/$base" 2>/dev/null || echo)"
  tip="$(git -C "$wt" rev-parse HEAD 2>/dev/null)" || return 1
  [ "$tip" = "$basetip" ] && return 1
  git -C "$wt" diff --quiet 2>/dev/null || return 1
  git -C "$wt" diff --cached --quiet 2>/dev/null || return 1
  git -C "$PROJECT_DIR" merge-base --is-ancestor "$tip" "origin/$base" 2>/dev/null
}

case "$verb" in
  path) echo "$WT" ;;

  merged)
    is_merged_worktree "$WT" "$branch" "$base"
    ;;

  cleanup)
    [ -d "$WORKTREE_BASE" ] || exit 0
    for wt in "$WORKTREE_BASE"/*/; do
      [ -d "$wt" ] || continue
      wt="${wt%/}"
      br="$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null)" || continue
      is_merged_worktree "$wt" "$br" "$base" || continue
      "$0" remove "$br" >/dev/null 2>&1 || continue
      echo "$br"
    done
    git -C "$PROJECT_DIR" worktree prune >/dev/null 2>&1 || true
    ;;

  add)
    # The pool itself must live outside the main checkout, or every "isolated"
    # worktree sits inside $PROJECT_DIR (and its half-finished files leak into
    # the main tree's test/tooling runs). Checked here, not just in doctor.
    _proj_real="$(resolve_dir "$PROJECT_DIR")"
    mkdir -p "$WORKTREE_BASE" 2>/dev/null || true
    _base_real="$(resolve_dir "$WORKTREE_BASE")"
    if [ -n "$_proj_real" ] && [ -n "$_base_real" ]; then
      case "$_base_real/" in
        "$_proj_real/"*)
          echo "worktree: WORKTREE_BASE ($WORKTREE_BASE) is inside PROJECT_DIR — worktrees there are not isolated; use a sibling directory" >&2
          exit 1 ;;
      esac
    fi
    # Idempotent: an existing worktree dir is re-used (revise re-runs the same
    # branch) — but only once it proves to be the isolated worktree we manage.
    if [ -d "$WT" ]; then assert_isolated_worktree; echo "$WT"; exit 0; fi
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
    # Verify what the tool produced before a caller cd's into it — for git this
    # is belt-and-braces; for grove it is the only check on an external command.
    assert_isolated_worktree
    echo "$WT"
    ;;

  remove)
    _proj_real="$(resolve_dir "$PROJECT_DIR")"
    if [ -n "$_proj_real" ] && [ "$(resolve_dir "$WT")" = "$_proj_real" ]; then
      echo "worktree: refusing to remove $WT — it resolves to the main checkout ($PROJECT_DIR)" >&2
      exit 1
    fi
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

  *) echo "worktree: verb must be add|remove|path|merged|cleanup" >&2; exit 2 ;;
esac
