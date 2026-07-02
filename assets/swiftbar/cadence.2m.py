#!/usr/bin/env python3
# <xbar.title>Cadence</xbar.title>
# <xbar.desc>One menu for every Cadence project: honest status, what's waiting on you, and per-project controls.</xbar.desc>
# <xbar.author>Cadence</xbar.author>
#
# SwiftBar/xbar plugin (refresh interval is the .2m. in the filename). It merges
# the old loop-monitor and gate-inbox into one menu:
#   - the menu-bar glyph answers the only question that matters — do I need to do
#     anything? (a broken run, or tasks sitting at a human gate)
#   - each project shows a plain-English status + relative freshness, then the
#     tasks awaiting your move, then a "Stages & controls" submenu with the
#     technical detail (per-stage results, pause/run, logs) tucked out of the way.
# Status comes from `cadence overview --json`; tasks from each project's backend
# (`linear issues-list` or `tasks list`); gate clicks go through cadence-grant.sh.
# ponytail: SECTIONS/SET_STAGE mirror docs/LABELS.md. Run `cadence.2m.py selftest`
# to check the status/relative-time logic without touching cadence.

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

os.environ["PATH"] = os.pathsep.join([
    os.path.expanduser("~/.local/bin"),
    "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
    os.environ.get("PATH", ""),
])

CADENCE = shutil.which("cadence") or os.path.expanduser("~/.local/bin/cadence")
GRANT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cadence-grant.sh")
)
BOARD = "https://linear.app/"
CAP = 12  # max tasks shown per section; the rest collapse to a "+N more" line
WORK_STAGES = ["triage", "spec", "build", "revise"]

# Honest per-project status. overview already derives health (paused / failed /
# ok / idle); we relabel it in plain words and let a task count and relative time
# carry the trust. Glyph precedence mirrors the menu bar: broken > needs-you >
# paused > running > idle.
OP_WORD = {"failed": "needs attention", "paused": "paused", "ok": "active", "idle": "idle"}

# (stage key, heading, counts_toward_badge). Order = display order.
SECTIONS = [
    ("needs-human",     "Needs a human decision",       True),
    ("needs-attention", "Run failed · needs attention", False),
    ("pr-open",         "PR open · review or merge",    True),
    ("revised",         "Revised · re-review",          True),
    ("specced",         "Specced · grant build",        False),
    ("triaged",         "Triaged · grant spec",         False),
    ("backlog",         "Open · backlog",               False),
]
SECTION_KEYS = [k for k, _, _ in SECTIONS]
BADGE_KEYS = {k for k, _, counts in SECTIONS if counts}

ALL_GATES = ["agent:spec", "agent:build", "agent:revise"]
STAGE_TITLE = {"agent:spec": "Spec", "agent:build": "Build", "agent:revise": "Revise"}

# Set stage -> (labels to add, labels to remove). The menu writes only gate
# labels; "Triage" is the one sanctioned breadcrumb clear (force re-triage).
SET_STAGE = [
    ("Triage", [],                ["agent:triaged"] + ALL_GATES),
    ("Spec",   ["agent:spec"],    ["agent:build", "agent:revise"]),
    ("Build",  ["agent:build"],   ["agent:spec", "agent:revise"]),
    ("Revise", ["agent:revise"],  ["agent:spec", "agent:build"]),
]

CLOSED_STATUS = {"done", "cancelled", "canceled", "closed"}
CLOSED_STATE_TYPE = {"completed", "canceled", "cancelled"}


OUT = []  # menu lines are buffered so the menu-bar summary (first line) can be
          # decided after every project has been tallied.


