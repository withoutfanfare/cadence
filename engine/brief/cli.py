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
META_CAPS = {"loop": 40, "issue": 80, "next_gate": 40}
RISK_REASON_CAP = 160
MAX_RISK_REASONS = 3

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
    if not isinstance(payload, dict):
        return ["payload must be a JSON object"]
    problems = []
    for key in REQUIRED:
        if not str(payload.get(key) or "").strip():
            problems.append(f"missing or empty: {key}")
    risk = str(payload.get("risk") or "").strip().lower()
    if risk and risk not in RISKS:
        problems.append(f"risk must be one of {', '.join(RISKS)}, got {risk!r}")
    if "risk_reasons" in payload and not isinstance(payload["risk_reasons"], list):
        problems.append("risk_reasons must be a JSON array")
    return problems


def render(payload):
    """Render the brief as markdown, ending in the parseable marker line."""
    problems = validate(payload)
    if problems:
        raise ValueError("; ".join(problems))

    fields, truncated = {}, set()
    for key, cap in CAPS.items():
        fields[key], was_cut = _one_line(payload.get(key), cap)
        if was_cut:
            truncated.add(key)

    meta = {}
    for key, cap in META_CAPS.items():
        meta[key], was_cut = _one_line(payload.get(key), cap)
        if was_cut:
            truncated.add(key)

    loop = meta["loop"].lower()
    risk = str(payload["risk"]).strip().lower()
    raw_reasons = [
        reason for reason in (
            _one_line(raw_reason, RISK_REASON_CAP)
            for raw_reason in (payload.get("risk_reasons") or [])
        ) if reason[0]
    ]
    reasons = []
    for reason, was_cut in raw_reasons[:MAX_RISK_REASONS]:
        reasons.append(reason)
        if was_cut:
            truncated.add("risk_reasons")
    if len(raw_reasons) > MAX_RISK_REASONS:
        truncated.add("risk_reasons")

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

    hint = NEXT_GATE_HINT.get(meta["next_gate"])
    if hint:
        lines += ["", f"**Your move:** {hint}."]

    marker = {
        "loop": loop,
        "issue": meta["issue"],
        "did": fields["did"],
        "unsure": fields["unsure"],
        "check_first": fields["check_first"],
        "risk": risk,
        "risk_reasons": reasons,
    }
    if meta["next_gate"]:
        marker["next_gate"] = meta["next_gate"]
    if truncated:
        marker["truncated"] = sorted(truncated)
    marker_json = json.dumps(marker, separators=(",", ":"), sort_keys=True)
    marker_json = marker_json.replace("-->", "--\\u003e")
    lines += ["", MARKER + marker_json + MARKER_END]
    return "\n".join(lines)


_MARKER_RE = re.compile(
    r"(?:^|\n)" + re.escape(MARKER) + r"(\{[^\n]*\})"
    + re.escape(MARKER_END) + r"[ \t\r\n]*\Z"
)


def parse(text):
    """Recover the brief payload from a rendered comment body, or None."""
    match = _MARKER_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) and not validate(data) else None


# Paths whose change deserves a human read regardless of how small the diff is.
# ponytail: fixed path-token match, not taint analysis — move to a
# configured list per project if the false-positive rate starts to grate.
SENSITIVE_PATTERNS = (
    "auth", "login", "session", "password", "token", "secret", "credential",
    "payment", "billing", "invoice", "charge", "refund", "price", "vat",
    "migration", ".env", "config", "middleware", "webhook",
    "permission", "policy", "gate", "role",
)

_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "cypress", "e2e"}

_NON_EXECUTABLE_SUFFIXES = (
    ".md", ".mdx", ".markdown", ".rst", ".adoc", ".txt", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".woff", ".woff2", ".ttf", ".otf",
)

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


def _is_non_executable(path):
    """Recognise documentation and static assets that do not need code tests."""
    name = str(path or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
    return (
        name.endswith(_NON_EXECUTABLE_SUFFIXES)
        or name in {"readme", "license", "copying", "changelog", "authors", "contributing"}
    )


def _sensitive_matches(path):
    """Return sensitive path tokens without matching words such as Aggregate."""
    if _is_non_executable(path):
        return set()
    clean = str(path or "").replace("\\", "/").strip("/")
    components = [part for part in clean.split("/") if part]
    words = []
    for component in components:
        split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", component)
        words.extend(re.findall(r"[a-z0-9]+", split_camel.lower()))

    matched = set()
    for pattern in SENSITIVE_PATTERNS:
        if pattern == ".env":
            if any(part.lower() == ".env" or part.lower().startswith(".env.")
                   for part in components):
                matched.add(pattern)
        elif pattern in words or pattern + "s" in words:
            matched.add(pattern)
        elif pattern == "policy" and "policies" in words:
            matched.add(pattern)
        elif pattern == "auth" and any(
                word.endswith("auth")
                or word.startswith(("authenticat", "authoris", "authoriz"))
                for word in words):
            matched.add(pattern)
        elif pattern == "migration" and any(word.startswith("migrat") for word in words):
            matched.add(pattern)
        elif pattern == "gate" and any(word.startswith("gate") for word in words):
            matched.add(pattern)
    return matched


def _bool_fact(facts, key, default):
    if key not in facts:
        return default
    value = facts[key]
    if type(value) is not bool:
        raise ValueError(f"{key} must be a JSON boolean")
    return value


def score(facts):
    """Score a change low/medium/high with the reasons that drove it.

    Highest band wins: any single high signal makes the whole change high.
    """
    if not isinstance(facts, dict):
        raise ValueError("facts must be a JSON object")
    files = facts.get("files", [])
    if not isinstance(files, list) or any(not isinstance(path, str) for path in files):
        raise ValueError("files must be a JSON array of strings")
    churn = int(facts.get("insertions") or 0) + int(facts.get("deletions") or 0)
    test_files = [f for f in files if _is_test(f)]
    source_files = [f for f in files if not _is_test(f) and not _is_non_executable(f)]
    # Derive tests_changed from the file list when the caller does not state it.
    # Callers that pass a flat `false` (a spec naming both a service and its test,
    # say) would otherwise be scored medium for "no test changed" and, under the
    # default low ceiling, escalate nearly every substantive issue. Deriving it
    # fixes that at the source rather than at each call site.
    tests_changed = (_bool_fact(facts, "tests_changed", False)
                     if "tests_changed" in facts else bool(test_files))
    gates_passed = _bool_fact(facts, "gates_passed", True)
    blocking_review = _bool_fact(facts, "blocking_review", False)

    high, medium = [], []

    sensitive = sorted({pattern for path in files for pattern in _sensitive_matches(path)})
    if sensitive:
        high.append("touches sensitive paths: " + ", ".join(sensitive))
    if not gates_passed:
        high.append("gates did not pass")
    # A blocking review finding is a separate signal from the gates: the gates are
    # CI, this is a reviewer saying "do not ship as-is". A small, clean, well-tested
    # diff can still carry one, and it would otherwise be banded `low` — the band a
    # reader skims past. Kept as its own fact rather than folded into
    # `gates_passed`, so the two never get conflated.
    if blocking_review:
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
    if source_files:
        reason = f"{len(files)} file(s), {churn} lines, tests touched"
    elif test_files:
        reason = f"{len(test_files)} test file(s)"
    else:
        reason = f"{len(files)} documentation or static asset file(s)"
    return {"risk": "low", "reasons": [reason]}


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
        try:
            result = score(json.loads(raw))
        except (TypeError, ValueError) as exc:
            print(f"cadence brief: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, separators=(",", ":"), sort_keys=True))
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
