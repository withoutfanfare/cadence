#!/usr/bin/env python3
"""cadence queue — read-only board overview grouped by agent:* label.

Fetches in-scope issues once via the Linear adapter and buckets them into
YOUR MOVE / IN FLIGHT / PARKED tiers. Pure read; performs no writes.
"""

import argparse
import json
import os
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


def render(buckets, team_name=None, verbose=False):
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
    return "\n".join(out)


def fetch_issues():
    """Run the existing Linear adapter and parse its JSON array of issues."""
    adapter = os.path.join(os.path.dirname(__file__), "..", "linear", "cli.py")
    proc = subprocess.run(
        [sys.executable, adapter, "issues-list", "--assignee", "me"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "cadence queue: linear adapter failed\n")
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
    args = ap.parse_args(argv)
    issues = fetch_issues()
    print(render(bucket(issues), os.environ.get("LINEAR_TEAM_NAME"), args.verbose))


if __name__ == "__main__":
    main()