def emit(line=""):
    OUT.append(line)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def rel(ts, now=None):
    """ISO timestamp -> 'just now' / '5m ago' / '3h ago' / '2d ago' (None if unparseable)."""
    dt = parse_iso(ts) if isinstance(ts, str) else ts
    if not dt:
        return None
    now = now or datetime.now(timezone.utc)
    secs = max(0.0, (now - dt).total_seconds())
    if secs < 90:
        return "just now"
    mins = secs / 60
    if mins < 60:
        return "%dm ago" % mins
    hours = mins / 60
    if hours < 24:
        return "%dh ago" % hours
    return "%dd ago" % (hours / 24)


def last_active_ts(p):
    """Freshest timestamp for a project: from last_activity's [stamp] or any stage."""
    cands = []
    m = re.match(r"\[([^\]]+)\]", p.get("last_activity") or "")
    if m:
        cands.append(m.group(1))
    for st in (p.get("stages") or {}).values():
        if st and st.get("ts"):
            cands.append(st["ts"])
    dts = [d for d in (parse_iso(c) for c in cands) if d]
    return max(dts) if dts else None


def status_of(p, need_you, now=None):
    """(glyph, subline) for a project header. Pure — covered by selftest."""
    health = p.get("health") or "idle"
    scheduled = p.get("scheduled", True)
    ra = rel(last_active_ts(p), now=now)

    if health == "failed":
        glyph = "⚠️"          # warning
    elif need_you:
        glyph = "\U0001f534"            # red circle
    elif health == "paused":
        glyph = "⏸"               # pause
    elif health == "ok":
        glyph = "\U0001f7e2"           # green circle
    else:
        glyph = "⚪"               # white circle (idle)

    bits = []
    if need_you:
        bits.append("%d awaiting you" % need_you)
    if health == "failed":
        bits.append("last run failed")
        bits.append("check logs")
    elif health == "paused":
        bits.append("paused")
    elif health == "idle" and not need_you:
        bits.append("nothing waiting")
    else:
        bits.append(OP_WORD[health])
    if ra:
        bits.append(ra)
    if not scheduled:
        bits.append("not scheduled")
    return glyph, " · ".join(bits)


def run_json(args, timeout=30):
    try:
        out = subprocess.run([CADENCE, *args], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "no output").strip().splitlines()
        return None, (detail[-1][:120] if detail else "failed")
    try:
        return json.loads(out.stdout), None
    except json.JSONDecodeError as e:
        return None, "bad JSON: %s" % e


