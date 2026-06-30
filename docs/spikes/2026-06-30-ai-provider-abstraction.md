# Spike: AI Provider Abstraction for Cadence Orchestrators

**Date:** 2026-06-30
**Question:** How can Cadence swap the lead/orchestrator AI model from Claude Code to Codex, Kimi, OpenCode, or another provider?
**Scope:** Comparative architecture spike over the current runner, prompt, implementer, and documentation surfaces.
**Verdict:** Go with caveats. Cadence already has a useful implementer abstraction, but true orchestrator abstraction requires moving from "Claude slash command launches a skill" to "Cadence renders a provider-neutral prompt and sends it through a provider adapter".

## Context

Cadence currently presents model choice as profile configuration, but the main loop runner is still a Claude Code runner. The build implementer can already be swapped between `claude`, `kimi`, `opencode`, and `codex`; the lead orchestrator cannot. This spike identifies what must change to let the same Cadence loop be led by Codex, Kimi, OpenCode, or future providers without rewriting the loop logic each time.

## Findings

### Current orchestrator path is hard-coded to Claude

The runner chooses a stage-specific slash command and a model alias, then directly executes:

```bash
claude -p "$CMD" --model "$MODEL" --dangerously-skip-permissions
```

Evidence: `engine/scripts/run-loop.sh` builds `CMD`/`MODEL` for `triage`, `spec`, `build`, `revise`, and `advance`, then invokes `claude` directly. `engine/lib/lib-env.sh` defaults `MODEL_TRIAGE=sonnet`, `MODEL_SPEC=opus`, `MODEL_BUILD=opus`, and `MODEL_REVISE=sonnet`, which are Claude model aliases, not provider-neutral model ids.

This means changing `MODEL_BUILD=...` only changes the Claude model. It cannot switch the orchestrator runtime to Codex or Kimi.

### Implementer abstraction is the best local pattern to copy

`engine/scripts/run-implementer.sh` is already the only place that knows how to invoke each coding agent. It accepts a vendor, a worktree, and a brief file, then maps that stable contract to vendor-specific CLI syntax:

- `claude -p "$PROMPT" --model sonnet --dangerously-skip-permissions`
- `kimi -p "$PROMPT"`
- `opencode run --model "$OPENCODE_MODEL" "$PROMPT"`
- `codex exec --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WT" --skip-git-repo-check "$PROMPT"`

That pattern should become `run-orchestrator.sh`: stable Cadence contract in, provider-specific command out.

### Slash-command skills are the main abstraction blocker

The current runner does not pass the loop body as plain prompt text. It passes strings such as `/cadence-loop-build --implementer=claude`. That assumes the provider understands Claude Code slash skills and can load `skills/cadence-loop-build/SKILL.md` with its frontmatter, allowed tools, and task instructions.

Codex, Kimi, and OpenCode can accept prompts, but they should not be assumed to understand Claude's slash-command skill registry. The provider-neutral boundary needs a prompt renderer:

1. Resolve stage + args into the relevant `skills/cadence-loop-<stage>/SKILL.md`.
2. Render that skill body plus runtime args into a plain prompt.
3. Send the rendered prompt to the chosen provider CLI.

Once the prompt is plain text, the provider adapter only needs to run a non-interactive agent with the right working directory, model, permissions, timeout, and output capture.

### The loop skills also assume Claude-only capabilities

Several loop bodies instruct the orchestrator to dispatch a `Task`/`code-reviewer` subagent. That is a Claude Code capability, not a generic provider capability. It appears in the build, revise, and advance paths.

For true abstraction, "review this diff" should become a Cadence helper such as `cadence review diff` or `engine/scripts/run-reviewer.sh`, with its own provider/model configuration. The orchestrator would run that helper and consume the result, instead of relying on its own runtime to have a specific subagent mechanism.

### Provider abstraction needs capability checks, not only command checks

`doctor.sh` currently requires `claude` on `PATH` for orchestration and only checks alternate CLIs for the implementer. With provider abstraction, doctor should validate the selected orchestrator provider:

- CLI is installed and authenticated enough for non-interactive use.
- Required execution mode is available: shell access, file read/write where needed, auto-approval mode, working-directory flag, timeout behaviour.
- Prompt mode can run without a TTY.
- Optional structured output support is known, if Cadence later enforces schemas.

Local CLI checks on this machine show:

- Codex has `codex exec`, `--model`, `-C/--cd`, `--dangerously-bypass-approvals-and-sandbox`, `--json`, and `--output-schema`.
- Kimi has `-p/--prompt`, `-m/--model`, `--output-format`, `--add-dir`, and auto modes (`--yolo`, `--auto`), but its current implementer wrapper deliberately avoids those auto flags because they were interactive in prior testing.
- OpenCode has `opencode run`, `--model`, `--dir`, JSON output, and `--dangerously-skip-permissions`.
- Claude has `-p/--print`, `--model`, `--dangerously-skip-permissions`, and JSON/schema options.

