#!/usr/bin/env python3
"""Render Cadence loop skills into provider-neutral prompt files."""

import argparse
import os
import pathlib
import sys


STAGES = {"triage", "spec", "build", "revise", "advance"}


FILE_STAGE_RULES = {
    "triage": [
        "Run `cadence tasks list` and inspect local tasks that do not already carry an agent terminal label.",
        "Fill only blanks that are clear from the task text. Mark settled tasks with `agent:triaged`; mark unclear tasks with `agent:needs-human`.",
    ],
    "spec": [
        "Run `cadence tasks list --label agent:spec`.",
        "For each selected task, write the spec into the task body with `cadence tasks update <ID> --body-file <file>`, then replace `agent:spec` with `agent:specced`.",
    ],
    "build": [
        "Run `cadence tasks list --label agent:build`.",
        "Implement inside the configured project/worktree only. Run configured gates. Replace `agent:build` with `agent:pr-open` when the work is ready for human review.",
    ],
    "revise": [
        "Run `cadence tasks list --label agent:revise`.",
        "Address the task feedback, run configured gates, then replace `agent:revise` with `agent:revised`.",
    ],
    "advance": [
        "Run `cadence tasks list --label agent:auto`.",
        "Grant only the next local gate when the resting label is ready: `agent:triaged` to `agent:spec`, `agent:specced` to `agent:build`, or repair/review labels after build.",
    ],
}


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text
    return text[end + len("\n---\n") :]


def extract_frontmatter_description(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    for line in text[4:end].splitlines():
        if line.startswith("description: "):
            return line.removeprefix("description: ").strip()
    return None


def render_file_prompt(stage: str, args: list[str], task_file: str) -> str:
    runtime_args = " ".join(args) if args else "(none)"
    rules = "\n".join(f"{idx}. {rule}" for idx, rule in enumerate(FILE_STAGE_RULES[stage], 1))
    return "\n".join(
        [
            f"# Cadence loop: {stage}",
            "",
            "You are running as the Cadence loop orchestrator.",
            "TASK_BACKEND=file. Use the local task-file adapter only for task state.",
            "",
            f"Task file: {task_file}",
            f"Runtime arguments: {runtime_args}",
            "",
            "## Hard Limits",
            "",
            "- Use `cadence tasks list`, `cadence tasks get`, and `cadence tasks update` for task reads and writes.",
            "- Do not use external issue tracker commands.",
            "- Keep all ids, paths, branches, models, and gates from the active config.",
            "- Never grant downstream authority beyond the current stage's documented local label transition.",
            "- Never mark a PR ready, merge, or push to the base branch.",
            "",
            "## Stage Procedure",
            "",
            rules,
            "",
            "## Summary",
            "",
            "Finish by printing one JSON object with `stage`, `dry_run`, count fields for this stage, and `errors`.",
            "",
        ]
    )


def render_prompt(stage: str, args: list[str], cadence_home: pathlib.Path) -> str:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    if os.environ.get("TASK_BACKEND", "linear").lower() == "file":
        return render_file_prompt(stage, args, os.environ.get("TASK_FILE", "cadence/tasks.md"))
    skill = cadence_home / "skills" / f"cadence-loop-{stage}" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8")
    body = strip_frontmatter(skill_text).strip()
    description = extract_frontmatter_description(skill_text)
    if description:
        body = f"{description}\n\n{body}"
    runtime_args = " ".join(args) if args else "(none)"
    return "\n".join(
        [
            f"# Cadence loop: {stage}",
            "",
            "You are running as the Cadence loop orchestrator.",
            "Follow the loop contract below exactly. Use the `cadence` CLI for Linear, memory, worktree, and decision operations.",
            "",
            f"Runtime arguments: {runtime_args}",
            "",
            "## Loop Contract",
            "",
            body,
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Cadence loop prompt.")
    parser.add_argument("stage")
    parser.add_argument("--output", required=True)
    ns, args = parser.parse_known_args(argv)

    cadence_home = pathlib.Path(__file__).resolve().parents[2]
    try:
        prompt = render_prompt(ns.stage, args, cadence_home)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output = pathlib.Path(ns.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(prompt, encoding="utf-8")
    print(str(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
