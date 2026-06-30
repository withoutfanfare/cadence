#!/usr/bin/env python3
# <xbar.title>Cadence gate inbox</xbar.title>
# <xbar.desc>Linear issues awaiting your move, with one-click gate grants.</xbar.desc>
# <xbar.author>Cadence</xbar.author>
#
# SwiftBar/xbar plugin. Refresh interval is the .5m. in the filename — the
# inbox hits the Linear API, so it polls less often than the local status
# monitor. One `cadence linear issues-list` call, bucketed by gate label.
#
# The badge counts only the time-sensitive set (PRs + escalations); the
# triaged/specced backlogs are pull-at-your-pace pools, listed but not counted.
# Granting a gate only ADDS the next-gate label, mirroring the documented
# manual action (README: "you -> add agent:spec"); the loops clean up their own
# labels. ponytail: GATES mirrors the label vocabulary in docs/LABELS.md.

import json
import os
import re
import shutil
import subprocess
import sys

# SwiftBar runs plugins with a minimal PATH (no shell profile). cadence shells
# out to python3/git internally, so give it a sane PATH before any subprocess.
os.environ["PATH"] = os.pathsep.join([
    os.path.expanduser("~/.local/bin"),
    "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
    os.environ.get("PATH", ""),
])

CADENCE = shutil.which("cadence") or os.path.expanduser("~/.local/bin/cadence")
# Wrapper lives one level up, OUTSIDE the SwiftBar plugin folder — otherwise
# SwiftBar would load it as a (broken, arg-less) plugin of its own.
GRANT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cadence-grant.sh")
)
# Generic fallback for the "Open board" link; refined to the real workspace
# below, derived from the issue URLs the API returns (no hardcoded org slug).
BOARD = "https://linear.app/"
CAP = 12  # max issues expanded per gate; the rest collapse to a "+N more" link


def workspace_url(issues):
    # Linear issue URLs look like https://linear.app/<workspace>/issue/<ID>/...
    for it in issues or []:
        m = re.match(r"(https://linear\.app/[^/]+/)", it.get("url", ""))
        if m:
            return m.group(1)
    return BOARD

ERR = None  # captured failure detail, surfaced in the dropdown

# (gate label, heading, next-gate label to add, counts_toward_badge)
GATES = [
    ("agent:needs-human", "Needs a human decision", "agent:spec", True),
    ("agent:pr-open", "PR open · review or merge", "agent:revise", True),
    ("agent:revised", "Revised · re-review", "agent:revise", True),
    ("agent:specced", "Specced · grant build", "agent:build", False),
    ("agent:triaged", "Triaged · grant spec", "agent:spec", False),
]


def fetch():
    global ERR
    try:
        out = subprocess.run(
            [CADENCE, "linear", "issues-list"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        ERR = f"{type(e).__name__}: {e}"
        return None
    if out.returncode != 0:
        ERR = (out.stderr or out.stdout or "no output").strip().splitlines()[-1][:120]
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as e:
        ERR = f"bad JSON: {e}"
        return None


def emit(line=""):
    print(line)


issues = fetch()
if issues is None:
    emit("\U0001F4E5 ? | color=#d0021b")
    emit("---")
    emit("Gate inbox unavailable | color=#d0021b")
    emit(f"{ERR or 'unknown error'} | size=11 color=#d0021b font=Menlo")
    emit(f"using cadence: {CADENCE} | size=11 color=#888888 font=Menlo")
    emit(f"Open Linear board | href={BOARD}")
    emit("Refresh now | refresh=true")
    sys.exit(0)

BOARD = workspace_url(issues)

buckets = {label: [] for label, _, _, _ in GATES}
for it in issues:
    labels = it.get("labels", [])
    for label in buckets:
        if label in labels:
            buckets[label].append(it)

badge = sum(len(buckets[l]) for l, _, _, counts in GATES if counts)
emit(f"\U0001F4E5 {badge}" if badge else "\U0001F4E5")
emit("---")

if not any(buckets.values()):
    emit("Nothing awaiting your move | color=#888888")
else:
    emit("Awaiting your move | size=11 color=#888888")
    for label, heading, nxt, _ in GATES:
        items = buckets[label]
        if not items:
            continue
        emit(f"{heading} ({len(items)}) | size=12")
        for it in items[:CAP]:
            ident = it["identifier"]
            url = it["url"]
            title = it["title"].replace("|", "│")
            disp = (title[:48] + "…") if len(title) > 49 else title
            emit(f"--{ident}  {disp} | href={url}")
            emit(f"----Open in Linear | href={url}")
            emit(
                f'----Grant {nxt} | bash="{GRANT}" param1={ident} '
                f"param2={nxt} terminal=false refresh=true"
            )
        if len(items) > CAP:
            emit(f"--+{len(items) - CAP} more · open Linear | href={BOARD}")

emit("---")
emit(f"Open Linear board | href={BOARD}")
emit("Refresh now | refresh=true")
