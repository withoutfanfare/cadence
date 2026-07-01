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
            continue
        if current is None:
            continue
        if line.startswith("status:"):
            current["status"] = line.split(":", 1)[1].strip()
        elif line.startswith("labels:"):
            current["labels"] = _split_list(line.split(":", 1)[1])
        else:
            body.append(line)
    if current:
        current["description"] = "\n".join(body).strip()
        tasks.append(current)
    return tasks


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


def build_parser():
    parser = argparse.ArgumentParser(prog="cadence tasks")
    sub = parser.add_subparsers(dest="cmd", required=True)

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
