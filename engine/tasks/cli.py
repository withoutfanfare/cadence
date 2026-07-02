#!/usr/bin/env python3
"""cadence tasks — local markdown task-file adapter. Stdlib only."""

import argparse
import json
import os
import re
import sys


HEADER_RE = re.compile(r"^##\s+([^:\n]+):\s*(.+)$")


def task_path(env=None):
    env = env or os.environ
    path = env.get("TASK_FILE") or "cadence/tasks.md"
    if not os.path.isabs(path):
        path = os.path.join(env.get("PROJECT_DIR") or os.getcwd(), path)
    return path


def _split_list(value):
    return [part.strip() for part in value.split(",") if part.strip()]


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
    for n, line in enumerate(text.splitlines(), 1):
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
        # `## ` is reserved for task headers. A `## ` line that is not a valid
        # `## <ID>: <Title>` is swallowed into the previous task's body.
        if line.startswith("## "):
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
    return tasks


def cmd_get(args, env=None):
    return _find(load(env), args.identifier)


def cmd_update(args, env=None):
    tasks = load(env)
    task = _find(tasks, args.identifier)
    if args.status is not None:
        task["status"] = args.status
    labels = list(task.get("labels") or [])
    for label in args.remove_label or []:
        labels = [existing for existing in labels if existing != label]
    for label in args.add_label or []:
        if label not in labels:
            labels.append(label)
    task["labels"] = labels
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            task["description"] = f.read().strip()
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
    return parser


def main(argv=None, env=None):
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "validate":
            problems = cmd_validate(args, env)
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1 if problems else 0
        if args.cmd == "list":
            out = cmd_list(args, env)
        elif args.cmd == "get":
            out = cmd_get(args, env)
        else:
            out = cmd_update(args, env)
    except (FileNotFoundError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