## Trade-offs

| Factor | Wrapper only | Prompt-rendered provider adapter | Full runtime abstraction |
| --- | --- | --- | --- |
| Effort | Small | Medium | Large |
| Can run Codex/Kimi as orchestrator | Only if they understand `/cadence-loop-*` | Yes, as plain prompt | Yes |
| Removes Claude-specific assumptions | No | Partly | Yes |
| Handles `Task`/subagent review | No | No, unless review helper is added | Yes |
| Risk | High hidden incompatibility | Moderate, testable per provider | Lower long-term, more upfront work |
| Best use | Quick experiment | Practical first implementation | Durable architecture |

## Risks

- **Provider capability mismatch:** The loop bodies need shell, file, git, GitHub, and Linear CLI access. A provider that can chat but cannot safely run those tools is not a valid orchestrator.
- **Prompt semantics drift:** Claude skill frontmatter (`allowed-tools`, `model`, `argument-hint`) may be ignored by other providers unless Cadence renders and enforces those concerns itself.
- **Review independence regression:** If `Task` subagents disappear without a replacement review helper, build/revise/advance lose one of their safety checks.
- **Model alias confusion:** `sonnet` and `opus` are provider-specific aliases. A provider-neutral config must not pretend `MODEL_BUILD=opus` means anything to Codex or Kimi.
- **Unattended permission safety:** Each CLI has different auto-approval flags. These should live in one adapter script with explicit tests, not in loop prose.

## Assumptions

- Cadence wants CLI-based providers first, not direct SDK/API integration.
- The first useful target is non-interactive scheduled execution, not rich interactive sessions.
- The existing human-gated safety model stays unchanged: pause/workspace guards still run before any provider launch; build/revise remain the only code-writing loops; PRs stay draft-only.
- Kimi/OpenCode/Codex command-line behaviour should be rechecked when implementing because these CLIs change faster than Cadence's engine code.

## Recommendation

Implement provider abstraction in two layers:

1. **Provider adapter layer:** Add `engine/scripts/run-orchestrator.sh`, modelled on `run-implementer.sh`. It should accept a provider, model, working directory, prompt file, and stage, then invoke `claude`, `codex`, `kimi`, or `opencode` through a single contract. Add `ORCHESTRATOR_PROVIDER=claude` and per-stage provider/model config.
2. **Prompt contract layer:** Stop launching `/cadence-loop-*` directly. Add a prompt renderer that converts `skills/cadence-loop-<stage>/SKILL.md` plus runtime args into a plain prompt file. Then every provider receives the same Cadence instructions.

Do not call this "true provider abstraction" until the `Task`/`code-reviewer` dependency is moved behind a provider-neutral review helper. Without that, Codex or Kimi may run the main loop but still fail or degrade at the folded-review gates.

## Suggested Config Shape

Prefer explicit provider/model pairs over overloading `MODEL_*`:

```dotenv
ORCHESTRATOR_PROVIDER=claude

ORCHESTRATOR_TRIAGE=claude:sonnet
ORCHESTRATOR_SPEC=claude:opus
ORCHESTRATOR_BUILD=claude:opus
ORCHESTRATOR_REVISE=claude:sonnet
ORCHESTRATOR_ADVANCE=claude:sonnet

REVIEW_PROVIDER=claude
REVIEW_MODEL=opus
BUILD_IMPLEMENTER=codex
```

This allows mixed setups such as Codex leading build while Claude performs folded review, or Claude leading triage/spec while Kimi performs implementation.

## Next Steps

1. Add `run-orchestrator.sh` with provider cases for `claude`, `codex`, `kimi`, and `opencode`.
2. Add a stdlib prompt renderer, for example `engine/prompts/render.py`, that turns a stage and args into a plain prompt file.
3. Change `run-loop.sh` to call the renderer and then `run-orchestrator.sh` instead of `claude -p`.
4. Add `doctor.sh` checks for the selected orchestrator provider and model config.
5. Replace `Task`/`code-reviewer` instructions in build/revise/advance with a `run-reviewer.sh` or `cadence review` helper.
6. Update `.env.example`, `docs/CONFIGURATION.md`, `docs/IMPLEMENTERS.md`, `README.md`, and `docs/ARCHITECTURE.md`.
7. Add tests proving pre-launch guards still exit before any provider command, and that each provider adapter receives the same rendered prompt.

## Implementation Plan

Accepted path: provider adapter + prompt renderer + provider-neutral reviewer.
See `docs/superpowers/plans/2026-06-30-ai-provider-abstraction.md`.
