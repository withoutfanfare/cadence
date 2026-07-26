#!/usr/bin/env python3
"""cadence brief — the decision brief a human reads before granting a gate.

Pure rendering and parsing: no Linear access, no writes, no judgement. A loop
hands over the facts it already knows as JSON; this prints the markdown comment
the human reads, ending in a machine-readable marker so the queue, the reader
and the menu bar can recover the brief from a comment body.

The point of a brief is that it is brief. Over-long fields are truncated rather
than rejected: a hard error mid-run would cost the whole run and park the issue
on agent:needs-attention over a formatting slip.
"""
import argparse
import json
import re
import sys

MARKER = "<!-- cadence-brief v1 "
MARKER_END = " -->"

RISKS = ("low", "medium", "high")

REQUIRED = ("loop", "issue", "did", "unsure", "check_first", "risk")

# Character caps per field. A brief that does not fit on a phone screen is not a
# brief. ponytail: fixed character caps, not a token count — raise them if the
# briefs start reading as truncated rather than terse.
CAPS = {"did": 300, "unsure": 200, "check_first": 200}

HEADINGS = {
    "triage": "Triaged — your move",
    "spec": "Spec ready — your move",
    "build": "Draft PR open — your move",
    "revise": "Revisions pushed — your move",
    "roadmap": "Proposal — your move",
}

NEXT_GATE_HINT = {
    "agent:spec": "add `agent:spec` to let the spec loop write the spec",
    "agent:build": "add `agent:build` to let the build loop open a PR",
    "agent:revise": "add `agent:revise` to send the review notes back",
}


def _one_line(value, cap):
    """Collapse to a single line and cap it. Returns (text, was_truncated)."""
    text = " ".join(str(value or "").split())
    if len(text) <= cap:
        return text, False
    return text[: cap - 1].rstrip() + "…", True


def validate(payload):
    """Return a list of problem strings; empty means the payload is renderable."""
    problems = []
    for key in REQUIRED:
        if not str(payload.get(key) or "").strip():
            problems.append(f"missing or empty: {key}")
    risk = str(payload.get("risk") or "").strip().lower()
    if risk and risk not in RISKS:
        problems.append(f"risk must be one of {', '.join(RISKS)}, got {risk!r}")
    return problems


def render(payload):
    """Render the brief as markdown, ending in the parseable marker line."""
    problems = validate(payload)
    if problems:
        raise ValueError("; ".join(problems))

    fields, truncated = {}, []
    for key, cap in CAPS.items():
        fields[key], was_cut = _one_line(payload.get(key), cap)
        if was_cut:
            truncated.append(key)

    loop = str(payload["loop"]).strip().lower()
    risk = str(payload["risk"]).strip().lower()
    reasons = [str(r).strip() for r in (payload.get("risk_reasons") or []) if str(r).strip()]

    lines = [
        f"🤖 **{HEADINGS.get(loop, loop + ' — your move')}**",
        "",
        f"**What I did.** {fields['did']}",
        "",
        f"**Least sure about.** {fields['unsure']}",
        "",
        f"**Check first.** {fields['check_first']}",
        "",
        f"**Risk: {risk}**" + (f" — {'; '.join(reasons)}" if reasons else ""),
    ]

    hint = NEXT_GATE_HINT.get(str(payload.get("next_gate") or "").strip())
    if hint:
        lines += ["", f"**Your move:** {hint}."]

    marker = dict(payload)
    marker.update(fields)
    marker["risk"] = risk
    if truncated:
        marker["truncated"] = sorted(truncated)
    lines += ["", MARKER + json.dumps(marker, separators=(",", ":"), sort_keys=True) + MARKER_END]
    return "\n".join(lines)


_MARKER_RE = re.compile(re.escape(MARKER) + r"(\{.*?\})" + re.escape(MARKER_END), re.DOTALL)


def parse(text):
    """Recover the brief payload from a rendered comment body, or None."""
    match = _MARKER_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


# Paths whose change deserves a human read regardless of how small the diff is.
# ponytail: substring match on the path, not taint analysis — move to a
# configured list per project if the false-positive rate starts to grate.
SENSITIVE_PATTERNS = (
    "auth", "login", "session", "password", "token", "secret", "credential",
    "payment", "billing", "invoice", "charge", "refund", "price", "vat",
    "migration", ".env", "config/", "middleware", "webhook",
    "permission", "policy", "gate", "role",
)

