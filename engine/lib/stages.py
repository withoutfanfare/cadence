"""Cadence stage vocabulary — derive a task's single pipeline position from its
labels. Stdlib only, no project facts. Mirrors docs/LABELS.md.
"""

# Furthest-wins: later entries outrank earlier ones.
_STATUS_ORDER = [
    ("agent:triaged", "triaged"),
    ("agent:specced", "specced"),
    ("agent:pr-open", "pr-open"),
    ("agent:revised", "revised"),
]
# Gate labels — the human's pending "go" signal (at most one in practice).
_GATES = [
    ("agent:spec", "spec"),
    ("agent:build", "build"),
    ("agent:revise", "revise"),
]
# Flags that pull a task out of the normal flow; first match is reported.
_EXCEPTIONS = [
    ("agent:needs-attention", "needs-attention"),
    ("agent:needs-human", "needs-human"),
    ("agent:superseded", "superseded"),
]
# Which gate label "Advance" grants next, per current stage.
_ADVANCE = {
    "backlog": "agent:spec",
    "triaged": "agent:spec",
    "specced": "agent:build",
    "pr-open": "agent:revise",
    "revised": "agent:revise",
}


def stage_of(labels):
    have = set(labels or [])
    name = "backlog"
    for label, stage in _STATUS_ORDER:
        if label in have:
            name = stage
    gate = next((g for label, g in _GATES if label in have), None)
    exception = next((e for label, e in _EXCEPTIONS if label in have), None)
    hold = "agent:hold" in have
    advance = None if (gate or exception) else _ADVANCE[name]
    return {
        "name": name,
        "gate": gate,
        "hold": hold,
        "exception": exception,
        "advance": advance,
    }


# Lifecycle position labels are mutually exclusive: an issue rests at exactly one.
# agent:triaged is excluded on purpose — it is sticky (only a human clears it) and
# legitimately coexists with any later position. Order is lifecycle order.
POSITION_LABELS = ["agent:specced", "agent:pr-open", "agent:revised"]
_POSITION_RANK = {lbl: i for i, lbl in enumerate(POSITION_LABELS)}


def resolve_labels(existing, add=None, remove=None):
    """Apply add/remove to a label set, then enforce the single-position invariant
    so an issue can never carry two lifecycle labels at once (the corruption the
    queue's conflict check surfaces).

    Adding a position label makes it the resting one and drops the other two —
    respecting an explicit move, including the backwards revised→pr-open accept
    step. If the caller adds none but two survive (residue from a crashed loop, or
    a human editing labels directly in the tracker), the furthest is kept: any
    write self-heals stray residue. Returns a de-duplicated, order-stable list.
    """
    add = list(add or [])
    remove = set(remove or [])
    out = []
    for lbl in list(existing) + add:
        if lbl in remove or lbl in out:
            continue
        out.append(lbl)
    present = [lbl for lbl in out if lbl in _POSITION_RANK]
    if len(present) <= 1:
        return out
    added_pos = [lbl for lbl in add if lbl in _POSITION_RANK]
    keep = max(added_pos or present, key=_POSITION_RANK.__getitem__)
    return [lbl for lbl in out if lbl not in _POSITION_RANK or lbl == keep]


# Terminal states — a done/cancelled issue is out of play. Matches the Linear
# workflow-state types and the file backend's status values.
TERMINAL_STATES = {"completed", "canceled", "cancelled", "done", "closed"}


def is_terminal(state):
    return (state or "").strip().lower() in TERMINAL_STATES


# DEPS_SATISFIED_WHEN modes — when a blocking task stops blocking its dependants.
DEP_MODES = ("merged", "pr-open")


def dep_satisfied(state, labels, mode="merged"):
    """True when a blocker no longer blocks. `merged` (default): the blocker
    must be terminal (its PR merged and the task completed, or cancelled —
    a dead blocker does not block). `pr-open`: reaching an open PR is enough,
    for unattended runs that sequence work without waiting on human merges."""
    if is_terminal(state):
        return True
    if mode == "pr-open":
        return stage_of(labels)["name"] in ("pr-open", "revised")
    return False


def dep_mode(env):
    """Read DEPS_SATISFIED_WHEN from the config env; unknown values fall back
    to merged (the safe default) rather than erroring an unattended run."""
    mode = (env.get("DEPS_SATISFIED_WHEN") or "merged").strip().lower()
    return mode if mode in DEP_MODES else "merged"


def strip_workflow_labels(labels):
    """Drop the agent:* workflow labels — a done/cancelled issue holds no live
    workflow state, so completing it should clear its gates, status, and flags.
    Non-agent labels (Bug, priority, …) are kept."""
    return [lbl for lbl in labels if not str(lbl).startswith("agent:")]
