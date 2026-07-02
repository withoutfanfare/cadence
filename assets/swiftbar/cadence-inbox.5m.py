#!/usr/bin/env python3
# <xbar.title>Cadence gate inbox</xbar.title>
# <xbar.desc>Tasks awaiting your move across every project, each with one-click stage controls.</xbar.desc>
# <xbar.author>Cadence</xbar.author>
#
# SwiftBar/xbar plugin. Refresh interval is the .5m. in the filename. It
# enumerates registered projects via `cadence overview --json`, reads each
# project's task backend (`cadence linear issues-list` or `cadence tasks list`),
# and groups every task under its single canonical stage (the `stage` field the
# adapters now emit — furthest breadcrumb wins, so a task shows in exactly one
# place). Each task gets a submenu: Advance (grant next gate), Set stage (any
# stage), Hold/Release, and Open. Actions run through cadence-grant.sh, scoped to
# the project config and backend. The badge counts the time-sensitive set (PRs +
# escalations). ponytail: SECTIONS/SET_STAGE mirror docs/LABELS.md.

import json
import os
import re
import shutil
import subprocess

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
CAP = 12  # max tasks expanded per section; the rest collapse to a "+N more" line

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


def emit(line=""):
    print(line)


def run_json(args, timeout=30):
    try:
        out = subprocess.run([CADENCE, *args], capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "no output").strip().splitlines()
        return None, (detail[-1][:120] if detail else "failed")
    try:
        return json.loads(out.stdout), None
    except json.JSONDecodeError as e:
        return None, f"bad JSON: {e}"


def run_text(config, *args, timeout=15):
    cfg = (["--config", config] if config else [])
    try:
        out = subprocess.run([CADENCE, *cfg, *args], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def projects():
    data, err = run_json(["overview", "--json"])
    if not data or not data.get("projects"):
        return [(None, None, "linear")]
    return [(p["name"], p["config"], p.get("backend") or "linear") for p in data["projects"]]


def workspace_url(issues):
    for it in issues or []:
        m = re.match(r"(https://linear\.app/[^/]+/)", it.get("url", ""))
        if m:
            return m.group(1)
    return BOARD


def items_for(config, backend):
    cfg = (["--config", config] if config else [])
    if backend == "file":
        return run_json(cfg + ["tasks", "list"])
    return run_json(cfg + ["linear", "issues-list"])


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
        f'{pre}{title} | bash="{GRANT}" param1={backend} param2="{config or ""}" '
        f'param3="{ident}" param4="{",".join(add)}" param5="{",".join(remove)}" '
        f"terminal=false refresh=true"
    )


def render_task(pre, it, config, backend, task_path):
    ident = it["identifier"]
    st = it.get("stage") or {}
    title = (it.get("title") or "").replace("|", "│")
    disp = (title[:48] + "…") if len(title) > 49 else title
    bits = []
    if st.get("gate"):
        bits.append(f"{st['gate']} queued")
    if st.get("hold"):
        bits.append("on hold")
    marker = ("   · " + ", ".join(bits)) if bits else ""
    emit(f"{pre}--{ident}  {disp}{marker}")

    sub = pre + "----"
    adv = st.get("advance")
    if adv:
        emit(action(sub, f"▶ Advance to {STAGE_TITLE.get(adv, adv)}",
                    [adv], [g for g in ALL_GATES if g != adv], config, ident, backend))
    emit(f"{sub}Set stage: | size=11 color=#888888")
    for label, add, remove in SET_STAGE:
        emit(action(sub, f"  {label}", add, remove, config, ident, backend))
    if st.get("hold"):
        emit(action(sub, "Release hold", [], ["agent:hold"], config, ident, backend))
    else:
        emit(action(sub, "Hold", ["agent:hold"], [], config, ident, backend))
    url = it.get("url")
    if backend == "file" and task_path:
        emit(f'{sub}Open tasks.md | bash="/usr/bin/open" param1="{task_path}" terminal=false')
    elif url:
        emit(f"{sub}Open in Linear | href={url}")


# Gather every project first so the badge can total across projects.
sections = []  # (name, config, backend, grouped, board, err, task_path)
badge = 0
for name, config, backend in projects():
    items, err = items_for(config, backend)
    if items is None:
        sections.append((name, config, backend, None, BOARD, err, None))
        continue
    grouped = {k: [] for k in SECTION_KEYS}
    for it in items:
        if is_closed(it):
            continue
        key = section_of(it)
        if key in grouped:
            grouped[key].append(it)
    badge += sum(len(grouped[k]) for k in BADGE_KEYS)
    task_path = run_text(config, "tasks", "path") if backend == "file" else None
    sections.append((name, config, backend, grouped, workspace_url(items), None, task_path))

emit(f"\U0001F4E5 {badge}" if badge else "\U0001F4E5")
emit("---")

multi = len(sections) > 1
for name, config, backend, grouped, board, err, task_path in sections:
    if multi or name:
        tag = " · file" if backend == "file" else ""
        emit(f"{name or 'default'}{tag} | size=12 color=#888888")
    pre = "--" if multi else ""
    if err is not None:
        emit(f"{pre}inbox unavailable: {err} | size=11 color=#d0021b font=Menlo")
        continue

    if not any(grouped.values()):
        emit(f"{pre}Nothing awaiting your move | color=#888888")
    for key, heading, _ in SECTIONS:
        tasks = grouped[key]
        if not tasks:
            continue
        emit(f"{pre}{heading} ({len(tasks)}) | size=12")
        for it in tasks[:CAP]:
            render_task(pre, it, config, backend, task_path)
        if len(tasks) > CAP:
            emit(f"{pre}--+{len(tasks) - CAP} more | href={board}")

    if backend != "file":
        emit(f"{pre}Open board | href={board}")

emit("---")
emit("Refresh now | refresh=true")
