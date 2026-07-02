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
