#!/usr/bin/env python3
"""cadence schedule — config-driven launchd schedules.

Reads SCHED_<STAGE> from the environment (falling back to defaults that reproduce
the historical hourly, staggered schedule), parses the cadence, and renders the
single launchd scheduler plist. Every cadence is clock-aligned to midnight —
predictable firing times; stagger loops by giving them different minutes.

Format (value of each SCHED_<STAGE>):
  :MM       hourly, at minute MM         (e.g. :15 -> every hour at :15)
  Nh        every N hours, at minute 0   (e.g. 4h  -> 00:00, 04:00, 08:00, ...)
  Nh@MM     every N hours, at minute MM  (e.g. 4h@30 -> 00:30, 04:30, 08:30, ...)
"""
from datetime import datetime, timezone
import importlib.util
import os
import re
import subprocess
import sys

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.dirname(ENGINE)
SCHEDULER_LABEL = "com.cadence.scheduler"
SCHEDULER_DEFAULT_INTERVAL = 300
TRUE = {"1", "on", "true", "yes"}

# stage -> (launchd label, runner kind, runner arg, default spec)
JOBS = {
    "triage":  ("com.cadence.loop-triage",  "run-loop", "triage",  ":00"),
    "spec":    ("com.cadence.loop-spec",    "run-loop", "spec",    ":15"),
    "build":   ("com.cadence.loop-build",   "run-loop", "build",   ":30"),
    "revise":  ("com.cadence.loop-revise",  "run-loop", "revise",  ":45"),
    "advance": ("com.cadence.loop-advance", "run-loop", "advance", ":55"),
    "conduct": ("com.cadence.conduct",      "cadence",  "conduct", "3h@50"),
}

_MIN_RE = re.compile(r'^\s*:(\d{1,2})\s*$')
_HR_RE = re.compile(r'^\s*(\d+)\s*h\s*(?:@\s*(\d{1,2}))?\s*$')


