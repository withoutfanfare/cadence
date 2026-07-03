#!/usr/bin/env python3
"""Render Cadence loop skills into provider-neutral prompt files."""

import argparse
import os
import pathlib
import re
import sys


STAGES = {"triage", "spec", "build", "revise", "advance", "roadmap"}

# Delimiters may carry trailing spaces/tabs and the file may use CRLF; match the
# lines loosely rather than requiring an exact `\n---\n`, which silently leaked the
# whole frontmatter into the prompt body on a single stray character.
_FM_OPEN = re.compile(r"^---[^\S\n]*\n")
_FM_CLOSE = re.compile(r"^---[^\S\n]*$", re.M)


FILE_STAGE_RULES = {
    "triage": [
        "Run `cadence tasks list` and inspect local tasks that do not already carry an agent terminal label.",
        "Fill only blanks that are clear from the task text. Mark settled tasks with `agent:triaged`; mark unclear tasks with `agent:needs-human`.",
        "Before marking a task `agent:triaged`, ensure its body has an `### Acceptance Criteria` section with a `- [ ]` checklist derived from the task text; if it is missing, write it with `cadence tasks update <ID> --body-file <file>` (use `###`, not `##`, which is reserved for task headers). If you cannot state clear criteria, mark `agent:needs-human` instead — autonomous mode only advances tasks that carry acceptance criteria.",
        "Reconcile merged PRs: `gh pr list --state merged --base \"${BASE_BRANCH:-develop}\" --json number,url,headRefName`. For each `agent:pr-open` task whose recorded PR URL (in its body) matches a PR that is now merged, close it with `cadence tasks update <ID> --status completed --remove-label agent:pr-open`. This only records a merge a human already made — never merge, mark a PR ready, or grant a gate. Count these as `backfilled` in the summary.",
    ],
    "spec": [
        "Run `cadence tasks list --label agent:spec`.",
        "For each selected task, write the spec into the task body with `cadence tasks update <ID> --body-file <file>`, then replace `agent:spec` with `agent:specced`. Also remove `agent:proposed` if present — a human gating a proposal accepts it.",
    ],
    "build": [
        "Run `cadence tasks list --label agent:build`.",
        "For each selected task, create an isolated worktree off the base branch — `WT=\"$(cadence worktree add <task-id-lowercase> \"${BASE_BRANCH:-develop}\")\"; cd \"$WT\"` — and implement in that worktree only. Never edit the main project checkout (`$PROJECT_DIR`) directly.",
        "Run the configured gates inside the worktree.",
        "Commit only the files the task targeted, push the branch, and open a **draft** PR against the base branch: `gh pr create --draft --base \"${BASE_BRANCH:-develop}\"`. Never mark it ready, never merge.",
        "Record the PR URL in the task body with `cadence tasks update`, then replace `agent:build` with `agent:pr-open` — only after the draft PR exists. If any step fails, keep `agent:build`, add `agent:needs-attention` with a note explaining what failed, and count it in `errors`.",
    ],
    "revise": [
        "Run `cadence tasks list --label agent:revise`.",
        "For each selected task, work in the task's existing worktree and branch (locate them from the PR URL recorded in the task body). Address the feedback there, run the configured gates, and push to the same branch so the existing draft PR updates. Never open a new PR, never mark it ready, never merge.",
        "Replace `agent:revise` with `agent:revised`. If the task has no PR URL or the branch is missing, do not edit any files — add `agent:needs-attention` with a note and count it in `errors`.",
    ],
    "advance": [
        "Run `cadence tasks list --label agent:auto`.",
        "Grant only the next local gate when the resting label is ready: `agent:triaged` to `agent:spec`, `agent:specced` to `agent:build`, or repair/review labels after build.",
    ],
    "roadmap": [
        "Read the optional goal from the file named by the GOAL_FILE environment variable (default cadence/goal.md, relative to the project root). If it exists and is non-empty, it steers what you look for. If it is missing or empty, that is normal — do not idle; work against the standing quality rubric instead: real bugs and correctness errors, performance problems (payload, slow paths, N+1 queries, image and asset weight), accessibility gaps, security issues, dead code and unused assets, and consistency defects where code violates a pattern the codebase already establishes. Prefer what a senior engineer would stop and flag.",
        "Run `cadence tasks list` (every task, every status). Treat any task carrying `agent:proposed` — whatever its status — as already proposed: never re-file an idea overlapping an open task, a done task, or a dismissed proposal. A dismissed proposal carrying `agent:later` may be reconsidered if it still clearly serves the goal or rubric.",
        "Investigate the codebase read-only for the few strongest improvements — bugs or missing pieces — that serve the goal (if set) or the rubric. Never edit files, never run application code.",
        "File new proposals with `cadence tasks add --title <title> --body-file <file>` (the adapter forces `agent:proposed` and enforces the ROADMAP_MAX_OPEN cap). Each body must state the problem or opportunity, where in the code it lives, a one-line `Why it matters: ...` (tie it to the goal if set, otherwise the rubric category), and an `### Acceptance Criteria` checklist. Prefer few and strong over many and thin; filing nothing is a valid outcome — never pad to the cap.",
    ],
}


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter, body). If the text opens with a `---` fence but has no
    closing delimiter, warn and treat the whole file as body (frontmatter=None)."""
    text = text.replace("\r\n", "\n")
    opening = _FM_OPEN.match(text)
    if not opening:
        return None, text
    closing = _FM_CLOSE.search(text, opening.end())
    if not closing:
        sys.stderr.write(
            "render: file opens with '---' but has no closing frontmatter "
            "delimiter; treating the whole file as body\n")
        return None, text
    frontmatter = text[opening.end():closing.start()]
    body = text[closing.end():]
    return frontmatter, body.lstrip("\n")


def strip_frontmatter(text: str) -> str:
    return _split_frontmatter(text)[1]


def extract_frontmatter_description(text: str) -> str | None:
    frontmatter, _ = _split_frontmatter(text)
    if frontmatter is None:
        return None
    for line in frontmatter.splitlines():
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
            "Finish by printing, as the final line of stdout, one JSON object with `stage`, `dry_run`, count fields for this stage, and `errors`, prefixed with the fixed marker `CADENCE_SUMMARY ` so the runner finds it reliably (e.g. `CADENCE_SUMMARY {\"stage\":\"triage\",\"dry_run\":false,\"errors\":0}`).",
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
    frontmatter, body = _split_frontmatter(skill_text)  # split once: one warning at most
    body = body.strip()
    description = None
    if frontmatter is not None:
        for line in frontmatter.splitlines():
            if line.startswith("description: "):
                description = line.removeprefix("description: ").strip()
                break
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
