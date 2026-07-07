#!/usr/bin/env python3
"""cadence overview — one glance across every registered project. Stdlib only.

The single-project `cadence status` shows one config's state dir. This aggregates
the scheduler registry: for each project it reports scheduled/paused, the last run
per stage (from that project's runs.jsonl), and a derived health so a menu bar or
terminal can show the whole system at once. Read-only; makes no network calls.

`main()` prints a human table, or a JSON object with `--json` for SwiftBar.
"""
import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGES = ["triage", "spec", "build", "revise", "advance", "roadmap", "conduct"]
TRUE = {"1", "on", "true", "yes"}


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ENGINE, *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Reuse the scheduler's registry/config readers — one source of truth for how a
# project folder or .env path maps to its config and settings.
_schedule = _load("cadence_schedule_cli", "schedule", "cli.py")


def _resolve(path, default=None):
    return os.path.expanduser(os.path.expandvars(path)) if path else default


def _last_run_per_stage(state_dir):
    """Last substantive ledger entry per stage from runs/runs.jsonl, keyed by
    stage/loop. Paused runs are skipped: a pause is a skipped tick that did no
    work, so it must not mask a stage's real last result (and current-pause is
    already surfaced by the PAUSED flag → health)."""
    out = {}
    path = os.path.join(state_dir, "runs", "runs.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("paused"):
                    continue
                stage = d.get("stage") or d.get("loop")
                if stage:
                    out[stage] = d
    except FileNotFoundError:
        pass
    return out


def _stage_result(d):
    """Compact outcome string for one ledger entry. Paused runs never reach here
    — _last_run_per_stage skips them."""
    if d.get("idle"):
        return "idle"
    errors = int(d.get("errors") or 0)
    if errors:
        return "%d error(s)" % errors
    return "ok"


def _tail(path, n=1):
    try:
        with open(path, encoding="utf-8") as f:
            lines = [x.rstrip("\n") for x in f if x.strip()]
        return lines[-n:]
    except FileNotFoundError:
        return []


def _linear_board_url(values):
    if (values.get("TASK_BACKEND") or "linear").lower() != "linear":
        return None
    workspace = values.get("LINEAR_WORKSPACE_SLUG") or values.get("LINEAR_WORKSPACE")
    workspace = workspace.strip().strip("/") if workspace else ""
    return "https://linear.app/%s/" % workspace if workspace else None


def _project_overview(item, now=None):
    now = now or datetime.now(timezone.utc)
    config = item["config"]
    values = _schedule.read_env_file(config)
    state_dir = _resolve(values.get("CADENCE_STATE_DIR"), os.path.expanduser("~/.cadence"))
    scheduled = (values.get("CADENCE_SCHEDULED") or "").lower() in TRUE
    autonomous = (values.get("AUTONOMOUS") or "").lower() in TRUE
    paused = os.path.exists(os.path.join(state_dir, "runs", "PAUSED"))
    runs = _last_run_per_stage(state_dir)

    stages = {}
    any_error = False
    for stage in STAGES:
        d = runs.get(stage)
        if d is None:
            stages[stage] = None
            continue
        errors = int(d.get("errors") or 0)
        any_error = any_error or errors > 0
        stages[stage] = {"ts": d.get("ts"), "errors": errors, "result": _stage_result(d)}

    if paused:
        health = "paused"
    elif any_error:
        health = "failed"
    elif any(stages[s] for s in STAGES):
        health = "ok"
    else:
        health = "idle"

    # Next scheduled run per stage (UTC ISO). Only when the project is actually
    # scheduled and not paused — a paused loop would fire and exit doing nothing,
    # so advertising a next-run then would mislead.
    schedule = {}
    for stage in STAGES:
        nr = _schedule.next_run(_schedule.spec_for(stage, values), now) \
            if (scheduled and not paused) else None
        schedule[stage] = nr.isoformat().replace("+00:00", "Z") if nr else None

    activity = _tail(os.path.join(state_dir, "runs", "activity.log"), 1)
    return {
        "name": os.path.basename(item["project"]),
        "project": item["project"],
        "config": config,
        "state_dir": state_dir,
        "team_name": values.get("LINEAR_TEAM_NAME") or None,
        "board_url": _linear_board_url(values),
        "backend": (values.get("TASK_BACKEND") or "linear").lower(),
        "scheduled": scheduled,
        "autonomous": autonomous,
        "paused": paused,
        "health": health,
        "stages": stages,
        "schedule": schedule,
        "last_activity": activity[0] if activity else None,
    }


def overview(env):
    items = _schedule.read_projects(_schedule.projects_file(env))
    projects = [_project_overview(it) for it in items]
    return {
        "registry": _schedule.projects_file(env),
        "projects": projects,
        "warnings": _schedule.shared_state_warnings(items) if items else [],
    }


_HEALTH_GLYPH = {"ok": "✅", "failed": "❌", "paused": "⏸", "idle": "·", "unknown": "?"}


def render_human(data):
    out = []
    reg = data["registry"]
    projects = data["projects"]
    out.append("── Cadence overview · %d project(s) ──────────────" % len(projects))
    if not projects:
        out.append("  none registered (cadence schedule register <path>)")
        return "\n".join(out)
    for p in projects:
        flags = []
        flags.append("scheduled" if p["scheduled"] else "not scheduled")
        if p["paused"]:
            flags.append("PAUSED")
        head = "%s %s%s  [%s]" % (
            _HEALTH_GLYPH.get(p["health"], "?"), p["name"],
            (" · " + p["team_name"]) if p["team_name"] else "",
            ", ".join(flags))
        out.append("")
        out.append(head)
        cells = []
        for s in STAGES:
            st = p["stages"].get(s)
            cells.append("%s=%s" % (s, st["result"] if st else "—"))
        out.append("    " + "  ".join(cells))
        if p["last_activity"]:
            out.append("    last: " + p["last_activity"])
    for w in data["warnings"]:
        out.append("")
        out.append("  ⚠ " + w)
    out.append("")
    out.append("  registry: " + reg)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cadence overview",
                                 description="Cross-project status for every registered project.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    data = overview(os.environ)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_human(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
