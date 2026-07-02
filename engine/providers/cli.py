#!/usr/bin/env python3
"""Inspect and update Cadence AI provider configuration."""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys


PROVIDERS = {"claude", "codex", "kimi", "opencode"}
STAGES = {
    "triage": ("ORCHESTRATOR_TRIAGE", "MODEL_TRIAGE", "sonnet", "triage orchestrator"),
    "spec": ("ORCHESTRATOR_SPEC", "MODEL_SPEC", "opus", "spec orchestrator"),
    "build": ("ORCHESTRATOR_BUILD", "MODEL_BUILD", "opus", "build orchestrator"),
    "revise": ("ORCHESTRATOR_REVISE", "MODEL_REVISE", "sonnet", "revise orchestrator"),
    "advance": ("ORCHESTRATOR_ADVANCE", "MODEL_ADVANCE", "sonnet", "advance orchestrator"),
    "roadmap": ("ORCHESTRATOR_ROADMAP", "MODEL_ROADMAP", "opus", "roadmap orchestrator"),
}
ORDER = [
    "ORCHESTRATOR_PROVIDER",
    "ORCHESTRATOR_TRIAGE",
    "ORCHESTRATOR_SPEC",
    "ORCHESTRATOR_BUILD",
    "ORCHESTRATOR_REVISE",
    "ORCHESTRATOR_ADVANCE",
    "ORCHESTRATOR_ROADMAP",
    "REVIEW_PROVIDER",
    "REVIEW_MODEL",
    "BUILD_IMPLEMENTER",
]
MANUAL = """\
Cadence Provider Roles

Provider Roles
  triage/spec/build/revise/advance/roadmap orchestrator
    Controlled by ORCHESTRATOR_<STAGE>=provider:model. This is the lead model
    running each Cadence loop.

  folded reviewer
    Controlled by REVIEW_PROVIDER and REVIEW_MODEL. This is separate from the
    loop orchestrator and can deliberately stay on another provider.

  build implementer
    Controlled by BUILD_IMPLEMENTER. This is the coding agent provider used
    inside the build worktree.

Rules
  ORCHESTRATOR_* values use provider:model.
  REVIEW_PROVIDER/REVIEW_MODEL combine into provider:model for folded review.
  BUILD_IMPLEMENTER is provider-only, for example codex.
  MODEL_* values are model names only. Do not put provider:model values there.

Common commands
  cadence providers roles
  cadence providers show
  cadence providers set --build codex:gpt-5.4 --implementer codex
  cadence providers set --all kimi:k2 --review claude:opus --implementer kimi
  cadence doctor

Common trap
  Wrong: MODEL_BUILD=codex:gpt-5.4
  Right: ORCHESTRATOR_BUILD=codex:gpt-5.4

  Wrong: BUILD_IMPLEMENTER=codex:gpt-5.4
  Right: BUILD_IMPLEMENTER=codex

Full guide: docs/PROVIDERS.md
"""


def cadence_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CADENCE_HOME", pathlib.Path(__file__).resolve().parents[2]))


def env_path() -> pathlib.Path:
    explicit = os.environ.get("CADENCE_CONFIG")
    if explicit:
        return pathlib.Path(explicit)
    project = pathlib.Path.cwd() / "cadence" / ".env"
    if project.exists():
        return project
    return cadence_home() / ".env"


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not match:
            continue
        raw = match.group(2).strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        values[match.group(1)] = raw
    return values


def effective_values(values: dict[str, str]) -> dict[str, str]:
    provider = values.get("ORCHESTRATOR_PROVIDER", "claude")
    result = dict(values)
    result.setdefault("ORCHESTRATOR_PROVIDER", provider)
    for _stage, (key, model_key, model_default, _label) in STAGES.items():
        result.setdefault(key, f"{provider}:{values.get(model_key, model_default)}")
    result.setdefault("REVIEW_PROVIDER", "claude")
    result.setdefault("REVIEW_MODEL", "opus")
    result.setdefault("BUILD_IMPLEMENTER", "claude")
    return result


