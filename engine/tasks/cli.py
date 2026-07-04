#!/usr/bin/env python3
"""cadence tasks — local markdown task-file adapter. Stdlib only."""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from stages import resolve_labels, stage_of  # noqa: E402


HEADER_RE = re.compile(r"^##\s+([^:\n]+):\s*(.+)$")


def task_path(env=None):
    env = env or os.environ
    path = env.get("TASK_FILE") or "cadence/tasks.md"
    if not os.path.isabs(path):
        path = os.path.join(env.get("PROJECT_DIR") or os.getcwd(), path)
    return path


def _split_list(value):
    return [part.strip() for part in value.split(",") if part.strip()]


def _check_body(description):
    """Reject body text that would round-trip into a brand-new task.

    `## ID: Title` is reserved for task headers; a body line matching it re-parses
    on the next load() as a separate task carrying attacker-chosen status/labels —
    a privilege-escalation vector, since roadmap bodies can derive from untrusted
    repo content and could forge gate labels (agent:build/agent:auto) the loops are
    forbidden from granting, while bypassing the ROADMAP_MAX_OPEN cap. Bodies use
    `###` for sub-headings (see the triage/roadmap rules).
    ponytail: rejects at the write path rather than escaping in render/parse —
    validate() already flags any forged header a human hand-edits in.
    """
    for line in (description or "").splitlines():
        if HEADER_RE.match(line):
            raise ValueError(
                "task body contains a line that parses as a task header "
                f"({line.strip()!r}); use '###' for sub-headings — '##' is "
                "reserved for task headers")


def parse(text):
    tasks = []
    current = None
    body = []
    in_header = False
    for line in text.splitlines():
        match = HEADER_RE.match(line)
        if match:
            if current:
                current["description"] = "\n".join(body).strip()
                tasks.append(current)
            current = {
                "id": match.group(1).strip(),
                "identifier": match.group(1).strip(),
                "title": match.group(2).strip(),
                "status": "",
                "labels": [],
                "description": "",
            }
            body = []
            in_header = True
            continue
        if current is None:
            continue
        # `status:`/`labels:` are metadata only in the header block that render()
        # emits right after the `## ID: Title` line. Once body text begins, an
        # identical prefix (e.g. "status: 200" in a spec) is body, not metadata.
        if in_header and line.startswith("status:"):
            current["status"] = line.split(":", 1)[1].strip()
        elif in_header and line.startswith("labels:"):
            current["labels"] = _split_list(line.split(":", 1)[1])
        else:
            in_header = False
            body.append(line)
    if current:
        current["description"] = "\n".join(body).strip()
        tasks.append(current)
    return tasks


def validate(text):
    """Return a list of format problems that would cause silent data loss.

    The parser (parse) never errors — it ignores lines it does not recognise.
    That means a malformed header or metadata placed a line too late is dropped
    silently. This surfaces exactly those cases so `cadence doctor` can flag them.
    """
    problems = []
    seen_ids = {}
    current = None
    in_header = False
    header_meta = set()
    awaiting_body = False
    lines = text.splitlines()

    def _next_nonempty(i):
        for j in range(i + 1, len(lines)):
            if lines[j].strip():
                return lines[j]
        return ""

    for n, line in enumerate(lines, 1):
        match = HEADER_RE.match(line)
        if match:
            tid = match.group(1).strip()
            if tid in seen_ids:
                problems.append(
                    f"line {n}: duplicate task id '{tid}' (first at line "
                    f"{seen_ids[tid]}); only the first is reachable"
                )
            else:
                seen_ids[tid] = n
            current = tid
            in_header = True
            header_meta = set()
            awaiting_body = True
            continue
        # `## ` is reserved for task headers, but a body line may legitimately
        # start with it and parse() tolerates that (treats it as body). Only flag
        # a non-matching `## ` line as a broken header when the author clearly
        # meant one — i.e. the next non-empty line is task metadata.
        if line.startswith("## ") and _next_nonempty(n - 1).startswith(("status:", "labels:")):
            problems.append(
                f"line {n}: malformed task header {line.strip()!r}; expected "
                "'## <ID>: <Title>' (the ID must not contain a colon)"
            )
            continue
        if current is None:
            continue
        if in_header and line.startswith("status:"):
            header_meta.add("status")
        elif in_header and line.startswith("labels:"):
            header_meta.add("labels")
        else:
            in_header = False
            if awaiting_body and line.strip():
                awaiting_body = False
                key = "status" if line.startswith("status:") else (
                    "labels" if line.startswith("labels:") else None)
                if key and key not in header_meta:
                    problems.append(
                        f"line {n}: '{key}:' is in the body of task '{current}', "
                        f"not its header; move it directly under the "
                        f"'## {current}: …' line with no blank line between"
                    )
    # Workflow truth, not just format: agent:pr-open claims a draft PR exists,
    # and the build loop records its URL in the body. A pr-open task with no
    # PR reference is the tell that build never opened one.
    for task in parse(text):
        if "agent:pr-open" in task["labels"] and not re.search(
                r"/pull/\d+", task["description"]):
            problems.append(
                f"task '{task['identifier']}': labelled agent:pr-open but the body "
                "has no PR URL (…/pull/<n>) — the draft PR may not exist; the build "
                "loop records the PR URL when it opens one"
            )
    return problems


def render(tasks):
    parts = ["# Cadence Tasks", ""]
    for task in tasks:
        parts.append(f"## {task['identifier']}: {task['title']}")
        parts.append(f"status: {task.get('status', '')}")
        parts.append("labels: " + ", ".join(task.get("labels") or []))
        parts.append("")
        desc = (task.get("description") or "").strip()
        if desc:
            parts.append(desc)
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def load(env=None):
    path = task_path(env)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


