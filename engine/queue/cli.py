#!/usr/bin/env python3
"""cadence queue — read-only board overview grouped by agent:* label.

Fetches in-scope issues once via the Linear adapter and buckets them into
YOUR MOVE / IN FLIGHT / PARKED tiers. Pure read; performs no writes.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# (bucket_id, display label, agent label) — YOUR MOVE shown in lifecycle order.
YOUR_MOVE = [
    ("triaged",         "Grant spec",   "agent:triaged"),
    ("specced",         "Grant build",  "agent:specced"),
    ("pr_open",         "Review PR",    "agent:pr-open"),
    ("revised",         "Re-review PR", "agent:revised"),
    ("needs_human",     "Needs you",    "agent:needs-human"),
    ("needs_attention", "Run failed",   "agent:needs-attention"),
]
IN_FLIGHT = [("claimed", "Working now", "agent:claimed")]
PARKED = [
    ("hold",       "on hold",    "agent:hold"),
    ("superseded", "superseded", "agent:superseded"),
    ("stale",      "stale",      "Stale"),
]

# First match wins: parked removes from play, failures are loudest, then
# in-flight, then the most-advanced lifecycle gate.
ASSIGN_ORDER = [
    "hold", "superseded", "stale",
    "needs_attention", "needs_human", "claimed",
    "revised", "pr_open", "specced", "triaged",
]

_LABEL = {bid: lbl for bid, _disp, lbl in YOUR_MOVE + IN_FLIGHT + PARKED}


def bucket(issues):
    """Assign each issue to at most one bucket by ASSIGN_ORDER precedence."""
    out = {bid: [] for bid in _LABEL}
    for issue in issues:
        labels = set(issue.get("labels") or [])
        for bid in ASSIGN_ORDER:
            if _LABEL[bid] in labels:
                out[bid].append(issue)
                break
    return out


# Lifecycle position labels that are mutually exclusive on a clean board: the
# build loop swaps specced→pr-open, revise swaps pr-open→revised. Two of these at
# once means a loop crashed mid-transition. agent:triaged is deliberately sticky
# (only a human clears it — docs/LABELS.md) so it coexists with any position by
# design, and the exception flags (needs-attention/needs-human) ride alongside a
# position too — none of those are conflicts.
_CONFLICT_LABELS = ["agent:specced", "agent:pr-open", "agent:revised"]


def conflicts(issues):
    """Issues carrying two or more mutually-exclusive lifecycle position labels —
    a sign of a loop that crashed mid-transition, leaving stale board state.
    Returns [(identifier, [labels]), ...]."""
    out = []
    for issue in issues:
        labels = set(issue.get("labels") or [])
        matched = [lbl for lbl in _CONFLICT_LABELS if lbl in labels]
        if len(matched) > 1:
            out.append((issue.get("identifier", "?"), matched))
    return out


# ── Failure clustering ───────────────────────────────────────────────────────
# A systemic problem (a broken worktree, a repo-wide gate, an engine gap) parks
# many issues with the same failure. Grouping them by root cause turns "17 red
# items to triage one by one" into "3 things to fix once". First signature wins;
# order most-specific first.
_FAILURE_SIGNATURES = [
    (("bare repo", "could not find bare", "grove add' failed", "worktree add failed",
      "worktree creation failed", "could not create worktree"),
     "Worktree setup",
     "the worktree backend can't create a tree — check WORKTREE_TOOL and that the git/grove repo exists (`cadence doctor`)"),
    (("doc-get", "doc-list", "criteria_present", "linked-document", "linked spec document"),
     "Spec-doc verification",
     "engine gap now fixed — clear agent:needs-attention to let advance retry"),
    (("review_clean", "run-reviewer", "reviewer stage", "stage name"),
     "Reviewer",
     "engine bug now fixed — clear agent:needs-attention to let advance retry"),
    (("empty diff", "no implementation diff", "nothing to ship"),
     "Empty diff",
     "no change was produced — likely already done; verify and close, or re-spec"),
    (("already present", "already on", "already exists", "already done", "already merged"),
     "Work already on base",
     "the change is already on the base branch — close it as done"),
    (("lint", "phpstan", "duster", "pre-existing", "full test suite", "gate failed", "gate failure"),
     "Gate on pre-existing debt",
     "scope the gate to the change or add a baseline (`cadence doctor` flags repo-wide gates)"),
]

_REASON_HINT_WORDS = ("build note", "gate", "worktree", "fail", "block", "no pr",
                      "empty diff", "cannot", "could not", "parked", "already",
                      "review", "criteria", "needs-attention", "doc-")


def classify_failure(reason):
    """Map a failure reason (a run note or last comment) to a (cluster, fix-hint)."""
    low = (reason or "").lower()
    for needles, label, hint in _FAILURE_SIGNATURES:
        if any(n in low for n in needles):
            return label, hint
    return "Other", "read the run note / last comment and decide"


def cluster_failures(items):
    """items: iterable of (identifier, reason). Returns clusters
    [{"label","hint","ids"}], largest first, so the biggest shared cause leads."""
    groups = {}
    for ident, reason in items:
        label, hint = classify_failure(reason)
        groups.setdefault(label, {"label": label, "hint": hint, "ids": []})["ids"].append(ident)
    return sorted(groups.values(), key=lambda g: (-len(g["ids"]), g["label"]))


def _salient_line(text):
    """The most failure-relevant one-liner from a run note or comment."""
    if not text:
        return ""
    best = ""
    for para in re.split(r"\n\s*\n", text):
        if any(w in para.lower() for w in _REASON_HINT_WORDS):
            best = " ".join(para.split())
    if not best:
        for line in text.splitlines():
            if line.strip():
                best = " ".join(line.split())
                break
    return best[:200]


def render_failures(clusters, team_name=None):
    head = "── Run failures%s ──────────────" % (" · " + team_name if team_name else "")
    if not clusters:
        return head + "\n  None — nothing is in agent:needs-attention."
    out = [head, "grouped by root cause — fix each once:"]
    for c in clusters:
        out.append("  ⚠ %-26s %2d   %s" % (c["label"], len(c["ids"]), ", ".join(c["ids"])))
        out.append("      ↳ %s" % c["hint"])
    return "\n".join(out)


def _failure_reason(issue, env):
    """One-line reason a needs-attention issue failed: the run note in a file
    task's body, or a Linear issue's last comment."""
    if _backend(env) == "file":
        return _salient_line(issue.get("description") or issue.get("body") or "")
    ident = issue.get("identifier")
    if not ident:
        return ""
    adapter = os.path.join(os.path.dirname(__file__), "..", "linear", "cli.py")
    run_env = os.environ.copy()
    run_env.update(env)
    proc = subprocess.run([sys.executable, adapter, "issue-get", ident],
                          capture_output=True, text=True, env=run_env)
    if proc.returncode != 0:
        return ""
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return ""
    comments = data.get("comments") or []
    return _salient_line(comments[-1].get("body", "") if comments else "")


def _keys(issues, cap=15):
    if not issues:
        return "—"
    shown = issues if cap is None else issues[:cap]
    parts = []
    for i in shown:
        k = i.get("identifier", "?")
        if "agent:dupe-candidate" in (i.get("labels") or []):
            k += "*"
        parts.append(k)
    s = ", ".join(parts)
    extra = len(issues) - len(shown)
    if extra > 0:
        s += ", …+%d more" % extra
    return s


def _verbose_lines(issues):
    lines = []
    for i in issues:
        meta = []
        if i.get("priority"):
            meta.append("P%s" % i["priority"])
        if i.get("cycle") is not None:
            meta.append("cycle %s" % i["cycle"])
        tail = ("  ·  " + " / ".join(meta)) if meta else ""
        lines.append("      %s  %s%s" % (i.get("identifier", "?"), i.get("title", ""), tail))
        lines.append("        %s" % i.get("url", ""))
    return lines


def render(buckets, team_name=None, verbose=False, conflict_list=None):
    head = "── Cadence queue%s ──────────────" % (" · " + team_name if team_name else "")
    if sum(len(v) for v in buckets.values()) == 0:
        return head + "\n  Nothing waiting on you."

    out = [head, "YOUR MOVE"]
    dupe_seen = False
    for bid, disp, lbl in YOUR_MOVE:
        items = buckets[bid]
        marker = "  ⚠" if bid == "needs_attention" and items else "  ▸"
        keys = _keys(items, cap=None if verbose else 15)
        out.append("%s %-13s %-23s %3d   %s" % (marker, disp, "(%s)" % lbl, len(items), keys))
        if any("agent:dupe-candidate" in (i.get("labels") or []) for i in items):
            dupe_seen = True
        if verbose and items:
            out += _verbose_lines(items)
    if dupe_seen:
        out.append("  * = duplicate candidate")

    inflight = buckets["claimed"]
    out += ["", "IN FLIGHT",
            "  • %-13s %-23s %3d   %s" % ("Working now", "(agent:claimed)", len(inflight), _keys(inflight))]
    if verbose and inflight:
        out += _verbose_lines(inflight)

    parked = ["%s %d" % (disp, len(buckets[bid])) for bid, disp, _lbl in PARKED if buckets[bid]]
    out += ["", "PARKED  (counts only)",
            "  " + (" · ".join(parked) if parked else "nothing parked")]

    if conflict_list:
        out.append("")
        for ident, labels in conflict_list:
            out.append("⚠ inconsistent labels: %s (%s)" % (ident, " + ".join(labels)))
    return "\n".join(out)


def _backend(env=None):
    return ((env or os.environ).get("TASK_BACKEND") or "linear").strip().lower()


def fetch_issues(env=None):
    """Run the configured task adapter and parse its JSON array of issues."""
    env = env or os.environ
    if _backend(env) == "file":
        adapter = os.path.join(os.path.dirname(__file__), "..", "tasks", "cli.py")
        args = ["list"]
        error = "cadence queue: tasks adapter failed\n"
    else:
        adapter = os.path.join(os.path.dirname(__file__), "..", "linear", "cli.py")
        args = ["issues-list", "--assignee", "me"]
        error = "cadence queue: linear adapter failed\n"
    run_env = os.environ.copy()
    run_env.update(env)
    proc = subprocess.run(
        [sys.executable, adapter, *args],
        capture_output=True, text=True, env=run_env,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or error)
        sys.exit(1)
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        sys.stderr.write("cadence queue: could not parse adapter output: %s\n" % exc)
        sys.exit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cadence queue",
                                 description="What needs you now, grouped by agent state.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="expand each actionable issue to title, priority, cycle and URL")
    ap.add_argument("--why", action="store_true",
                    help="cluster the failed (agent:needs-attention) issues by root cause, "
                         "each with a one-line fix, so a shared cause is fixed once")
    args = ap.parse_args(argv)
    issues = fetch_issues()
    if args.why:
        failed = bucket(issues)["needs_attention"]
        items = [(i.get("identifier", "?"), _failure_reason(i, os.environ)) for i in failed]
        print(render_failures(cluster_failures(items), os.environ.get("LINEAR_TEAM_NAME")))
        return
    print(render(bucket(issues), os.environ.get("LINEAR_TEAM_NAME"), args.verbose,
                 conflicts(issues)))


if __name__ == "__main__":
    main()