def _load_env_module():
    spec = importlib.util.spec_from_file_location("cadence_env", os.path.join(ENGINE, "lib", "cadence_env.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cadence_env = _load_env_module()


def is_off(spec):
    return (spec or "").strip().lower() in {"off", "0", "false", "no"}


def parse_spec(spec):
    """('minute', M) or ('hours', (every_N, minute)). Raises ValueError on a bad spec."""
    spec = spec or ""
    m = _MIN_RE.match(spec)
    if m:
        minute = int(m.group(1))
        if minute > 59:
            raise ValueError(f"minute must be 0-59: {spec!r}")
        return ("minute", minute)
    h = _HR_RE.match(spec)
    if h:
        n = int(h.group(1))
        minute = int(h.group(2) or 0)
        if n < 1 or n > 24:
            raise ValueError(f"hours must be 1-24: {spec!r}")
        if minute > 59:
            raise ValueError(f"minute must be 0-59: {spec!r}")
        return ("hours", (n, minute))
    raise ValueError(f"bad spec {spec!r} (use :MM, Nh, or Nh@MM)")


def _hours_for(n):
    return list(range(0, 24, n))


def describe(spec):
    if is_off(spec):
        return "off"
    kind, val = parse_spec(spec)
    if kind == "minute":
        return f"hourly at :{val:02d}"
    n, minute = val
    return f"every {n}h at :{minute:02d}"


def spec_for(stage, env=None):
    env = os.environ if env is None else env
    return (env.get("SCHED_" + stage.upper()) or "").strip() or JOBS[stage][3]


def _schedule_xml(spec):
    kind, val = parse_spec(spec)
    if kind == "minute":
        return ("  <key>StartCalendarInterval</key>\n"
                f"  <dict><key>Minute</key><integer>{val}</integer></dict>")
    n, minute = val
    hours = _hours_for(n)
    if len(hours) == 1:
        return ("  <key>StartCalendarInterval</key>\n"
                f"  <dict><key>Hour</key><integer>{hours[0]}</integer>"
                f"<key>Minute</key><integer>{minute}</integer></dict>")
    items = "\n".join(
        f"    <dict><key>Hour</key><integer>{h}</integer>"
        f"<key>Minute</key><integer>{minute}</integer></dict>" for h in hours)
    return "  <key>StartCalendarInterval</key>\n  <array>\n" + items + "\n  </array>"


def _program_args(kind, arg, home):
    if kind == "run-loop":
        return [f"{home}/engine/scripts/run-loop.sh", arg]
    return [f"{home}/bin/cadence", arg]


def render_scheduler_plist(home, state, interval=SCHEDULER_DEFAULT_INTERVAL):
    args_xml = "\n".join(f"    <string>{a}</string>"
                         for a in [f"{home}/bin/cadence", "schedule", "tick"])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{SCHEDULER_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
  <key>StartInterval</key><integer>{interval}</integer>
  <key>StandardOutPath</key><string>{state}/logs/scheduler.launchd.log</string>
  <key>StandardErrorPath</key><string>{state}/logs/scheduler.launchd.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


def render_plist(stage, home, state, spec):
    label, kind, arg, _ = JOBS[stage]
    args_xml = "\n".join(f"    <string>{a}</string>"
                         for a in _program_args(kind, arg, home))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array>
{args_xml}
  </array>
{_schedule_xml(spec)}
  <key>StandardOutPath</key><string>{state}/logs/{stage}.launchd.log</string>
  <key>StandardErrorPath</key><string>{state}/logs/{stage}.launchd.err</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


def main(argv):
    cmd = argv[0] if argv else "show"
    home = os.environ.get("CADENCE_HOME") or HOME
    state = os.environ.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence")

    if cmd == "show":
        print("  stage    spec       when")
        for stage in JOBS:
            spec = spec_for(stage)
            try:
                when = describe(spec)
            except ValueError as e:
                when = f"INVALID — {e}"
            print(f"  {stage:8} {spec:10} {when}")
        return 0

    if cmd == "check":
        bad = 0
        for stage in JOBS:
            if is_off(spec_for(stage)):
                continue
            try:
                parse_spec(spec_for(stage))
            except ValueError as e:
                print(f"  ❌ SCHED_{stage.upper()}: {e}", file=sys.stderr)
                bad += 1
        return 1 if bad else 0

    if cmd == "status":
        return print_status(os.environ)

    if cmd == "tick":
        return tick(os.environ)

    if cmd == "render-scheduler":
        interval = int(os.environ.get("CADENCE_SCHEDULER_INTERVAL") or SCHEDULER_DEFAULT_INTERVAL)
        sys.stdout.write(render_scheduler_plist(home, state, interval))
        return 0

    if cmd == "render":
        if len(argv) < 2 or argv[1] not in JOBS:
            print("render needs a job: " + "|".join(JOBS), file=sys.stderr)
            return 2
        stage = argv[1]
        try:
            sys.stdout.write(render_plist(stage, home, state, spec_for(stage)))
        except ValueError as e:
            print(f"SCHED_{stage.upper()}: {e}", file=sys.stderr)
            return 1
        return 0

    print("usage: cadence schedule [show|status|tick|apply]", file=sys.stderr)
    return 2


def projects_file(env):
    return os.path.expanduser(os.path.expandvars(
        env.get("CADENCE_PROJECTS_FILE")
        or os.path.join(env.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence"), "projects.txt")
    ))


def read_projects(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            raw = os.path.expanduser(os.path.expandvars(raw))
            if os.path.basename(raw) == ".env":
                config = os.path.abspath(raw)
                project = os.path.dirname(os.path.dirname(config))
            else:
                project = os.path.abspath(raw)
                config = os.path.join(project, "cadence", ".env")
            out.append({"project": project, "config": config})
    return out


def read_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            # bash does not treat `KEY = value` (whitespace before `=`) as an
            # assignment, so neither should we — otherwise the scheduler's parsed
            # view of a value can diverge from what lib-env.sh actually sources.
            if key != key.rstrip():
                continue
            key = key.strip()
            if key.startswith("export "):
                key = key.split(None, 1)[1]
            values[key] = _cadence_env._parse_value(val)
    return values


def _path_value(value, default):
    return os.path.expanduser(os.path.expandvars(value or default))


def _int_env(env, key, default):
    """Read an integer setting, degrading to the default on a non-numeric value
    instead of crashing the whole tick (mirrors the SCHED_* graceful handling)."""
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"scheduler: {key}={raw!r} is not an integer; using {default}", file=sys.stderr)
        return default


def _shared_state_warnings(projects):
    """Projects resolving to the same CADENCE_STATE_DIR collide on the pause flag,
    logs, and scheduler run-markers (so one can silently skip the other's slot).
    Return one warning line per directory shared by more than one project."""
    seen = {}
    for item in projects:
        values = read_env_file(item["config"])
        state = _path_value(values.get("CADENCE_STATE_DIR"), os.path.expanduser("~/.cadence"))
        seen.setdefault(state, []).append(item["project"])
    lines = []
    for state, projs in seen.items():
        if len(projs) > 1:
            lines.append(
                "warning: %d projects share CADENCE_STATE_DIR %s — pause flag, logs, "
                "and scheduler markers will collide; give each its own state dir: %s"
                % (len(projs), state, ", ".join(projs))
            )
    return lines


def _slot_key(stage, spec, now, window):
    if is_off(spec):
        return None
    kind, val = parse_spec(spec)
    if kind == "minute":
        minute = val
        if minute <= now.minute < minute + window:
            return f"{stage}:{now:%Y%m%dT%H}"
        return None
    every, minute = val
    if now.hour % every == 0 and minute <= now.minute < minute + window:
        return f"{stage}:{now:%Y%m%dT%H}"
    return None


def _marker(state, stage):
    return os.path.join(state, "scheduler", f"{stage}.last")


def _project_key(now, window):
    return f"project:{now:%Y%m%dT%H}:{now.minute // window}"


def _already_ran(state, stage, key):
    try:
        with open(_marker(state, stage), encoding="utf-8") as f:
            return f.read().strip() == key
    except FileNotFoundError:
        return False


def _mark_ran(state, stage, key):
    path = _marker(state, stage)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(key + "\n")


def _run_stage(home, project, config, stage, run):
    cmd = [os.path.join(home, "bin", "cadence"), "--config", config]
    if stage == "conduct":
        cmd.append("conduct")
    else:
        cmd.extend(["run", stage])
    env = os.environ.copy()
    env["CADENCE_CONFIG"] = config
    return run(cmd, cwd=project, env=env)


def tick(env, now=None, run=subprocess.run):
    home = env.get("CADENCE_HOME") or HOME
    now = now or datetime.now(timezone.utc)
    window = max(1, _int_env(env, "CADENCE_SCHEDULER_WINDOW_MINUTES", 5))
    max_runs = _int_env(env, "CADENCE_SCHEDULER_MAX_RUNS", 1)
    projects = read_projects(projects_file(env))
    ran = 0
    failed = 0

    if not projects:
        print(f"scheduler: no projects in {projects_file(env)}")
        return 0

    for w in _shared_state_warnings(projects):
        print(w, file=sys.stderr)

    for item in projects:
        if ran >= max_runs:
            break
        project, config = item["project"], item["config"]
        values = read_env_file(config)
        if (values.get("CADENCE_SCHEDULED") or "").lower() not in TRUE:
            print(f"{project}: skipped (CADENCE_SCHEDULED not enabled)")
            continue
        state = _path_value(values.get("CADENCE_STATE_DIR"), os.path.expanduser("~/.cadence"))
        project_key = _project_key(now, window)
        if _already_ran(state, "project", project_key):
            continue
        for stage in JOBS:
            spec = (values.get("SCHED_" + stage.upper()) or JOBS[stage][3]).strip()
            try:
                key = _slot_key(stage, spec, now, window)
            except ValueError as e:
                print(f"{project}: SCHED_{stage.upper()} invalid: {e}", file=sys.stderr)
                failed = 1
                continue
            if not key or _already_ran(state, stage, key):
                continue
            proc = _run_stage(home, project, config, stage, run)
            _mark_ran(state, "project", project_key)
            _mark_ran(state, stage, key)
            ran += 1
            print(f"{project}: {stage} exit {proc.returncode}")
            if proc.returncode:
                failed = 1
            break
    if ran == 0:
        print("scheduler: nothing due")
    return failed


def print_status(env):
    path = projects_file(env)
    print(f"projects: {path}")
    print(f"max runs/tick: {env.get('CADENCE_SCHEDULER_MAX_RUNS') or 1}")
    projects = read_projects(path)
    if not projects:
        print("  (none)")
        return 0
    for item in projects:
        values = read_env_file(item["config"])
        enabled = "yes" if (values.get("CADENCE_SCHEDULED") or "").lower() in TRUE else "no"
        print(f"  {item['project']}  scheduled={enabled}  config={item['config']}")
    for w in _shared_state_warnings(projects):
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
