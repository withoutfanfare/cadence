#!/usr/bin/env python3
"""cadence conduct — deterministic WIP-limited feeder for autonomous mode.

Ranks the ready backlog, skips blocked issues, and tops up the agent:auto queue
to CONDUCT_WIP. No model invocation. The conduct pass shells out to the Linear
adapter; the filtering/ranking/blocked logic here is pure and unit-tested.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

_ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(modname, relpath):
    spec = importlib.util.spec_from_file_location(modname, os.path.join(_ENGINE, relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_advance = _load("advance_cli", "advance/cli.py")
parse_criteria = _advance.parse_criteria

_TERMINAL = {"completed", "canceled"}
_BLOCK_OUT = {"agent:hold", "agent:superseded", "agent:needs-human", "agent:auto"}
# Linear priority: 1=urgent … 4=low, 0=none. Map so urgent ranks highest and
# none ranks lowest, then sort priority-descending (most urgent first).
_PRIORITY_RANK = {1: 4, 2: 3, 3: 2, 4: 1}


def eligible(issues):
    out = []
    for i in issues:
        labels = set(i.get("labels") or [])
        if "agent:triaged" not in labels:
            continue
        if labels & _BLOCK_OUT:
            continue
        if (i.get("state_type") or "") in _TERMINAL:
            continue
        if not parse_criteria(i.get("description") or ""):
            continue
        out.append(i)
    return out


def _sort_key(issue, active_cycle):
    prio = _PRIORITY_RANK.get(issue.get("priority"), 0)  # urgent→4 … low→1; none→0 (last)
    in_cycle = 1 if (active_cycle is not None and issue.get("cycle") == active_cycle) else 0
    created = issue.get("createdAt") or ""
    # priority desc (most urgent first), then in-cycle first, then oldest first
    return (-prio, -in_cycle, created)


def rank(issues, active_cycle):
    return sorted(issues, key=lambda i: _sort_key(i, active_cycle))


def is_blocked(detail):
    for rel in (detail.get("inverseRelations") or []):
        if rel.get("type") != "blocks":
            continue
        state = ((rel.get("issue") or {}).get("state") or {}).get("type")
        if state not in _TERMINAL:
            return True
    return False


_cadence_env = _load("cadence_env", "lib/cadence_env.py")

_TRUE = {"1", "true", "on", "yes"}


def _linear(*args):
    adapter = os.path.join(_ENGINE, "linear", "cli.py")
    proc = subprocess.run([sys.executable, adapter, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or "cadence conduct: linear adapter failed\n")
        sys.exit(1)
    return json.loads(proc.stdout or "null")


def _active_cycle():
    # cycles-list returns {number, starts_at, ends_at}; the active cycle is the
    # one whose window contains now (there is no isActive flag).
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for c in (_linear("cycles-list") or []):
        s, e = c.get("starts_at"), c.get("ends_at")
        try:
            sd = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
            ed = datetime.fromisoformat((e or "").replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if sd <= now <= ed:
            return c.get("number")
    return None


def conduct(env, dry_run=False):
    """One feeder pass. Returns a summary dict."""
    state_dir = env.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence")
    if os.path.exists(os.path.join(state_dir, "runs", "PAUSED")):
        return {"loop": "conduct", "dry_run": dry_run, "paused": True, "reason": "manual"}
    if (env.get("AUTONOMOUS") or "").strip().lower() not in _TRUE:
        return {"loop": "conduct", "dry_run": dry_run, "paused": True, "reason": "autonomous-off"}

    wip = int(env.get("CONDUCT_WIP") or 1)
    issues = _linear("issues-list", "--assignee", "me") or []
    inflight = [i for i in issues if "agent:auto" in (i.get("labels") or [])]
    free = wip - len(inflight)
    if free <= 0:
        return {"loop": "conduct", "dry_run": dry_run, "inflight": len(inflight),
                "free": 0, "tagged": [], "note": "queue full"}

    active = _active_cycle()
    ranked = rank(eligible(issues), active)
    tagged, skipped_blocked = [], []
    for cand in ranked:
        if len(tagged) >= free:
            break
        detail = _linear("issue-get", cand["identifier"])
        if is_blocked(detail):
            skipped_blocked.append(cand["identifier"])
            continue
        if not dry_run:
            _linear("issue-update", cand["identifier"], "--add-label", "agent:auto")
        tagged.append(cand["identifier"])
    return {"loop": "conduct", "dry_run": dry_run, "inflight": len(inflight),
            "free": free, "tagged": tagged, "skipped_blocked": skipped_blocked}


def _summary_line(summary):
    tagged = len(summary.get("tagged") or [])
    blocked = len(summary.get("skipped_blocked") or [])
    if summary.get("paused"):
        return "PAUSED — %s" % summary.get("reason", "?")
    parts = []
    if tagged:
        parts.append("%d tagged" % tagged)
    if blocked:
        parts.append("%d blocked" % blocked)
    if summary.get("free") == 0 and summary.get("note"):
        parts.append(summary["note"])
    return ", ".join(parts) if parts else "nothing to do"


def append_ledger(summary, env, ts=None):
    state_dir = env.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence")
    runs_dir = os.path.join(state_dir, "runs")
    os.makedirs(runs_dir, exist_ok=True)
    ts = ts or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record = dict(summary)
    record["ts"] = ts
    with open(os.path.join(runs_dir, "runs.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")
    with open(os.path.join(runs_dir, "activity.log"), "a", encoding="utf-8") as f:
        f.write("[%s] conduct — %s\n" % (ts, _summary_line(summary)))
    logs_dir = os.path.join(state_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    with open(os.path.join(logs_dir, "conduct.log"), "a", encoding="utf-8") as f:
        f.write("[%s] conduct — %s\n" % (ts, _summary_line(summary)))
    day = ts[:10]
    mode = "dry-run" if summary.get("dry_run") else "live"
    with open(os.path.join(runs_dir, day + ".md"), "a", encoding="utf-8") as f:
        f.write("\n## conduct · %s · %s\n\n%s\n" % (mode, ts, _summary_line(summary)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="cadence conduct")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    env = _cadence_env.load_env()
    summary = conduct(env, dry_run=args.dry_run)
    append_ledger(summary, env)
    print(json.dumps(summary, separators=(",", ":")))


if __name__ == "__main__":
    main()
