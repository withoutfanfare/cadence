# Configuring Cadence

Cadence reads profile-specific values from `.env` in the repo root. The engine
files and skills are generic; the `.env` file tells Cadence which Linear project,
repo, models, memory backend, and verification commands to use.

Copy the example first:

```bash
cp .env.example .env
```

Because the shell scripts source `.env`, quote values that contain spaces:

```dotenv
LINEAR_TEAM_NAME="Modern Print Works"
RUNNER_PATH_PREPEND="$HOME/Library/Application Support/Herd/bin"
```

## Linear

| Variable | Required | Description |
| --- | --- | --- |
| `LINEAR_API_KEY` | Yes | Personal API key from Linear Settings -> API. |
| `LINEAR_TEAM_ID` | Yes | Team ID Cadence is allowed to operate in. `cadence doctor` verifies this. |
| `LINEAR_PROJECT_ID` | Yes | Project ID used to scope every issue query. |
| `LINEAR_TEAM_NAME` | Recommended | Display name used in status output and human-facing checks. Quote it if it contains spaces. |
| `LINEAR_ASSIGNEE_ID` | Yes | User ID whose assigned issues Cadence may act on. |

Cadence always scopes issue lists to both `LINEAR_TEAM_ID` and
`LINEAR_PROJECT_ID`. The loop skills also query only issues assigned to
`LINEAR_ASSIGNEE_ID`.

## Repository

| Variable | Required | Description |
| --- | --- | --- |
| `REPO_SLUG` | Build/revise | GitHub repository slug, for example `owner/app`. |
| `BASE_BRANCH` | Build/revise | Branch used as the base for generated worktrees and draft PRs. Defaults to `develop`. |
| `PROJECT_DIR` | Build/revise | Main checkout of the app repo Cadence works on. |
| `WORKTREE_BASE` | Build/revise | Directory where build/revise create temporary worktrees. |
| `WORKTREE_TOOL` | Build/revise | `git` (default) or `grove` — how worktrees are created. |

`PROJECT_DIR` should be a normal checkout of the application repo. `WORKTREE_BASE`
should be a separate directory so generated worktrees do not clutter the main
checkout.

`WORKTREE_TOOL` chooses how the build and revise loops create their isolated
worktrees:

- `git` (default) uses plain `git worktree` and needs nothing beyond Git. This is
  the simplest path and the right choice for most users.
