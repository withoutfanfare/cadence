#!/usr/bin/env python3
"""cadence schedule — config-driven launchd schedules.

Reads SCHED_<STAGE> from the environment (falling back to defaults that reproduce
the historical hourly, staggered schedule), parses the cadence, and renders launchd
plists. Every cadence is clock-aligned to midnight — predictable firing times; stagger
loops by giving them different minutes.

Format (value of each SCHED_<STAGE>):
  :MM       hourly, at minute MM         (e.g. :15 -> every hour at :15)
  Nh        every N hours, at minute 0   (e.g. 4h  -> 00:00, 04:00, 08:00, ...)
  Nh@MM     every N hours, at minute MM  (e.g. 4h@30 -> 00:30, 04:30, 08:30, ...)
"""
import os
import re
import sys

ENGINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.dirname(ENGINE)

# stage -> (launchd label, runner kind, runner arg, default spec)
JOBS = {
    "triage":  ("com.cadence.loop-triage",  "run-loop", "triage",  ":00"),
    "spec":    ("com.cadence.loop-spec",    "run-loop", "spec",    ":15"),
    "build":   ("com.cadence.loop-build",   "run-loop", "build",   ":30"),
    "revise":  ("com.cadence.loop-revise",  "run-loop", "revise",  ":45"),
    "advance": ("com.cadence.loop-advance", "run-loop", "advance", ":55"),
    "conduct": ("com.cadence.conduct",      "cadence",  "conduct", "3h"),
}

_MIN_RE = re.compile(r'^\s*:(\d{1,2})\s*$')
_HR_RE = re.compile(r'^\s*(\d+)\s*h\s*(?:@\s*(\d{1,2}))?\s*$')


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
            try:
                parse_spec(spec_for(stage))
            except ValueError as e:
                print(f"  ❌ SCHED_{stage.upper()}: {e}", file=sys.stderr)
                bad += 1
        return 1 if bad else 0

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

    print("usage: cadence schedule [show|apply]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
