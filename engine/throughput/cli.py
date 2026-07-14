#!/usr/bin/env python3
"""cadence throughput — per-stage rollup of recent runs from runs.jsonl.

Read-only. Aggregates the machine ledger over a day window. Pure aggregate()
and render(); thin file read in main(). Handles the ledger's two quirks: the
stage key is `stage` (triage) or `loop` (spec/build/revise), and some old
records carry no timestamp (counted separately, never silently dropped).
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

STAGES = ["triage", "spec", "build", "revise", "advance", "roadmap", "conduct"]

# stage -> list of (ledger_field, display label). build's PRs are special-cased.
PRODUCED = {
    "triage": [("triaged", "triaged"), ("dupe_candidates", "dupes"), ("stale", "stale")],
    "spec":   [("specced", "specced"), ("superseded", "superseded")],
    "build":  [("built", "built")],
    "revise": [("revised", "revised")],
    "advance": [("advanced", "advanced"), ("accepted", "accepted"),
                ("repaired", "repaired"), ("escalated", "escalated")],
    "roadmap": [("proposed", "proposed"), ("skipped", "skipped")],
    "conduct": [("tagged", "tagged"), ("blocked", "blocked")],
}


def _stage_of(rec):
    return rec.get("stage") or rec.get("loop")


def _ts_of(rec):
    raw = rec.get("ts") or rec.get("timestamp") or rec.get("date")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _int(value):
    # A misbehaving provider can leave a non-numeric ledger field (e.g. "none")
    # in a record; degrade to 0 rather than crash the whole rollup.
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _count_field(rec, field):
    if field == "blocked":
        value = rec.get("skipped_blocked")
    else:
        value = rec.get(field)
    if isinstance(value, list):
        return len(value)
    return _int(value)


def aggregate(records, since=None):
    """Roll records up per stage. since=None counts all; otherwise records
    older than `since` are dropped and records with no timestamp are counted
    under `undated` rather than placed in a window they can't be dated into."""
    stages = {s: {"runs": 0, "errors": 0, "paused": 0, "prs": 0} for s in STAGES}
    for s in STAGES:
        for field, _ in PRODUCED[s]:
            stages[s][field] = 0
    undated = 0
    for rec in records:
        s = _stage_of(rec)
        if s not in stages:
            continue
        if since is not None:
            ts = _ts_of(rec)
            if ts is None:
                undated += 1
                continue
            if ts < since:
                continue
        st = stages[s]
        st["runs"] += 1
        st["errors"] += _int(rec.get("errors"))
        if rec.get("paused"):
            st["paused"] += 1
        for field, _ in PRODUCED[s]:
            st[field] += _count_field(rec, field)
        if s == "build":
            st["prs"] += len(rec.get("pr_numbers") or [])
    return {"stages": stages, "undated": undated}


def _produced_str(stage, st):
    bits = ["%d %s" % (st[field], label) for field, label in PRODUCED[stage] if st.get(field)]
    if stage == "build" and st.get("prs"):
        bits.append("%d PRs" % st["prs"])
    return " · ".join(bits) if bits else "—"


def render(agg, days):
    out = ["── Cadence throughput · last %d days ───────────" % days,
           "           runs   produced                          err"]
    for s in STAGES:
        st = agg["stages"][s]
        out.append("  %-7s %4d    %-34s %3d"
                   % (s, st["runs"], _produced_str(s, st), st["errors"]))
    if agg["undated"]:
        out += ["", "  %d undated run(s) skipped (no timestamp in ledger)" % agg["undated"]]
    return "\n".join(out)


def _read_ledger():
    path = os.path.join(os.environ.get("CADENCE_STATE_DIR", ""), "runs", "runs.jsonl")
    if not os.path.exists(path):
        return []
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    days = 7
    if argv:
        try:
            days = int(argv[0])
        except ValueError:
            sys.stderr.write("cadence throughput: days must be an integer\n")
            sys.exit(2)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    print(render(aggregate(_read_ledger(), since), days))


if __name__ == "__main__":
    main()