def provider_from_pair(pair: str) -> str:
    provider = pair.split(":", 1)[0]
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    if ":" not in pair:
        raise ValueError(f"provider/model pair required: {pair}")
    if not pair.split(":", 1)[1]:
        raise ValueError(f"model is required: {pair}")
    return provider


def validate_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")


def set_env_values(path: pathlib.Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    pattern = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(=.*)$")

    for line in lines:
        match = pattern.match(line)
        if match and match.group(2) in updates:
            key = match.group(2)
            output.append(f"{match.group(1)}{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)

    missing = [key for key in ORDER if key in updates and key not in seen]
    missing.extend(key for key in updates if key not in ORDER and key not in seen)
    if missing and output and output[-1] != "":
        output.append("")
    for key in missing:
        output.append(f"{key}={updates[key]}")

    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def print_table(rows: list[tuple[str, str, str]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    for row in rows:
        print(f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]}")


def cmd_roles(_args: argparse.Namespace) -> int:
    values = effective_values(parse_env(env_path()))
    rows = [("Role", "Setting", "Current")]
    rows.extend((label, key, values[key]) for _stage, (key, _model_key, _model_default, label) in STAGES.items())
    rows.append(("folded reviewer", "REVIEW_PROVIDER/REVIEW_MODEL", f"{values['REVIEW_PROVIDER']}:{values['REVIEW_MODEL']}"))
    rows.append(("build implementer", "BUILD_IMPLEMENTER", values["BUILD_IMPLEMENTER"]))
    print_table(rows)
    return 0


def cmd_show(_args: argparse.Namespace) -> int:
    values = effective_values(parse_env(env_path()))
    for key in ORDER:
        print(f"{key}={values[key]}")
    return 0


def cmd_help(_args: argparse.Namespace) -> int:
    print(MANUAL.rstrip())
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    updates: dict[str, str] = {}
    if args.all:
        provider = provider_from_pair(args.all)
        updates["ORCHESTRATOR_PROVIDER"] = provider
        for _stage, (key, _model_key, _model_default, _label) in STAGES.items():
            updates[key] = args.all

    for stage, (key, _model_key, _model_default, _label) in STAGES.items():
        value = getattr(args, stage)
        if value:
            provider_from_pair(value)
            updates[key] = value

    if args.review:
        provider = provider_from_pair(args.review)
        updates["REVIEW_PROVIDER"] = provider
        updates["REVIEW_MODEL"] = args.review.split(":", 1)[1]

    if args.implementer:
        validate_provider(args.implementer)
        updates["BUILD_IMPLEMENTER"] = args.implementer

    if not updates:
        print("providers set: no changes requested", file=sys.stderr)
        return 2

    set_env_values(env_path(), updates)
    for key in ORDER:
        if key in updates:
            print(f"{key}={updates[key]}")
    print("Run `cadence doctor` to verify selected provider CLIs.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cadence providers")
    sub = parser.add_subparsers(dest="command", required=True)

    roles = sub.add_parser("roles", help="show provider roles and current values")
    roles.set_defaults(func=cmd_roles)

    show = sub.add_parser("show", help="show raw provider configuration")
    show.set_defaults(func=cmd_show)

    help_parser = sub.add_parser("help", help="show provider role manual")
    help_parser.set_defaults(func=cmd_help)

    man = sub.add_parser("man", help="show provider role manual")
    man.set_defaults(func=cmd_help)

    set_parser = sub.add_parser("set", help="update provider configuration in the active config")
    set_parser.add_argument("--all", help="set every orchestrator to provider:model")
    for stage in STAGES:
        set_parser.add_argument(f"--{stage}", help=f"set {stage} orchestrator to provider:model")
    set_parser.add_argument("--review", help="set folded reviewer to provider:model")
    set_parser.add_argument("--implementer", help="set build implementer provider")
    set_parser.set_defaults(func=cmd_set)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