- `grove` uses the `grove` command to manage a [Laravel Herd](https://herd.laravel.com)
  dev site per worktree (its own `.test` URL). Choose this only if you already use
  grove; it requires the `grove` command on `PATH` and is intended for the author's
  team. With `grove`, keep branch identifiers short so the generated Herd domain
  stays under Herd's SSL length limit.

Either way the loops drive worktrees through `cadence worktree add|remove|path`, so
the skills themselves stay tool-agnostic.

## Orchestrators, Reviewer, and Implementer

| Variable | Default | Description |
| --- | --- | --- |
| `ORCHESTRATOR_PROVIDER` | `claude` | Default provider used when a per-stage orchestrator value omits `provider:`. |
| `ORCHESTRATOR_TRIAGE` | `claude:sonnet` | Provider and model for the triage loop. |
| `ORCHESTRATOR_SPEC` | `claude:opus` | Provider and model for the spec loop. |
| `ORCHESTRATOR_BUILD` | `claude:opus` | Provider and model for the build loop orchestrator. |
| `ORCHESTRATOR_REVISE` | `claude:sonnet` | Provider and model for the revise loop orchestrator. |
| `ORCHESTRATOR_ADVANCE` | `claude:sonnet` | Provider and model for the advancer orchestrator. |
| `REVIEW_PROVIDER` | `claude` | Provider used by folded PR/diff reviews. |
| `REVIEW_MODEL` | `opus` | Model used by folded PR/diff reviews. |
| `BUILD_IMPLEMENTER` | `claude` | Coding agent used by the build loop: `claude`, `kimi`, `opencode`, or `codex`. |

The build loop orchestrator still reviews the implementer's diff and owns the PR
workflow. `BUILD_IMPLEMENTER` controls only the coding step.

See [Implementers](IMPLEMENTERS.md) for the dispatch contract.

Legacy fallback aliases from older profiles remain supported for compatibility
with `.env.example`: `MODEL_TRIAGE`, `MODEL_SPEC`, `MODEL_BUILD`,
`MODEL_REVISE`, and `MODEL_ADVANCE`. Treat them as aliases only; prefer the
`ORCHESTRATOR_*` variables above.

### Provider Switching Examples

Every orchestrator setting uses `provider:model` format. Supported provider
names are `claude`, `codex`, `kimi`, and `opencode`. The model part is passed
through to that provider's CLI, so use a model alias that provider accepts.

Use the helper command for routine changes:

```bash
cadence providers roles
cadence providers show
cadence providers set --all codex:gpt-5.4 --implementer codex
cadence providers set --build opencode:zai-coding-plan/glm-5.2 --review claude:opus
cadence doctor
```

`roles` explains what each provider slot does. `show` prints the effective raw
settings. `set` edits only the provider-related keys in `.env` and preserves
unrelated profile values and comments.

To make Codex the lead orchestrator for every loop:

```bash
cadence providers set --all codex:gpt-5.4 --review codex:gpt-5.4 --implementer codex
```

To keep Claude on planning stages but use Codex as the build orchestrator and
Kimi as the coding implementer:

```bash
cadence providers set --triage claude:sonnet --spec claude:opus --build codex:gpt-5.4 --revise claude:sonnet --advance claude:sonnet --review claude:opus --implementer kimi
```

To try Kimi as the lead loop provider while keeping Claude as the folded PR
reviewer:

```bash
cadence providers set --all kimi:k2 --review claude:opus --implementer kimi
```

To use OpenCode for build/revise only:

```bash
cadence providers set --build opencode:zai-coding-plan/glm-5.2 --revise opencode:zai-coding-plan/glm-5.2 --review opencode:zai-coding-plan/glm-5.2 --implementer opencode
```

For a one-off manual run, override values in the command environment without
editing `.env`:

```bash
ORCHESTRATOR_BUILD=codex:gpt-5.4
BUILD_IMPLEMENTER=codex
cadence run build
```

After changing providers, run:

```bash
cadence doctor
```

If you prefer to edit `.env` by hand, use the equivalent keys directly:

```dotenv
ORCHESTRATOR_BUILD=codex:gpt-5.4
REVIEW_PROVIDER=claude
REVIEW_MODEL=opus
BUILD_IMPLEMENTER=kimi
```

## Autonomous Mode

| Variable | Default | Description |
| --- | --- | --- |
| `AUTONOMOUS` | `0` | Set to `1`, `on`, or `true` to enable autonomous mode. Off by default; must be explicitly opted into. |
| `AUTO_MAX_ISSUES_PER_RUN` | `1` | Maximum number of issues the advancer may advance in a single run. Raise once the setup is trusted. |
| `AUTO_MAX_REPAIRS` | `3` | Number of build-to-revise repair cycles allowed before the advancer hands the issue back to a human. |
| `AUTO_COST_CEILING` | unset | Reserved per-run spend ceiling. Each advancer run logs its reported cost; hard enforcement is not yet implemented (the 1-issue/run cap is the real guard). Leave blank. |
| `CONDUCT_WIP` | `1` | Maximum number of issues the conductor will keep carrying `agent:auto` at once. The conduct pass tags candidates only until this cap is reached. Raise once the setup is trusted. |
| `ORCHESTRATOR_ADVANCE` | `claude:sonnet` | Provider and model for the advancer. The folded PR/diff review helper is configured separately via `REVIEW_PROVIDER` and `REVIEW_MODEL`. |
| `REVIEW_PROVIDER` | `claude` | Provider used by folded PR/diff reviews. |
| `REVIEW_MODEL` | `opus` | Model used by folded PR/diff reviews. |

Autonomous mode is independent of `PAUSED` — if `PAUSED` is set, all loops halt
regardless of `AUTONOMOUS`. Setting `AUTONOMOUS=1` only enables the advancer;
it does not override the pause flag or any other gate.

## Schedule

By default every loop runs hourly, staggered 15 minutes apart, with the conductor
every 3 hours. Override any of these per loop with a `SCHED_<STAGE>` value, then run
`cadence schedule apply` (regenerates the launchd plists and reloads them).
`cadence schedule` with no argument prints the live schedule.

| Variable | Default | Job |
| --- | --- | --- |
| `SCHED_TRIAGE` | `:00` | triage loop |
| `SCHED_SPEC` | `:15` | spec loop |
| `SCHED_BUILD` | `:30` | build loop |
| `SCHED_REVISE` | `:45` | revise loop |
| `SCHED_ADVANCE` | `:55` | autonomous advancer |
| `SCHED_CONDUCT` | `3h` | conductor |

Value format — every cadence is clock-aligned to midnight, so firing times are
predictable; stagger loops by giving them distinct minutes:

- `:MM` — hourly, at minute MM (e.g. `:15` runs every hour at `:15`).
- `Nh` — every N hours, at minute 0 (e.g. `4h` → 00:00, 04:00, 08:00, …).
- `Nh@MM` — every N hours, at minute MM (e.g. `4h@30` → 00:30, 04:30, …).

N is 1–24. `cadence schedule apply` validates every value first and refuses to write
a broken
plist. The defaults reproduce the historical schedule, so leaving `SCHED_*` unset
changes nothing. The advancer still grants only one stage per pass, so an
autonomous issue advances at most one stage per `SCHED_ADVANCE` interval.

`cadence schedule apply` always (re)writes the four gated loops; it touches the
advance and conduct jobs only when autonomous mode has already installed them, so
it never enables autonomous on its own.

## Verification Gates

| Variable | Required | Description |
| --- | --- | --- |
| `GATE_LINT` | No | Shell command run after build/revise changes. Blank means skip. |
| `GATE_TEST` | No | Shell command for tests. Blank means skip. |
| `GATE_ANALYSE` | No | Shell command for static analysis or type checks. Blank means skip. |

Examples:

```dotenv
GATE_LINT="composer pint --test"
GATE_TEST="composer test:filter"
GATE_ANALYSE="composer analyse"
```

Commands run from the generated worktree. Keep them deterministic and non-
interactive. If a gate fails, the build loop gives the implementer one repair
turn, then escalates to `agent:needs-attention` if it still fails.

## Runtime

| Variable | Default | Description |
| --- | --- | --- |
| `CADENCE_STATE_DIR` | `$HOME/.cadence` | Logs, digests, activity feed, machine ledger, and pause flag. |
| `NOTIFY` | `on` | macOS notifications for runs that did work, paused, or **failed**. Failures (non-zero exit or reported errors) use a distinct title and "Basso" sound and are always also recorded in the dated digest and activity feed. `off` silences the notifications only; the digest/feed records are kept. |
| `RUNNER_PATH_PREPEND` | unset | Optional directory prepended to `PATH` for loop runners. |

Use `RUNNER_PATH_PREPEND` when launchd cannot find project-specific tooling:

```dotenv
RUNNER_PATH_PREPEND="$HOME/Library/Application Support/Herd/bin"
```

## Memory

| Variable | Default | Description |
| --- | --- | --- |
| `MEMORY_BACKEND` | `markdown` | `markdown` or `clio`. |
| `MEMORY_DIR` | `$CADENCE_HOME/memory` | Directory for markdown memory rules. |
| `MEMORY_NAMESPACE` | empty | Clio namespace when `MEMORY_BACKEND=clio`. |

The markdown backend stores one rule per file. The Clio backend is used from
agent tools, not from the Python memory adapter.

## Example Minimal Profile

```dotenv
LINEAR_API_KEY=lin_api_xxx
LINEAR_TEAM_ID=team-id
LINEAR_PROJECT_ID=project-id
LINEAR_TEAM_NAME="Example Team"
LINEAR_ASSIGNEE_ID=user-id

REPO_SLUG=example/app
BASE_BRANCH=develop
PROJECT_DIR=/Users/you/Code/app
WORKTREE_BASE=/Users/you/Code/app-worktrees

ORCHESTRATOR_PROVIDER=claude
ORCHESTRATOR_TRIAGE=claude:sonnet
ORCHESTRATOR_SPEC=claude:opus
ORCHESTRATOR_BUILD=claude:opus
ORCHESTRATOR_REVISE=claude:sonnet
ORCHESTRATOR_ADVANCE=claude:sonnet
REVIEW_PROVIDER=claude
REVIEW_MODEL=opus
BUILD_IMPLEMENTER=claude

# Legacy fallback aliases retained for compatibility with .env.example
MODEL_TRIAGE=sonnet
MODEL_SPEC=opus
MODEL_BUILD=opus
MODEL_REVISE=sonnet
MODEL_ADVANCE=sonnet

GATE_LINT=
GATE_TEST=
GATE_ANALYSE=

MEMORY_BACKEND=markdown
CADENCE_STATE_DIR=
```

Leaving `CADENCE_STATE_DIR` blank uses `$HOME/.cadence`.
