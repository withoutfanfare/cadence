# Cadence — Implementers

The build loop delegates the *coding* step to a headless agent (the implementer).
The orchestrating loop, selected by `ORCHESTRATOR_<STAGE>`, still owns
everything else: claiming the issue, reading the spec, setting up the worktree,
running gates, reviewing the diff, opening the PR, and setting labels.

Install and configure Cadence first with [Installation](INSTALL.md) and
[Configuration](CONFIGURATION.md). This page is the reference for the build
loop's coding delegation only.

---

## Dispatch — `engine/scripts/run-implementer.sh`

`run-implementer.sh <implementer> <worktree> <brief-file>`

This script is the single place that knows each vendor's invocation. The build
loop calls it and never branches on vendor itself — to add or swap a vendor, edit
only this script.

| Implementer | Invocation | Notes |
|---|---|---|
| `claude` | `claude -p "$(cat IMPLEMENT.md)" --model sonnet --dangerously-skip-permissions` | Baseline; always available |
| `kimi` | `kimi -p "$(cat IMPLEMENT.md)"` | K2; auto-approves by default |
| `opencode` | `opencode run --model "$OPENCODE_MODEL" "$(cat IMPLEMENT.md)"` | Defaults to `zai-coding-plan/glm-5.2` unless `OPENCODE_MODEL` is set |
| `codex` | `codex exec --dangerously-bypass-approvals-and-sandbox -c 'mcp_servers={}' -C "$WORKTREE" --skip-git-repo-check "$(cat IMPLEMENT.md)"` | Strong focused codegen; MCP disabled for headless runs |

Exit codes: `0` clean · `124` timeout · `2` unknown error · `3` bad arguments.

The active implementer is set via `BUILD_IMPLEMENTER` in `.env`. The build loop
passes this value to the script at runtime.

For lead loop provider selection, see `ORCHESTRATOR_*` in `CONFIGURATION.md`.

The default implementer timeout is 1200 seconds. Override it with `IMPL_TIMEOUT`
in the environment if a project routinely needs longer repair turns.

---

## The brief/worktree contract

The orchestrator writes a self-contained `IMPLEMENT.md` brief into the worktree
before invoking the implementer. The brief contains:

- Problem statement (from the spec)
- Exact files to change, with line references
- Approach and constraints
- Acceptance criteria
- The test that must pass
- An explicit "out of scope" section

**The implementer's only job is to edit code in the worktree.** It must not:
- Commit or push anything
- Open or close pull requests
- Write to Linear or any issue tracker
- Install new dependencies without justification in the brief

The worktree is a throwaway branch. The orchestrator handles all git operations
after the implementer returns.

---

## Gate step — one repair turn

After the implementer finishes, the orchestrator runs the configured gates
(`GATE_LINT`, `GATE_TEST`, `GATE_ANALYSE` from `.env`). On failure:

1. The failure output is fed back to the implementer for **one repair turn**.
2. If the repair does not pass all gates, the orchestrator escalates to
   `agent:needs-attention` and stops. It does not keep retrying.

---

## Review independence

The orchestrating loop reviews the implementer's diff **adversarially** — as if
the diff came from an unknown contributor. The review checks correctness, security,
scope creep, and whether the test genuinely guards the change.

This independence is what makes delegation safe: the orchestrator never skips
the review step even when it is also running `claude` as the implementer.

---

## `BUILD_IMPLEMENTER` in `.env`

```dotenv
# Implementer to use for the build loop's coding step.
# Options: claude | kimi | opencode | codex
BUILD_IMPLEMENTER=kimi
```

Override per-run by passing the variable directly:

```bash
BUILD_IMPLEMENTER=codex cadence run build
```