_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "cypress", "e2e"}

BIG_DIFF = 600
MODERATE_DIFF = 200
MANY_FILES = 12


def _is_test(path):
    """Recognise conventional test paths without substring false positives.

    `LatestWidget.php` and `ContestEntry.php` are source files, despite containing
    the letters "test". Directory names and filename boundaries are the useful
    signals here.
    """
    clean = str(path or "").replace("\\", "/").strip("/")
    parts = [part for part in clean.split("/") if part]
    if not parts:
        return False
    if any(part.lower() in _TEST_DIRS for part in parts[:-1]):
        return True
    stem = parts[-1].rsplit(".", 1)[0]
    lower = stem.lower()
    return (
        lower.startswith(("test_", "test-"))
        or lower.endswith(("_test", "-test", ".test", ".spec"))
        or bool(re.search(r"(?:^Test[A-Z]|Test$)", stem))
    )


def score(facts):
    """Score a change low/medium/high with the reasons that drove it.

    Highest band wins: any single high signal makes the whole change high.
    """
    files = [str(f) for f in (facts.get("files") or [])]
    churn = int(facts.get("insertions") or 0) + int(facts.get("deletions") or 0)
    source_files = [f for f in files if not _is_test(f)]
    # Derive tests_changed from the file list when the caller does not state it.
    # Callers that pass a flat `false` (a spec naming both a service and its test,
    # say) would otherwise be scored medium for "no test changed" and, under the
    # default low ceiling, escalate nearly every substantive issue. Deriving it
    # fixes that at the source rather than at each call site.
    tests_changed = facts.get("tests_changed")
    tests_changed = (any(_is_test(f) for f in files) if tests_changed is None
                     else bool(tests_changed))
    gates_passed = facts.get("gates_passed", True)

    high, medium = [], []

    sensitive = sorted({p for f in files for p in SENSITIVE_PATTERNS if p in f.lower()})
    if sensitive:
        high.append("touches sensitive paths: " + ", ".join(sensitive))
    if not gates_passed:
        high.append("gates did not pass")
    # A blocking review finding is a separate signal from the gates: the gates are
    # CI, this is a reviewer saying "do not ship as-is". A small, clean, well-tested
    # diff can still carry one, and it would otherwise be banded `low` — the band a
    # reader skims past. Kept as its own fact rather than folded into
    # `gates_passed`, so the two never get conflated.
    if facts.get("blocking_review"):
        high.append("the folded review raised a blocking finding")
    if churn > BIG_DIFF:
        high.append(f"very large diff ({churn} lines)")

    if source_files and not tests_changed:
        medium.append(f"no test changed alongside {len(source_files)} source file(s)")
    if len(files) > MANY_FILES:
        medium.append(f"{len(files)} files touched")
    if churn > MODERATE_DIFF:
        medium.append(f"moderate diff ({churn} lines)")

    if high:
        return {"risk": "high", "reasons": high}
    if medium:
        return {"risk": "medium", "reasons": medium}
    if not files:
        return {"risk": "low", "reasons": ["no file changes reported"]}
    return {"risk": "low", "reasons": [f"{len(files)} file(s), {churn} lines, tests touched"
                                       if tests_changed else f"{len(files)} test file(s)"]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="cadence-brief")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--payload", help="brief JSON (default: read stdin)")
    p = sub.add_parser("parse")
    p.add_argument("--file", help="comment body file (default: read stdin)")
    k = sub.add_parser("risk")
    k.add_argument("--facts", help="facts JSON (default: read stdin)")
    args = ap.parse_args(argv)

    if args.cmd == "risk":
        raw = args.facts if args.facts else sys.stdin.read()
        print(json.dumps(score(json.loads(raw)), separators=(",", ":"), sort_keys=True))
        return 0
    if args.cmd == "render":
        raw = args.payload if args.payload else sys.stdin.read()
        try:
            print(render(json.loads(raw)))
        except ValueError as exc:
            print(f"cadence brief: {exc}", file=sys.stderr)
            return 2
    else:
        if args.file:
            with open(args.file, encoding="utf-8") as fh:
                text = fh.read()
        else:
            text = sys.stdin.read()
        found = parse(text)
        if found is None:
            return 1
        print(json.dumps(found, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
