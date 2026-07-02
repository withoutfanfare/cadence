#!/usr/bin/env python3
"""cadence advance — deterministic decision core for autonomous mode.

Pure logic only: no Linear access, no gate writes, no agent judgement. The
advancer skill (Plan 2) gathers the facts, calls these helpers, and acts on the
result. Subcommands: decide, criteria, repairs.

`decide()` trusts the state blob it is handed. The `repairs` field MUST be the
persisted count from `cadence advance repairs get <issue>` — if it is omitted the
repair cap cannot bound the loop. `decide()` stays pure (no file reads); coercing
the counts here just stops a missing/blank/stringy value from disabling the cap.
"""
import argparse
import json
import os
import re
import sys

_TRUE = {"1", "true", "on", "yes"}


def config(env):
    def _int(key, default):
        try:
            return int(env.get(key) or default)
        except (TypeError, ValueError):
            return default
    return {
        "autonomous": (env.get("AUTONOMOUS") or "").strip().lower() in _TRUE,
        "max_issues": _int("AUTO_MAX_ISSUES_PER_RUN", 1),
        "max_repairs": _int("AUTO_MAX_REPAIRS", 3),
        "cost_ceiling": _int("AUTO_COST_CEILING", 0),
    }


def _act(action, reason, bump_repairs=False, reset_repairs=False):
    return {"action": action, "reason": reason,
            "bump_repairs": bump_repairs, "reset_repairs": reset_repairs}


def _coerce_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def decide(state):
    """Map an auto issue's state to one action. See module/plan for the contract."""
    if state.get("hold") or not state.get("auto"):
        return _act("skip", "not an auto issue, or on hold")
    if state.get("issues_done", 0) >= state.get("max_issues", 1):
        return _act("cap-stop", "per-run issue cap reached")

    resting = state.get("resting")
    bar = state.get("bar") or {}

    if resting == "triaged":
        if bar.get("triage_clean") and bar.get("criteria_present"):
            return _act("grant-spec", "triage clean, acceptance criteria stubbed")
        return _act("escalate", "triage incomplete or no criteria stub")

    if resting == "specced":
        if bar.get("criteria_present"):
            return _act("grant-build", "spec has checkable acceptance criteria")
        return _act("escalate", "spec missing checkable acceptance criteria")

    if resting in ("pr-open", "revised"):
        full = bool(bar.get("gates") and bar.get("criteria_met") and bar.get("review_clean"))
        if full:
            return _act("accept", "full bar clear — ready for human merge", reset_repairs=True)
        # `repairs` must be the count from `cadence advance repairs get <issue>`;
        # coerce defensively so a missing/blank/stringy value can't silently reset
        # the count and let the repair cap never fire (unbounded model spend).
        # `max_repairs: 0` therefore means "escalate immediately" — that is intended.
        repairs = _coerce_int(state.get("repairs"))
        max_repairs = _coerce_int(state.get("max_repairs"))
        if repairs < max_repairs:
            return _act("repair", f"bar not met — repairing ({repairs}/{max_repairs})",
                        bump_repairs=True)
        return _act("escalate", f"still failing after {repairs}/{max_repairs} repairs")

    return _act("skip", "not at an advanceable resting label")


_CRIT_HEADING = re.compile(r'^\s*(#+\s*|\*\*\s*)?acceptance criteria\b', re.IGNORECASE)
_HEADING = re.compile(r'^\s*(#+\s+|\*\*)')
_ITEM = re.compile(r'^\s*(?:[-*]\s+(?:\[[ xX]\]\s+)?|\d+\.\s+)(.*\S)\s*$')


def parse_criteria(markdown):
    """Return the acceptance-criteria list items from a spec document, or []."""
    lines = (markdown or "").splitlines()
    out, in_section = [], False
    for line in lines:
        if _CRIT_HEADING.match(line):
            in_section = True
            continue
        if in_section and _HEADING.match(line):
            break  # next heading ends the section
        if in_section:
            m = _ITEM.match(line)
            if m:
                out.append(m.group(1).strip())
    return out


def repairs_path(state_dir):
    return os.path.join(state_dir, "runs", "auto-repairs.json")


def _load_repairs(state_dir):
    try:
        with open(repairs_path(state_dir), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def _save_repairs(state_dir, data):
    path = repairs_path(state_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def get_repairs(state_dir, issue):
    return int(_load_repairs(state_dir).get(issue, 0))


def bump_repairs(state_dir, issue):
    data = _load_repairs(state_dir)
    data[issue] = int(data.get(issue, 0)) + 1
    _save_repairs(state_dir, data)
    return data[issue]


def reset_repairs(state_dir, issue):
    data = _load_repairs(state_dir)
    if issue in data:
        del data[issue]
        _save_repairs(state_dir, data)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="cadence-advance")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--state", help="state JSON (default: read stdin)")
    c = sub.add_parser("criteria")
    c.add_argument("--file", help="spec markdown file (default: read stdin)")
    r = sub.add_parser("repairs")
    r.add_argument("op", choices=["get", "bump", "reset"])
    r.add_argument("issue")
    args = ap.parse_args(argv)
    if args.cmd == "decide":
        raw = args.state if args.state else sys.stdin.read()
        print(json.dumps(decide(json.loads(raw)), separators=(",", ":")))
    elif args.cmd == "criteria":
        if args.file:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = sys.stdin.read()
        print(json.dumps(parse_criteria(text), separators=(",", ":")))
    elif args.cmd == "repairs":
        sd = os.environ.get("CADENCE_STATE_DIR") or os.path.expanduser("~/.cadence")
        if args.op == "get":
            print(get_repairs(sd, args.issue))
        elif args.op == "bump":
            print(bump_repairs(sd, args.issue))
        else:
            reset_repairs(sd, args.issue)


if __name__ == "__main__":
    main()
