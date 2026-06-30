# Spike: AI Provider Abstraction for Cadence Orchestrators

**Date:** 2026-06-30
**Status:** Historical spike. The provider-neutral path described here was accepted and is now the working direction at current HEAD.
**Question:** How can Cadence swap the lead/orchestrator AI model from Claude Code to Codex, Kimi, OpenCode, or another provider?
**Scope:** Comparative architecture spike over the current runner, prompt, implementer, and documentation surfaces.
**Verdict:** Accepted. Cadence keeps the same loop contract, but the lead orchestrator is configured through provider/model pairs rather than a hard-coded Claude-only runtime.

## Historical context

At the time of the spike, the build implementer could already be swapped between `claude`, `kimi`, `opencode`, and `codex`, but the lead orchestrator still assumed Claude Code. That mismatch was the problem this spike set out to solve.

The notes below preserve the reasoning that led to the accepted implementation path. They are historical context, not current blockers.

## Historical findings

### The old orchestrator path was Claude-specific

The runner used to choose a stage-specific slash command and a model alias, then execute Claude directly:

```bash
claude -p "$CMD" --model "$MODEL" --dangerously-skip-permissions
```

That made `MODEL_BUILD=...` a Claude model selection only. It could not switch the orchestrator runtime to Codex or Kimi.

### The implementer abstraction was the right local pattern to copy

`engine/scripts/run-implementer.sh` already provided the useful shape: a stable Cadence contract in, provider-specific command out. That remains the reference pattern for any orchestrator adapter.

### Slash-command skills were the main blocker

The historical runner passed `/cadence-loop-*` style commands instead of plain prompt text. That assumed the provider understood Claude Code slash skills and its skill registry.

The accepted direction is to render the loop skill into plain text first, then hand that text to the selected provider CLI.

### Folded review needed a provider-neutral home

The `Task`/`code-reviewer` dependency was a Claude Code capability, not a generic provider feature. That is why the spike treated folded review as a separate helper concern.

That dependency is best treated as follow-up hardening, not a current blocker for the provider-neutral lead loop.

### Doctor needed provider-aware checks

The historical `claude`-only prerequisite check belonged to the old world. Current docs and tooling should validate whichever orchestrator provider the profile selects, rather than assuming Claude.

## Accepted path at current HEAD

Cadence now expresses the lead loop through provider-neutral profile values:

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

That shape allows mixed setups such as Codex leading build while Claude performs folded review, or Claude leading triage/spec while Kimi performs implementation.

Any remaining prompt-renderer or reviewer-helper polish should be tracked as follow-up work, not as a blocker to the accepted provider-neutral path.

## Recommendation

Keep the provider-neutral direction. Treat future provider-specific assumptions as follow-up tasks, and keep the historical Claude-only analysis here only as context for why the abstraction exists.

## Implementation plan

Accepted path: provider adapter plus prompt renderer, with folded review handled by a provider-neutral helper when needed.
See `docs/superpowers/plans/2026-06-30-ai-provider-abstraction.md`.
