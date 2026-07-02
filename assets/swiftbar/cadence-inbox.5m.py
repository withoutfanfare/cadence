#!/usr/bin/env python3
# <xbar.title>Cadence gate inbox</xbar.title>
# <xbar.desc>Issues/tasks awaiting your move across every project, with one-click gate grants.</xbar.desc>
# <xbar.author>Cadence</xbar.author>
#
# SwiftBar/xbar plugin. Refresh interval is the .5m. in the filename. It
# enumerates registered projects via `cadence overview --json`, then reads each
# project's task backend — `cadence linear issues-list` for Linear projects, or
# `cadence tasks list` for file-backed ones — bucketed by gate label. File
# projects also get an "Open tasks" backlog of ungated open tasks so the whole
# task file is visible. The badge counts only the time-sensitive set (PRs +
# escalations) across all projects. Grants ADD the next-gate label, scoped to
# the project's config and backend. ponytail: GATES mirrors docs/LABELS.md.

import json
import os
import re
import shutil
import subprocess
import sys

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
CAP = 12  # max issues expanded per gate/backlog; the rest collapse to a "+N more" line

# (gate label, heading, next-gate label to add, counts_toward_badge)
GATES = [
    ("agent:needs-human", "Needs a human decision", "agent:spec", True),
    ("agent:pr-open", "PR open · review or merge", "agent:revise", True),
    ("agent:revised", "Revised · re-review", "agent:revise", True),
    ("agent:specced", "Specced · grant build", "agent:build", False),
    ("agent:triaged", "Triaged · grant spec", "agent:spec", False),
]
GATE_LABELS = {label for label, _, _, _ in GATES}
# Labels that mean an ungated task is not idle backlog (parked, in flight, failed).
NON_BACKLOG = {"agent:hold", "agent:superseded", "agent:claimed", "agent:needs-attention", "Stale"}


def emit(line=""):
    print(line)


def run_json(args, timeout=30):
    """Run a cadence subcommand and parse JSON, returning (data, error)."""
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


def projects():
    """Registered projects as (name, config, backend). Falls back to default."""
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


def backlog_of(issues):
    """Ungated, open, not-parked tasks — visible so the file backlog isn't hidden."""
    out = []
    for it in issues:
        labels = set(it.get("labels") or [])
        if labels & GATE_LABELS or labels & NON_BACKLOG:
            continue
        if (it.get("status") or "open").lower() in ("done", "cancelled", "closed"):
            continue
        out.append(it)
    return out


# Gather every project first so the badge can total across projects.
sections = []   # (name, config, backend, buckets, backlog, board, err)
badge = 0
for name, config, backend in projects():
    issues, err = items_for(config, backend)
    if issues is None:
        sections.append((name, config, backend, None, None, BOARD, err))
        continue
    buckets = {label: [] for label, _, _, _ in GATES}
    for it in issues:
        labels = it.get("labels", [])
        for label in buckets:
            if label in labels:
                buckets[label].append(it)
    badge += sum(len(buckets[l]) for l, _, _, counts in GATES if counts)
    backlog = backlog_of(issues) if backend == "file" else []
    sections.append((name, config, backend, buckets, backlog, workspace_url(issues), None))

emit(f"\U0001F4E5 {badge}" if badge else "\U0001F4E5")
emit("---")

multi = len(sections) > 1
for name, config, backend, buckets, backlog, board, err in sections:
    if multi or name:
        tag = " · file" if backend == "file" else ""
        emit(f"{name or 'default'}{tag} | size=12 color=#888888")
    pre = "--" if multi else ""
    if err is not None:
        emit(f"{pre}inbox unavailable: {err} | size=11 color=#d0021b font=Menlo")
        continue

    gated = any(buckets.values())
    if not gated and not backlog:
        emit(f"{pre}Nothing awaiting your move | color=#888888")
    for label, heading, nxt, _ in GATES:
        items = buckets[label]
        if not items:
            continue
        emit(f"{pre}{heading} ({len(items)}) | size=12")
        for it in items[:CAP]:
            ident = it["identifier"]
            title = it.get("title", "").replace("|", "│")
            disp = (title[:48] + "…") if len(title) > 49 else title
            url = it.get("url")
            href = f" | href={url}" if url else ""
            emit(f"{pre}--{ident}  {disp}{href}")
            if url:
                emit(f"{pre}----Open in Linear | href={url}")
            emit(
                f'{pre}----Grant {nxt} | bash="{GRANT}" param1={ident} param2={nxt} '
                f'param3="{config or ""}" param4={backend} terminal=false refresh=true'
            )
        if len(items) > CAP:
            emit(f"{pre}--+{len(items) - CAP} more | href={board}")

    # File projects: show the ungated open backlog so the task file is visible.
    if backend == "file" and backlog:
        emit(f"{pre}Open tasks · backlog ({len(backlog)}) | size=12 color=#888888")
        for it in backlog[:CAP]:
            ident = it["identifier"]
            title = it.get("title", "").replace("|", "│")
            disp = (title[:48] + "…") if len(title) > 49 else title
            emit(f"{pre}--{ident}  {disp} | font=Menlo size=12")
        if len(backlog) > CAP:
            emit(f"{pre}--+{len(backlog) - CAP} more in {name or 'tasks.md'} | size=11 color=#888888")

    if backend != "file":
        emit(f"{pre}Open board | href={board}")

emit("---")
emit("Refresh now | refresh=true")
