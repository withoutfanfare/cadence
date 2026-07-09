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
from datetime import datetime, timedelta, timezone
import concurrent.futures
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.dirname(ENGINE)
sys.path.insert(0, os.path.join(ENGINE, "lib"))
from atomic_file import atomic_write  # noqa: E402

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
    "roadmap": ("com.cadence.loop-roadmap", "run-loop", "roadmap", "off"),
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


def next_run(spec, now):
    """Next datetime at or after `now` when this spec fires, or None if off/invalid.
    Works in whatever timezone `now` carries; the scheduler ticks in UTC."""
    if is_off(spec):
        return None
    try:
        kind, val = parse_spec(spec)
    except ValueError:
        return None
    now = now.replace(second=0, microsecond=0)
    minute = val if kind == "minute" else val[1]
    cand = now.replace(minute=minute)
    if cand <= now:
        cand += timedelta(hours=1)
    if kind == "minute":
        return cand
    every = val[0]
    for _ in range(24):  # at most 24 hourly steps to land on an every-N hour
        if cand.hour % every == 0:
            return cand
        cand += timedelta(hours=1)
    return None


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

    if cmd == "register":
        return register(os.environ, argv[1:])

    if cmd == "unregister":
        return unregister(os.environ, argv[1:])

    if cmd == "onboard":
        return onboard(os.environ, argv[1:])

    if cmd == "offboard":
        return offboard(os.environ, argv[1:])

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

    print("usage: cadence schedule [show|status|register|unregister|tick|apply]", file=sys.stderr)
    return 2


def _root_config_path(env):
    home = os.path.expanduser(os.path.expandvars(env.get("CADENCE_HOME") or HOME))
    return os.path.abspath(os.path.join(home, ".env"))


def _active_config_path(env):
    path = env.get("CADENCE_CONFIG")
    if not path:
        return None
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def _registry_env(env):
    active = _active_config_path(env)
    root = _root_config_path(env)
    if active and active != root:
        root_values = read_env_file(root)
        root_values["CADENCE_HOME"] = os.path.dirname(root)
        return root_values
    return env