def save(tasks, env=None):
    path = task_path(env)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(tasks))


def _find(tasks, identifier):
    for task in tasks:
        if task["identifier"] == identifier:
            return task
    raise KeyError(identifier)


def cmd_list(args, env=None):
    tasks = load(env)
    if args.label:
        tasks = [task for task in tasks if args.label in (task.get("labels") or [])]
    if args.status:
        tasks = [task for task in tasks if task.get("status") == args.status]
    for task in tasks:
        task["stage"] = stage_of(task.get("labels") or [])
    return tasks


def cmd_get(args, env=None):
    return _find(load(env), args.identifier)


GATE_LABELS = {"agent:spec", "agent:build", "agent:revise"}
# Only the stage that owns a gate may retire it as part of its forward transition
# (spec consumes agent:spec, build consumes agent:build, revise consumes agent:revise).
_STAGE_MAY_REMOVE_GATE = {"spec": {"agent:spec"}, "build": {"agent:build"}, "revise": {"agent:revise"}}


def _guard_gate_removal(remove_labels, env):
    """A scheduled loop must never strip a human gate label; only a human (no
    CADENCE_STAGE in the environment) or the stage that owns the gate may remove
    it. Enforced here in the engine because the prompt-level rule can be — and was
    — disobeyed by a model (triage erased a granted agent:spec, reverting the work
    to agent:triaged). run-loop.sh exports CADENCE_STAGE for every loop run."""
    stage = (env.get("CADENCE_STAGE") or "").strip().lower()
    if not stage:
        return
    allowed = _STAGE_MAY_REMOVE_GATE.get(stage, set())
    illegal = sorted(lbl for lbl in remove_labels if lbl in GATE_LABELS and lbl not in allowed)
    if illegal:
        raise SystemExit(
            "refused: the %s loop may not remove human gate label(s) %s — only a "
            "human, or the stage that owns the gate, removes it"
            % (stage, ", ".join(illegal)))


def cmd_update(args, env=None):
    env = env or os.environ
    _guard_gate_removal(args.remove_label or [], env)
    tasks = load(env)
    task = _find(tasks, args.identifier)
    if args.status is not None:
        task["status"] = args.status
    task["labels"] = resolve_labels(task.get("labels") or [],
                                    add=args.add_label, remove=args.remove_label)
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            description = f.read().strip()
        _check_body(description)
        task["description"] = description
    save(tasks, env)
    return task


def _next_id(tasks):
    """Next id in the board's dominant PREFIX-N convention (default TASK)."""
    pattern = re.compile(r"^([A-Za-z]+)-(\d+)$")
    counts, highest = {}, {}
    for task in tasks:
        m = pattern.match(task["identifier"])
        if not m:
            continue
        prefix, num = m.group(1), int(m.group(2))
        counts[prefix] = counts.get(prefix, 0) + 1
        highest[prefix] = max(highest.get(prefix, 0), num)
    prefix = max(counts, key=lambda p: counts[p]) if counts else "TASK"
    return "%s-%d" % (prefix, highest.get(prefix, 0) + 1)


def cmd_add(args, env=None):
    """Append a roadmap proposal. Always status: open with agent:proposed;
    refuses to exceed ROADMAP_MAX_OPEN open proposals (engine-enforced cap)."""
    environ = env or os.environ
    tasks = load(env)
    try:
        max_open = int(environ.get("ROADMAP_MAX_OPEN") or 5)
    except ValueError:
        max_open = 5
    open_proposed = [t for t in tasks
                     if "agent:proposed" in (t.get("labels") or [])
                     and (t.get("status") or "") == "open"]
    if len(open_proposed) >= max_open:
        raise ValueError(
            "roadmap cap reached: %d open proposal(s) (ROADMAP_MAX_OPEN=%d)"
            % (len(open_proposed), max_open))
    labels = ["agent:proposed"]
    for label in args.add_label or []:
        if label not in labels:
            labels.append(label)
    description = ""
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            description = f.read().strip()
        _check_body(description)
    identifier = _next_id(tasks)
    task = {"id": identifier, "identifier": identifier, "title": args.title,
            "status": "open", "labels": labels, "description": description}
    tasks.append(task)
    save(tasks, env)
    return task


def cmd_validate(args, env=None):
    path = task_path(env)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        return validate(f.read())


def build_parser():
    parser = argparse.ArgumentParser(prog="cadence tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate")
    sub.add_parser("path")

    list_p = sub.add_parser("list")
    list_p.add_argument("--label")
    list_p.add_argument("--status")

    get_p = sub.add_parser("get")
    get_p.add_argument("identifier")

    update_p = sub.add_parser("update")
    update_p.add_argument("identifier")
    update_p.add_argument("--status")
    update_p.add_argument("--add-label", action="append")
    update_p.add_argument("--remove-label", action="append")
    update_p.add_argument("--body-file")

    add_p = sub.add_parser("add")
    add_p.add_argument("--title", required=True)
    add_p.add_argument("--add-label", action="append")
    add_p.add_argument("--body-file")
    return parser


def main(argv=None, env=None):
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "path":
            print(task_path(env))
            return 0
        if args.cmd == "validate":
            problems = cmd_validate(args, env)
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0
        if args.cmd == "list":
            out = cmd_list(args, env)
        elif args.cmd == "get":
            out = cmd_get(args, env)
        elif args.cmd == "add":
            out = cmd_add(args, env)
        else:
            out = cmd_update(args, env)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
