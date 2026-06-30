"""Cadence memory adapter — markdown backend. Stdlib only.

One file per rule under MEMORY_DIR (default $CADENCE_HOME/memory), frontmatter
name/importance/description. recall = read + filter + sort + limit. remember =
write a new rule file. The clio backend is handled in the skills via the Clio
MCP tools (Clio is an MCP server, not a CLI); this adapter is the markdown path.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from cadence_env import load_env  # noqa: E402


def _mem_dir(env):
    return env.get("MEMORY_DIR") or os.path.join(
        env.get("CADENCE_HOME", os.getcwd()), "memory")


def _parse(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return None
    meta, body = {}, m.group(2).strip()
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    try:
        imp = int(meta.get("importance", 0))
    except ValueError:
        imp = 0
    return {"name": meta.get("name", os.path.basename(path)[:-3]),
            "importance": imp, "description": meta.get("description", ""),
            "body": body}


def cmd_recall(args, env):
    d = _mem_dir(env)
    rules = []
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".md") and fn != "MEMORY.md":
                r = _parse(os.path.join(d, fn))
                if r and r["importance"] >= args.min_importance:
                    rules.append(r)
    rules.sort(key=lambda r: r["importance"], reverse=True)
    return rules[: args.limit]


def _slug(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]


def cmd_remember(args, env):
    d = _mem_dir(env)
    os.makedirs(d, exist_ok=True)
    name = _slug(args.title)
    path = os.path.join(d, f"{name}.md")
    desc = args.title if len(args.title) <= 80 else args.title[:77] + "..."
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\nname: {name}\nimportance: {args.importance}\n"
                f"description: {desc}\n---\n\n{args.body}\n")
    return {"name": name, "path": path}


def main(argv=None):
    p = argparse.ArgumentParser(prog="cadence memory")
    sub = p.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("recall")
    rc.add_argument("--min-importance", type=int, default=1, dest="min_importance")
    rc.add_argument("--limit", type=int, default=8)
    rm = sub.add_parser("remember")
    rm.add_argument("--importance", type=int, required=True)
    rm.add_argument("--title", required=True)
    rm.add_argument("body")
    args = p.parse_args(argv)
    env = load_env()
    out = cmd_recall(args, env) if args.cmd == "recall" else cmd_remember(args, env)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
