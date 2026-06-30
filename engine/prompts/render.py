#!/usr/bin/env python3
"""Render Cadence loop skills into provider-neutral prompt files."""

import argparse
import pathlib
import sys


STAGES = {"triage", "spec", "build", "revise", "advance"}


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


def render_prompt(stage: str, args: list[str], cadence_home: pathlib.Path) -> str:
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
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
