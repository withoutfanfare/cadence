#!/usr/bin/env python3
"""cadence prune — retention for local Cadence run history."""

from datetime import datetime, timedelta, timezone
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from atomic_file import atomic_write  # noqa: E402


_DAY_MD = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_ACTIVITY_TS = re.compile(r"^\[([^]]+)\]")


def _parse_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _cutoff(days, now):
    return now - timedelta(days=days)


def _keep_day_file(name, cutoff):
    if not _DAY_MD.match(name):
        return True
    day = datetime.strptime(name[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return day >= cutoff.replace(hour=0, minute=0, second=0, microsecond=0)


def _prune_daily(runs_dir, cutoff, dry_run):
    removed = []
    if not os.path.isdir(runs_dir):
        return removed
    for name in os.listdir(runs_dir):
        path = os.path.join(runs_dir, name)
        if os.path.isfile(path) and _DAY_MD.match(name) and not _keep_day_file(name, cutoff):
            removed.append(path)
            if not dry_run:
                os.unlink(path)
    return removed


def _prune_logs(logs_dir, cutoff, dry_run):
    removed = []
    if not os.path.isdir(logs_dir):
        return removed
    for name in os.listdir(logs_dir):
        path = os.path.join(logs_dir, name)
        if not os.path.isfile(path) or not name.endswith(".log"):
            continue
        if datetime.fromtimestamp(os.path.getmtime(path), timezone.utc) < cutoff:
            removed.append(path)
            if not dry_run:
                os.unlink(path)
    return removed


def _prune_jsonl(path, cutoff, dry_run):
    if not os.path.exists(path):
        return 0
    kept, removed = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            ts = _parse_ts(rec.get("ts") or rec.get("timestamp") or rec.get("date"))
            if ts is not None and ts < cutoff:
                removed += 1
            else:
                kept.append(line)
    if removed and not dry_run:
        atomic_write(path, "".join(kept))
    return removed


def _prune_activity(path, cutoff, dry_run):
    if not os.path.exists(path):
        return 0
    kept, removed = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = _ACTIVITY_TS.match(line)
            ts = _parse_ts(match.group(1) if match else None)
            if ts is not None and ts < cutoff:
                removed += 1
            else:
                kept.append(line)
    if removed and not dry_run:
        atomic_write(path, "".join(kept))
    return removed


def prune(state_dir, days=30, dry_run=False, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = _cutoff(days, now)
    runs_dir = os.path.join(state_dir, "runs")
    logs_dir = os.path.join(state_dir, "logs")
    daily = _prune_daily(runs_dir, cutoff, dry_run)
    logs = _prune_logs(logs_dir, cutoff, dry_run)
    jsonl = _prune_jsonl(os.path.join(runs_dir, "runs.jsonl"), cutoff, dry_run)
    activity = _prune_activity(os.path.join(runs_dir, "activity.log"), cutoff, dry_run)
    return {
        "state_dir": state_dir,
        "days": days,
        "dry_run": dry_run,
        "daily_files": len(daily),
        "log_files": len(logs),
        "jsonl_records": jsonl,
        "activity_lines": activity,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cadence prune")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.days < 1:
        print("cadence prune: --days must be at least 1", file=sys.stderr)
        return 2
    state = os.environ.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence")
    print(json.dumps(prune(state, days=args.days, dry_run=args.dry_run), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
