# AI Provider Roles

Cadence can use different AI providers for different jobs. The safest way to
inspect or change those settings is the provider helper:

```bash
cadence providers roles
cadence providers show
cadence providers help
cadence providers set --build codex:gpt-5.4 --implementer codex
cadence doctor
```

Run `cadence doctor` after any provider change. It checks that the selected
provider CLIs are visible on the same runner `PATH` used by scheduled loops.

## Role Map

| Role | Setting | Value shape | What it controls |
| --- | --- | --- | --- |
| Triage orchestrator | `ORCHESTRATOR_TRIAGE` | `provider:model` | Lead model for the triage loop. |
| Spec orchestrator | `ORCHESTRATOR_SPEC` | `provider:model` | Lead model for the spec loop. |
| Build orchestrator | `ORCHESTRATOR_BUILD` | `provider:model` | Lead model for the build loop. |
| Revise orchestrator | `ORCHESTRATOR_REVISE` | `provider:model` | Lead model for the revise loop. |
| Advance orchestrator | `ORCHESTRATOR_ADVANCE` | `provider:model` | Lead model for the autonomous advancer. |
| Folded reviewer | `REVIEW_PROVIDER` + `REVIEW_MODEL` | `provider` + `model` | Provider/model used for folded PR and diff review. |
| Build implementer | `BUILD_IMPLEMENTER` | `provider` | Coding agent provider used inside the build worktree. |

Supported provider names are `claude`, `codex`, `kimi`, and `opencode`.

## The Important Distinction

`ORCHESTRATOR_*` values are provider/model pairs:

```dotenv
ORCHESTRATOR_BUILD=codex:gpt-5.4
```

`BUILD_IMPLEMENTER` is provider-only:

```dotenv
BUILD_IMPLEMENTER=codex
```

The old `MODEL_*` values are legacy Claude model aliases. They are model names
only, not provider/model pairs:

```dotenv
MODEL_BUILD=opus
```

Do not use the old alias shape for provider switching:

```dotenv
# Wrong: MODEL_* is model-only
MODEL_BUILD=codex:gpt-5.4

# Wrong: BUILD_IMPLEMENTER is provider-only
BUILD_IMPLEMENTER=codex:gpt-5.4
```

If `ORCHESTRATOR_BUILD` is missing and `ORCHESTRATOR_PROVIDER=claude`, then
`MODEL_BUILD=codex:gpt-5.4` expands to `claude:codex:gpt-5.4`. That asks Claude
to use a Codex model name, which is not the intended provider switch.

## Common Configurations

### Codex for Build Only

This keeps Claude on planning/revise/advance and folded review, but makes Codex
lead the build loop and write the implementation:

```bash
cadence providers set --build codex:gpt-5.4 --review claude:opus --implementer codex
cadence doctor
```

Result:

```text
triage orchestrator   claude:sonnet
spec orchestrator     claude:opus
build orchestrator    codex:gpt-5.4
revise orchestrator   claude:sonnet
advance orchestrator  claude:sonnet
folded reviewer       claude:opus
build implementer     codex
```

### Codex Across Every Loop

```bash
cadence providers set --all codex:gpt-5.4 --review codex:gpt-5.4 --implementer codex
cadence doctor
```

### Kimi as the Lead Provider, Claude as Reviewer

```bash
cadence providers set --all kimi:k2 --review claude:opus --implementer kimi
cadence doctor
```

### OpenCode for Build and Revise

```bash
cadence providers set --build opencode:zai-coding-plan/glm-5.2 --revise opencode:zai-coding-plan/glm-5.2 --review opencode:zai-coding-plan/glm-5.2 --implementer opencode
cadence doctor
```

## Manual Editing

The helper preserves unrelated `.env` values and comments, so prefer it for
routine changes. If you edit `.env` manually, keep this shape:

```dotenv
ORCHESTRATOR_PROVIDER=claude
ORCHESTRATOR_TRIAGE=claude:sonnet
ORCHESTRATOR_SPEC=claude:opus
ORCHESTRATOR_BUILD=codex:gpt-5.4
ORCHESTRATOR_REVISE=claude:sonnet
ORCHESTRATOR_ADVANCE=claude:sonnet

REVIEW_PROVIDER=claude
REVIEW_MODEL=opus
BUILD_IMPLEMENTER=codex

MODEL_TRIAGE=sonnet
MODEL_SPEC=opus
MODEL_BUILD=opus
MODEL_REVISE=sonnet
MODEL_ADVANCE=sonnet
```

`ORCHESTRATOR_PROVIDER` is only the fallback provider used when a per-stage
`ORCHESTRATOR_*` value is missing or omits `provider:`. It does not override
explicit per-stage settings.