def run_text(config, *args, timeout=15):
    cfg = (["--config", config] if config else [])
    try:
        out = subprocess.run([CADENCE, *cfg, *args], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def items_for(config, backend):
    cfg = (["--config", config] if config else [])
    if backend == "file":
        return run_json(cfg + ["tasks", "list"])
    return run_json(cfg + ["linear", "issues-list"])


def workspace_url(issues):
    for it in issues or []:
        m = re.match(r"(https://linear\.app/[^/]+/)", it.get("url", ""))
        if m:
            return m.group(1)
    return BOARD


def is_closed(it):
    if (it.get("status") or "").lower() in CLOSED_STATUS:
        return True
    return (it.get("state_type") or "").lower() in CLOSED_STATE_TYPE


def section_of(it):
    st = it.get("stage") or {}
    if st.get("exception") == "superseded":
        return None
    return st.get("exception") or st.get("name") or "backlog"


def action(pre, title, add, remove, config, ident, backend):
    return (
        '%s%s | bash="%s" param1=%s param2="%s" param3="%s" param4="%s" param5="%s" '
        "terminal=false refresh=true"
        % (pre, title, GRANT, backend, config or "", ident,
           ",".join(add), ",".join(remove))
    )


def render_task(pre, it, config, backend, task_path):
    """A task line (at `pre`) with its action submenu one level deeper."""
    ident = it["identifier"]
    st = it.get("stage") or {}
    title = (it.get("title") or "").replace("|", "│")
    disp = (title[:48] + "…") if len(title) > 49 else title
    bits = []
    if st.get("gate"):
        bits.append("%s queued" % st["gate"])
    if st.get("hold"):
        bits.append("on hold")
    marker = ("   · " + ", ".join(bits)) if bits else ""
    emit("%s%s  %s%s" % (pre, ident, disp, marker))

    sub = pre + "--"
    adv = st.get("advance")
    if adv:
        emit(action(sub, "▶ Advance to %s" % STAGE_TITLE.get(adv, adv),
                    [adv], [g for g in ALL_GATES if g != adv], config, ident, backend))
    emit("%sSet stage: | size=11 color=#888888" % sub)
    for label, add, remove in SET_STAGE:
        emit(action(sub, "  " + label, add, remove, config, ident, backend))
    if st.get("hold"):
        emit(action(sub, "Release hold", [], ["agent:hold"], config, ident, backend))
    else:
        emit(action(sub, "Hold", ["agent:hold"], [], config, ident, backend))
    url = it.get("url")
    if backend == "file" and task_path:
        emit('%sOpen tasks.md | bash="/usr/bin/open" param1="%s" terminal=false' % (sub, task_path))
    elif url:
        emit("%sOpen in Linear | href=%s" % (sub, url))


def render_stages_and_controls(pre, p, board, backend, task_path, now=None):
    """The 'Stages & controls' submenu: per-stage results, autonomous line, controls."""
    cfg = p["config"]
    emit("%s▸ Stages & controls" % pre)
    sub = pre + "--"
    stages = p.get("stages") or {}
    for s in WORK_STAGES:
        st = stages.get(s)
        if st:
            ra = rel(st.get("ts"), now=now)
            detail = st.get("result") or "?"
            if ra:
                detail += " · " + ra
        else:
            detail = "idle"
        emit("%s%-8s %s | font=Menlo size=12" % (sub, s, detail))
    auto = "on" if p.get("autonomous") else "off"
    emit("%sAutonomous  %s | font=Menlo size=12 color=#888888" % (sub, auto))

    emit("%s-----" % pre)  # separator inside the submenu (7 dashes: depth-2)
    if p.get("paused"):
        emit('%s▶ Resume project | bash="%s" param1=--config param2="%s" param3=resume terminal=false refresh=true'
             % (sub, CADENCE, cfg))
    else:
        emit('%s⏸ Pause project | bash="%s" param1=--config param2="%s" param3=pause terminal=false refresh=true'
             % (sub, CADENCE, cfg))
    for s in WORK_STAGES:
        emit('%sRun %s now | bash="%s" param1=--config param2="%s" param3=run param4=%s terminal=true'
             % (sub, s, CADENCE, cfg, s))
    emit('%sView logs | bash="%s" param1=--config param2="%s" param3=logs terminal=true'
         % (sub, CADENCE, cfg))
    if backend == "file" and task_path:
        emit('%sOpen tasks.md | bash="/usr/bin/open" param1="%s" terminal=false' % (sub, task_path))
    else:
        emit("%sOpen board | href=%s" % (sub, board))


def render_project(p, now=None):
    config, backend = p["config"], (p.get("backend") or "linear")
    items, err = items_for(config, backend)

    grouped = {k: [] for k in SECTION_KEYS}
    need_you = 0
    board = BOARD
    task_path = None
    if items is not None:
        for it in items:
            if is_closed(it):
                continue
            key = section_of(it)
            if key in grouped:
                grouped[key].append(it)
        need_you = sum(len(grouped[k]) for k in BADGE_KEYS)
        board = workspace_url(items)
        task_path = run_text(config, "tasks", "path") if backend == "file" else None

    glyph, subline = status_of(p, need_you, now=now)
    team = ("  · " + p["team_name"]) if p.get("team_name") else ""
    tag = "  · file" if backend == "file" else ""
    emit("%s %s%s%s" % (glyph, p["name"], team, tag))
    emit("--%s | size=12 color=#888888" % subline)
    emit("-----")

    if err is not None:
        emit("--task list unavailable: %s | size=11 color=#d0021b font=Menlo" % err)
    elif need_you == 0 and not any(grouped.values()):
        emit("--Nothing awaiting your move | color=#888888")
    else:
        for key, heading, _ in SECTIONS:
            tasks = grouped[key]
            if not tasks:
                continue
            emit("--%s (%d) | size=12" % (heading, len(tasks)))
            for it in tasks[:CAP]:
                render_task("--", it, config, backend, task_path)
            if len(tasks) > CAP:
                emit("--+%d more | href=%s" % (len(tasks) - CAP, board))

    emit("-----")
    render_stages_and_controls("--", p, board, backend, task_path, now=now)
    return need_you


def main():
    data, err = run_json(["overview", "--json"])
    if err is not None or data is None:
        print("⚠️ | color=#d0021b")
        print("---")
        print("overview unavailable: %s | size=11 color=#d0021b font=Menlo" % (err or "no data"))
        print("Refresh now | refresh=true")
        return

    projects = data.get("projects") or []
    if not projects:
        print(" | sfimage=arrow.triangle.2.circlepath color=#9aa0a6")
        print("---")
        print("No registered projects | color=#888888")
        print("Register one: | size=11 color=#888888")
        print("cadence schedule register <path> | font=Menlo size=11 color=#888888")
        print("Refresh now | refresh=true")
        return

    badge = 0
    failed_any = paused_any = False
    for i, p in enumerate(projects):
        if i:
            emit("---")
        badge += render_project(p)
        failed_any = failed_any or p.get("health") == "failed"
        paused_any = paused_any or p.get("paused")

    # Menu bar: failed > needs-you > paused > all-clear.
    if failed_any:
        menubar = ("⚠️ %d" % badge) if badge else "⚠️"
    elif badge:
        menubar = "\U0001f4e5 %d" % badge
    elif paused_any:
        menubar = " | sfimage=pause.circle.fill color=#e0a000"
    else:
        menubar = " | sfimage=checkmark.circle color=#2e7d32"

    print(menubar)
    print("---")
    print("\n".join(OUT))
    print("---")
    print("Refresh now | refresh=true")


def _selftest():
    now = datetime(2026, 7, 2, 12, 0, 0, tzinfo=timezone.utc)
    assert rel("2026-07-02T11:59:30Z", now) == "just now"
    assert rel("2026-07-02T11:30:00Z", now) == "30m ago"
    assert rel("2026-07-02T09:00:00Z", now) == "3h ago"
    assert rel("2026-06-30T12:00:00Z", now) == "2d ago"
    assert rel(None, now) is None and rel("garbage", now) is None

    base = {"health": "ok", "scheduled": True, "stages": {},
            "last_activity": "[2026-07-02T10:00:00Z] build — nothing to do"}
    # Failure outranks everything.
    g, sub = status_of({**base, "health": "failed"}, 3, now)
    assert g == "⚠️" and "3 awaiting you" in sub and "last run failed" in sub, sub
    # Waiting work turns the dot red even when the loop itself is healthy.
    g, sub = status_of(base, 2, now)
    assert g == "\U0001f534" and sub.startswith("2 awaiting you") and "2h ago" in sub, sub
    # Healthy, nothing waiting -> green + freshness.
    g, sub = status_of(base, 0, now)
    assert g == "\U0001f7e2" and sub == "active · 2h ago", sub
    # Idle, nothing waiting, never run -> honest white dot, no fake freshness.
    g, sub = status_of({"health": "idle", "scheduled": True, "stages": {}, "last_activity": None}, 0, now)
    assert g == "⚪" and sub == "nothing waiting", sub
    # Paused shows as paused; unscheduled is flagged.
    g, sub = status_of({**base, "health": "paused", "scheduled": False}, 0, now)
    assert g == "⏸" and "paused" in sub and "not scheduled" in sub, sub
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["selftest"]:
        _selftest()
    else:
        main()