def projects_file(env):
    explicit = env.get("CADENCE_PROJECTS_FILE")
    if explicit:
        return os.path.expanduser(os.path.expandvars(explicit))
    reg_env = _registry_env(env)
    return os.path.expanduser(os.path.expandvars(
        reg_env.get("CADENCE_PROJECTS_FILE")
        or os.path.join(reg_env.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence"), "projects.txt")
    ))


def _project_dir_for(path):
    """Mirror read_projects: an .env path maps to its project two levels up; any
    other path is treated as the project directory itself."""
    path = os.path.abspath(os.path.expanduser(os.path.expandvars(path)))
    if os.path.basename(path) == ".env":
        return os.path.dirname(os.path.dirname(path)), path
    return path, os.path.join(path, "cadence", ".env")


def register(env, args, out=print, hint=True):
    """Add a project to the scheduler registry (idempotent). `args[0]` is a project
    directory or a config .env path; defaults to the current directory."""
    given = args[0] if args else os.getcwd()
    path = os.path.abspath(os.path.expanduser(os.path.expandvars(given)))
    project, config = _project_dir_for(path)
    reg = projects_file(env)
    for item in read_projects(reg):
        if item["project"] == project:
            out(f"already registered: {project}")
            return 0
    os.makedirs(os.path.dirname(reg), exist_ok=True)
    with open(reg, "a", encoding="utf-8") as f:
        f.write(path + "\n")
    out(f"registered: {project}")
    out(f"  registry: {reg}")
    out(f"  config:   {config}")
    if hint:
        out("Next: set CADENCE_SCHEDULED=1 in that config, then run `cadence schedule apply`.")
    return 0


def unregister(env, args, out=print):
    """Remove a project from the scheduler registry (idempotent). `args[0]` is a
    project directory or a config .env path; defaults to the current directory.
    Other lines — comments, blanks, other projects — pass through untouched."""
    given = args[0] if args else os.getcwd()
    project, _ = _project_dir_for(given)
    reg = projects_file(env)
    kept, removed = [], False
    if os.path.exists(reg):
        with open(reg, encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if raw and not raw.startswith("#") and _project_dir_for(raw)[0] == project:
                    removed = True
                    continue
                kept.append(line)
    if not removed:
        out(f"not registered: {project}")
        return 0
    with open(reg, "w", encoding="utf-8") as f:
        f.writelines(kept)
    out(f"unregistered: {project}")
    out(f"  registry: {reg}")
    return 0


def _state_dir_for(env, project):
    """Default per-project state dir: <caller state root>/projects/<basename>."""
    root = os.path.expanduser(os.path.expandvars(
        env.get("CADENCE_STATE_DIR") or "~/.cadence"))
    return os.path.join(root, "projects", os.path.basename(project))


def onboard(env, args, out=print):
    """One-shot scheduler onboarding. Fills CADENCE_STATE_DIR if blank (refusing a
    dir another registered project already uses), creates it, sets
    CADENCE_SCHEDULED=1, pauses newly registered projects (a human resumes
    deliberately), and registers. The launchd side stays in onboard.sh."""
    given = args[0] if args else os.getcwd()
    project, config = _project_dir_for(given)
    if not os.path.exists(config):
        out(f"no config at {config}")
        out("Create one first — run the cadence-setup skill, or copy .env.example.")
        return 1
    values = read_env_file(config)
    state = _path_value(values.get("CADENCE_STATE_DIR"), "")
    if not state:
        state = _state_dir_for(env, project)
        for item in read_projects(projects_file(env)):
            if item["project"] == project:
                continue
            other = read_env_file(item["config"]).get("CADENCE_STATE_DIR")
            if other and _path_value(other, "") == state:
                out(f"state dir {state} already belongs to {item['project']}")
                out("Set CADENCE_STATE_DIR in the config yourself, then re-run.")
                return 1
        upsert_env_var(config, "CADENCE_STATE_DIR", state)
        out(f"  state dir: {state} (written to config)")
    os.makedirs(os.path.join(state, "runs"), mode=0o700, exist_ok=True)
    upsert_env_var(config, "CADENCE_SCHEDULED", "1")
    out(f"  CADENCE_SCHEDULED=1 written to {config}")
    already = any(i["project"] == project
                  for i in read_projects(projects_file(env)))
    if not already:
        with open(os.path.join(state, "runs", "PAUSED"), "w", encoding="utf-8"):
            pass
        out("  paused — resume with: cadence --config " + config + " resume")
    register(env, [project], out=out, hint=False)
    return 0


def _same_or_parent(parent, child):
    try:
        return os.path.commonpath([parent, child]) == parent
    except ValueError:
        return False


def _purge_unsafe(state, env, project=None, config=None):
    """Return a refusal message if `state` must not be deleted, else None. A
    misconfigured CADENCE_STATE_DIR pointing at a broad directory or a dir
    another registered project still uses would otherwise let --purge wipe state
    it does not own. Call after unregister so the offboarded project excludes
    itself from the shared-use check."""
    canon = os.path.realpath(state)
    protected = {
        os.path.realpath(os.path.expanduser("~")),
        os.path.realpath(os.path.expanduser("~/.cadence")),
        os.path.realpath(tempfile.gettempdir()),
        os.path.realpath(os.sep),
    }
    current_state = os.path.realpath(_path_value(env.get("CADENCE_STATE_DIR"), "~/.cadence"))
    if current_state != canon:
        protected.add(current_state)
    if canon in protected:
        return f"  refused purge: {state} is not a project-owned state dir"
    home = os.path.realpath(os.path.expanduser("~"))
    if _same_or_parent(home, canon):
        parts = [p.lower() for p in canon.split(os.sep) if p]
        if ".cadence" not in parts and not any("cadence" in p for p in parts[-2:]):
            return f"  refused purge: {state} does not look like a Cadence state dir"
    if project and _same_or_parent(canon, os.path.realpath(project)):
        return f"  refused purge: {state} contains the project checkout"
    if config and _same_or_parent(canon, os.path.realpath(os.path.dirname(config))):
        return f"  refused purge: {state} contains the config directory"

    contains = []
    overlaps = []
    for p in read_projects(projects_file(env)):
        try:
            other_values = read_env_file(p["config"])
        except OSError as exc:
            return f"  refused purge: cannot inspect {p['config']}: {exc}"
        other = os.path.realpath(_path_value(
            other_values.get("CADENCE_STATE_DIR"), os.path.expanduser("~/.cadence")))
        if _same_or_parent(canon, other):
            contains.append(p["project"])
        elif _same_or_parent(other, canon):
            overlaps.append(p["project"])
    if contains:
        return f"  refused purge: {state} contains state for {', '.join(contains)}"
    if overlaps:
        return f"  refused purge: {state} overlaps state for {', '.join(overlaps)}"
    return None


def offboard(env, args, out=print):
    """Take a project off the scheduler: pause it, set CADENCE_SCHEDULED=0,
    unregister. Deletes nothing unless --purge, which removes only the project's
    own state dir (never the config, never the shared default state dir).
    Pausing/purging is skipped when the project has no CADENCE_STATE_DIR of its
    own — touching the shared default would hit every project at once."""
    purge = "--purge" in args
    paths = [a for a in args if not a.startswith("--")]
    given = paths[0] if paths else os.getcwd()
    project, config = _project_dir_for(given)
    values = read_env_file(config)
    state = _path_value(values.get("CADENCE_STATE_DIR"), "")
    if state:
        os.makedirs(os.path.join(state, "runs"), exist_ok=True)
        with open(os.path.join(state, "runs", "PAUSED"), "w", encoding="utf-8"):
            pass
        out(f"  paused: {os.path.join(state, 'runs', 'PAUSED')}")
    else:
        out("  no own CADENCE_STATE_DIR in config — skipping pause"
            + (" and purge" if purge else ""))
    if os.path.exists(config):
        upsert_env_var(config, "CADENCE_SCHEDULED", "0")
        out(f"  CADENCE_SCHEDULED=0 written to {config}")
    unregister(env, [project], out=out)
    if purge and state:
        refusal = _purge_unsafe(state, env, project=project, config=config)
        if refusal:
            out(refusal)
        else:
            shutil.rmtree(state)  # no ignore_errors: a failed delete must surface
            out(f"  purged state dir: {state}")
    elif state:
        out(f"  left in place: {state}")
    out(f"  left in place: {config}")
    return 0


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


def upsert_env_var(path, key, value):
    """Set KEY=value in a config file in place, preserving everything else.

    Replaces every uncommented assignment of the key (including `export KEY=`
    forms — lib-env sources with allexport, so the plain form is equivalent);
    appends when absent; creates the file when missing. Mirrors the in-place
    edit `autonomous.sh` performs for AUTONOMOUS.
    """
    try:
        with open(path, encoding="utf-8") as f:
            txt = f.read()
    except FileNotFoundError:
        txt = ""
    line = f"{key}={value}"
    pattern = re.compile(r"(?m)^\s*(?:export\s+)?" + re.escape(key) + r"=.*$")
    if pattern.search(txt):
        txt = pattern.sub(line, txt)
    else:
        if txt and not txt.endswith("\n"):
            txt += "\n"
        txt += line + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(txt)


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


def shared_state_warnings(projects):
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


def _already_ran(state, stage, key):
    try:
        with open(_marker(state, stage), encoding="utf-8") as f:
            return f.read().strip() == key
    except FileNotFoundError:
        return False


def _mark_ran(state, stage, key):
    path = _marker(state, stage)
    atomic_write(path, key + "\n")


def _runs_today(state, now):
    path = os.path.join(state, "runs", "runs.jsonl")
    today = now.date()
    count = 0
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (rec.get("stage") or rec.get("loop")) not in JOBS:
                    continue
                raw = rec.get("ts") or rec.get("timestamp") or rec.get("date")
                if not raw:
                    continue
                try:
                    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if ts.date() == today:
                    count += 1
    except FileNotFoundError:
        return 0
    return count


def _last_served(state):
    """Newest mtime among a project's scheduler slot markers, or 0.0 if it has
    never been served. Used to order the tick least-recently-served first so a
    project can never be permanently starved by its registry position when
    several fall due in the same slot."""
    d = os.path.join(state, "scheduler")
    try:
        return max((os.path.getmtime(os.path.join(d, f)) for f in os.listdir(d)), default=0.0)
    except FileNotFoundError:
        return 0.0


def _due_stage_count(values, now, window):
    """How many stages this project has due (and not yet run this slot check is
    left to the caller) — used only to warn when max_runs can't cover demand."""
    n = 0
    for stage in JOBS:
        spec = (values.get("SCHED_" + stage.upper()) or JOBS[stage][3]).strip()
        try:
            if _slot_key(stage, spec, now, window):
                n += 1
        except ValueError:
            pass
    return n


def _run_stage(home, project, config, stage, run, timeout=None):
    cmd = [os.path.join(home, "bin", "cadence"), "--config", config]
    if stage == "conduct":
        cmd.append("conduct")
    else:
        cmd.extend(["run", stage])
    env = os.environ.copy()
    env["CADENCE_CONFIG"] = config
    return run(cmd, cwd=project, env=env, timeout=timeout)


def _execute(home, project, config, stage, run, timeout):
    """Run one admitted pick and describe the outcome. Never raises: one
    crashed or hung run must not sink the tick or the other pool slots.
    subprocess.run kills the child itself on timeout, so a timed-out run frees
    its slot at once — the fast path in front of run-loop.sh's 2h lock reclaim."""
    try:
        proc = _run_stage(home, project, config, stage, run, timeout)
        return ("exit %d" % proc.returncode, proc.returncode != 0)
    except subprocess.TimeoutExpired as e:
        return ("failed (timed out after %ss; child killed)" % e.timeout, True)
    except Exception as e:  # isolation is the point: report it, never propagate
        return ("failed (%s)" % e, True)


def tick(env, now=None, run=subprocess.run):
    home = env.get("CADENCE_HOME") or HOME
    now = now or datetime.now(timezone.utc)
    window = max(1, _int_env(env, "CADENCE_SCHEDULER_WINDOW_MINUTES", 5))
    # MAX_RUNS is the per-tick throughput ceiling (how many runs are launched);
    # CONCURRENCY is the width (how many run at once). A twenty-project fleet
    # raises MAX_RUNS to cover demand and keeps CONCURRENCY small for API-rate
    # and cost safety; a tick lasts roughly ceil(MAX_RUNS / CONCURRENCY) times
    # the longest run. The defaults reproduce the old behaviour exactly.
    max_runs = _int_env(env, "CADENCE_SCHEDULER_MAX_RUNS", 1)
    concurrency = max(1, _int_env(env, "CADENCE_SCHEDULER_CONCURRENCY", 4))
    # Wall-clock cap per run; 0 disables it. subprocess.run kills the child on
    # expiry, so a hung model call cannot hold a pool slot forever. This sits
    # above ORCH_TIMEOUT (default 2700s), which bounds only the model call
    # inside the run; run-loop.sh's 2h stale-lock reclaim is the coarser backstop.
    timeout = _int_env(env, "CADENCE_SCHEDULER_RUN_TIMEOUT", 3600) or None
    projects = read_projects(projects_file(env))
    failed = 0

    if not projects:
        print(f"scheduler: no projects in {projects_file(env)}")
        return 0

    for w in shared_state_warnings(projects):
        print(w, file=sys.stderr)

    # Resolve the scheduled projects, then order them least-recently-served first.
    # Registry order alone lets projects sharing a slot starve the ones behind them
    # once max_runs is spent (a later project with identical SCHED offsets never gets
    # a turn); ordering by last-served makes the neediest project lead each tick, so
    # service rotates and no project is permanently skipped. Ties keep registry order.
    candidates = []
    for idx, item in enumerate(projects):
        values = read_env_file(item["config"])
        if (values.get("CADENCE_SCHEDULED") or "").lower() not in TRUE:
            print(f"{item['project']}: skipped (CADENCE_SCHEDULED not enabled)")
            continue
        state = _path_value(values.get("CADENCE_STATE_DIR"), os.path.expanduser("~/.cadence"))
        candidates.append((item, values, state, idx))
    candidates.sort(key=lambda c: (_last_served(c[2]), c[3]))

    # Under-provisioning signal: if more projects have work due than one tick can
    # serve, say so — that is exactly the condition that produced silent starvation.
    due = sum(1 for _i, v, _s, _x in candidates if _due_stage_count(v, now, window))
    if due > max_runs:
        print(f"scheduler: {due} projects due but max_runs={max_runs} — raise "
              f"CADENCE_SCHEDULER_MAX_RUNS so none are starved", file=sys.stderr)

    # Admission (serial): walk candidates in fairness order and pick at most one
    # due stage per project until max_runs picks are collected. Selecting per
    # project *before* dispatching is what guarantees a project never runs twice
    # in one tick — run-loop.sh's per-project lock is only a backstop.
    picks = []
    for item, values, state, _idx in candidates:
        if len(picks) >= max_runs:
            break
        project, config = item["project"], item["config"]
        daily_cap = _int_env(values, "CADENCE_DAILY_RUN_CAP",
                             _int_env(env, "CADENCE_DAILY_RUN_CAP", 0))
        if daily_cap > 0 and _runs_today(state, now) >= daily_cap:
            print(f"{project}: skipped (CADENCE_DAILY_RUN_CAP={daily_cap} reached)")
            continue
        # Dedup is per (stage, slot) only — a project is never excluded as a whole,
        # so two stages due in the same window each get their turn (across ticks),
        # rather than the first one silently starving the rest.
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
            # Mark at admission, not completion: the marker means "this slot was
            # served", which is true once the launch is committed. launchd
            # coalesces ticks so they never overlap, and run-loop.sh skips a
            # duplicate launch of a stage already in flight, so a run spanning
            # several tick intervals cannot be double-launched for its slot.
            # Marking here also stamps _last_served at selection time, which is
            # what the fairness rotation keys on. (The old code marked after the
            # child returned, but wrote the marker even on failure — semantics
            # are unchanged for every case except a crash inside run() itself.)
            _mark_ran(state, stage, key)
            picks.append((project, config, stage))
            break

    if not picks:
        print("scheduler: nothing due")
        return failed

    # Dispatch (parallel): the pool is fed in admission order, so when width is
    # scarce the least-recently-served projects still start first. The tick
    # blocks until every run finishes — launchd coalesces ticks, so a long tick
    # delays the next wake rather than overlapping it, and the exit code can
    # honestly report every run it launched.
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_execute, home, project, config, stage, run, timeout)
                   for project, config, stage in picks]
        outcomes = [f.result() for f in futures]
    for (project, _config, stage), (line, bad) in zip(picks, outcomes):
        print(f"{project}: {stage} {line}")
        if bad:
            failed = 1
    return failed


def print_status(env):
    path = projects_file(env)
    print(f"projects: {path}")
    print(f"max runs/tick: {env.get('CADENCE_SCHEDULER_MAX_RUNS') or 1}")
    print(f"concurrency: {env.get('CADENCE_SCHEDULER_CONCURRENCY') or 4}")
    projects = read_projects(path)
    if not projects:
        print("  (none)")
        return 0
    now = datetime.now(timezone.utc).timestamp()
    for item in projects:
        values = read_env_file(item["config"])
        enabled = "yes" if (values.get("CADENCE_SCHEDULED") or "").lower() in TRUE else "no"
        served = ""
        if enabled == "yes":
            state = _path_value(values.get("CADENCE_STATE_DIR"), os.path.expanduser("~/.cadence"))
            ls = _last_served(state)
            if ls == 0.0:
                served = "  last-run=never ⚠ starved"
            else:
                hrs = (now - ls) / 3600
                served = "  last-run=%.1fh ago%s" % (hrs, "  ⚠ starved?" if hrs >= 3 else "")
        print(f"  {item['project']}  scheduled={enabled}{served}  config={item['config']}")
    for w in shared_state_warnings(projects):
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
