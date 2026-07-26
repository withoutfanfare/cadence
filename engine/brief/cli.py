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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="cadence-brief")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--payload", help="brief JSON (default: read stdin)")
    p = sub.add_parser("parse")
    p.add_argument("--file", help="comment body file (default: read stdin)")
    args = ap.parse_args(argv)

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
