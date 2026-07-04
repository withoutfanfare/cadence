# Configuring Cadence

Cadence reads profile-specific values from the active config file. The engine
files and skills are generic; the config file tells Cadence which task backend,
repo, models, memory backend, and verification commands to use.

For front-door `cadence` commands, config resolves in this order:

1. `cadence --config /path/to/cadence/.env ...` sets `CADENCE_CONFIG` for that
   invocation and wins over any ambient value.
2. `cadence --profile name ...` reads `$CADENCE_HOME/profiles/name`; the first
   non-comment line is the target config path.
3. `CADENCE_CONFIG`
4. `$PWD/cadence/.env`
5. `$CADENCE_HOME/.env` for existing installs

Scripts invoked directly skip the front door, so ambient `CADENCE_CONFIG` is
their explicit override.

New projects should use `<project repo>/cadence/.env` in the base application
checkout (`PROJECT_DIR`) so Cadence does not collide with the app's own `.env`.
Generated worktrees do not get their own Cadence config unless you create one.

Existing root `.env` installs still work, but new project profiles should use
`cadence/.env`.

For a shorter command, create a profile alias that points at the real config:

```bash
mkdir -p "$CADENCE_HOME/profiles"
printf '%s\n' /path/to/app/cadence/.env > "$CADENCE_HOME/profiles/app"
cadence --profile app status
```

Aliases are just path lookups; the config values still live in the target
`cadence/.env`.

Copy the example first:

```bash
mkdir -p /path/to/app/cadence
cp .env.example /path/to/app/cadence/.env
$EDITOR /path/to/app/cadence/.env
```

Because the shell scripts source the active config file, quote values that
contain spaces:

```dotenv
LINEAR_TEAM_NAME="Modern Print Works"
RUNNER_PATH_PREPEND="$HOME/Library/Application Support/Herd/bin"
```

A quoted value must not contain a backslash-escaped quote (`\"`); the Python
loader stops at the first quote rather than mirroring bash, and warns. If a value
needs to contain a quote, wrap it in the other quote style instead.

## Linear

| Variable | Required | Description |
| --- | --- | --- |
| `LINEAR_API_KEY` | `TASK_BACKEND=linear` | Personal API key from Linear Settings -> API. |
| `LINEAR_TEAM_ID` | `TASK_BACKEND=linear` | Team ID Cadence is allowed to operate in. `cadence doctor` verifies this. |
| `LINEAR_PROJECT_ID` | `TASK_BACKEND=linear` | Project ID used to scope every issue query. |
| `LINEAR_TEAM_NAME` | Recommended | Display name used in status output and human-facing checks. Quote it if it contains spaces. |
| `LINEAR_ASSIGNEE_ID` | `TASK_BACKEND=linear` | User ID whose assigned issues Cadence may act on. |

Cadence always scopes issue lists to both `LINEAR_TEAM_ID` and
`LINEAR_PROJECT_ID`. The loop skills also query only issues assigned to
`LINEAR_ASSIGNEE_ID`.

## Task Backend

| Variable | Default | Description |
| --- | --- | --- |
| `TASK_BACKEND` | `linear` | `linear` uses the Linear adapter. `file` uses a local markdown task file and skips Linear credential checks. |
| `TASK_FILE` | `cadence/tasks.md` | Local task file for `TASK_BACKEND=file`, resolved relative to `PROJECT_DIR` when not absolute. |

The file backend is intentionally small. It stores human-editable tasks as
markdown sections, exposes them through `cadence tasks list|get|update`, and is
used by `cadence queue` and `cadence conduct` when selected. The full format
rules — what `cadence doctor` validates, plus the label vocabulary — are in
[TASKS.md](TASKS.md):

```markdown
# Cadence Tasks

## TASK-1: Short title
status: open
labels: agent:triaged, Bug

Task body and acceptance notes.
```

Use `linear` when you want Linear documents, project scoping, comments, and PR
back-fill. Use `file` when a local `cadence/tasks.md` board is enough.

## Repository

| Variable | Required | Description |
| --- | --- | --- |
| `REPO_SLUG` | Build/revise | GitHub repository slug, for example `owner/app`. |
| `BASE_BRANCH` | Build/revise | Branch used as the base for generated worktrees and draft PRs. Defaults to `develop`. |
| `PROJECT_DIR` | Build/revise | Main checkout of the app repo Cadence works on. |
| `WORKTREE_BASE` | Build/revise | Directory where build/revise create temporary worktrees. Exported into the loop's environment so external tooling (for example user git hooks) can recognise Cadence's own worktrees. |
| `WORKTREE_TOOL` | Build/revise | `git` (default) or `grove` — how worktrees are created. |

`PROJECT_DIR` should be a normal checkout of the application repo. This is the
base repo whose `cadence/.env` Cadence normally reads. `WORKTREE_BASE` should be
a separate directory so generated worktrees do not clutter the main checkout.

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
the skills themselves stay tool-agnostic. The generated worktree path is
`$WORKTREE_BASE/<branch>`; keep the Cadence config in
`$PROJECT_DIR/cadence/.env`, not in each generated worktree.

## Orchestrators, Reviewer, and Implementer

| Variable | Default | Description |
| --- | --- | --- |
| `ORCHESTRATOR_PROVIDER` | `claude` | Default provider used when a per-stage orchestrator value omits `provider:`. |
| `ORCHESTRATOR_TRIAGE` | `claude:sonnet` | Provider and model for the triage loop. |
| `ORCHESTRATOR_SPEC` | `claude:opus` | Provider and model for the spec loop. |
| `ORCHESTRATOR_BUILD` | `claude:opus` | Provider and model for the build loop orchestrator. |
| `ORCHESTRATOR_REVISE` | `claude:sonnet` | Provider and model for the revise loop orchestrator. |
| `ORCHESTRATOR_ADVANCE` | `claude:sonnet` | Provider and model for the advancer orchestrator. |
| `ORCHESTRATOR_ROADMAP` | `claude:opus` | Provider and model for the roadmap loop. Judgement-heavy stage — elect a high-reasoning model. |
| `REVIEW_PROVIDER` | `claude` | Provider used by folded PR/diff reviews. |
| `REVIEW_MODEL` | `opus` | Model used by folded PR/diff reviews. |
| `BUILD_IMPLEMENTER` | `claude` | Coding agent used by the build loop: `claude`, `kimi`, `opencode`, or `codex`. |

The build loop orchestrator still reviews the implementer's diff and owns the PR
workflow. `BUILD_IMPLEMENTER` controls only the coding step.

See [Implementers](IMPLEMENTERS.md) for the dispatch contract.
See [AI Provider Roles](PROVIDERS.md) for the evergreen provider role map and
the `cadence providers` command reference.

Legacy fallback aliases from older profiles remain supported for compatibility
with `.env.example`: `MODEL_TRIAGE`, `MODEL_SPEC`, `MODEL_BUILD`,
`MODEL_REVISE`, `MODEL_ADVANCE`, and `MODEL_ROADMAP`. Treat them as aliases
only; prefer the `ORCHESTRATOR_*` variables above.

Important: `MODEL_*` values are model names only. Do not put `provider:model`
values there. For example, `MODEL_BUILD=codex:gpt-5.4` expands through the
default provider and becomes `claude:codex:gpt-5.4`, which asks Claude to run a
Codex model name. Use `ORCHESTRATOR_BUILD=codex:gpt-5.4` instead.

`BUILD_IMPLEMENTER` is also provider-only. Use `BUILD_IMPLEMENTER=codex`, not
`BUILD_IMPLEMENTER=codex:gpt-5.4`.

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
settings. `set` edits only the provider-related keys in the active config file
and preserves unrelated profile values and comments.

To make Codex the lead orchestrator for every loop:

```bash
cadence providers set --all codex:gpt-5.4 --review codex:gpt-5.4 --implementer codex
```

To keep Claude on planning stages but use Codex as the build orchestrator and
Kimi as the coding implementer:

```bash
cadence providers set --triage claude:sonnet --spec claude:opus --build codex:gpt-5.4 --revise claude:sonnet --advance claude:sonnet --roadmap claude:opus --review claude:opus --implementer kimi
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
editing the active config file:

```bash
ORCHESTRATOR_BUILD=codex:gpt-5.4
BUILD_IMPLEMENTER=codex
cadence run build
```

After changing providers, run:

```bash
cadence doctor
```

If you prefer to edit the active config file by hand, use the equivalent keys
directly:

```dotenv
ORCHESTRATOR_BUILD=codex:gpt-5.4
REVIEW_PROVIDER=claude
REVIEW_MODEL=opus
BUILD_IMPLEMENTER=kimi
```

Do not use the old alias shape for provider switching:

```dotenv
# Wrong: MODEL_* is model-only, not provider:model
MODEL_BUILD=codex:gpt-5.4

# Wrong: BUILD_IMPLEMENTER is provider-only
BUILD_IMPLEMENTER=codex:gpt-5.4
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

## Roadmapper mode

The roadmap loop is opt-in per project: set `SCHED_ROADMAP` to a cadence to
enable it. A goal only *steers* it — with none, it works against a standing
engineering-quality rubric (real bugs, performance, accessibility, security,
dead code, consistency).

| Variable | Default | Description |
| --- | --- | --- |
| `SCHED_ROADMAP` | `off` | Schedule slot for the roadmap loop (same `:MM`/`Nh@MM` format as the other stages). **This is the on/off switch** — `off` means the loop never runs unattended for the project; set e.g. `24h@20` to enable it. A manual `cadence run roadmap` always runs regardless. |
| `ROADMAP_MAX_OPEN` | `5` | Top-up cap: the roadmap loop keeps at most this many open `agent:proposed` issues on the board. Enforced by the create verbs, not just the prompt. |
| `GOAL_FILE` | `cadence/goal.md` | Optional file-backend goal location, relative to `PROJECT_DIR`. Present and non-empty → it steers the scout; absent → the standing rubric. Linear profiles read the Linear project description instead. |

## Schedule

Cadence uses one launchd job, `com.cadence.scheduler`. That job runs
`cadence schedule tick`; the tick reads an explicit projects file and then runs
due stages with `cadence --config <project>/cadence/.env ...`.

Scheduling is opt-in per project. Add the project folder to
`CADENCE_PROJECTS_FILE`, then set `CADENCE_SCHEDULED=1` in that project's
`cadence/.env`. The global tick launches at most `CADENCE_SCHEDULER_MAX_RUNS`
stages per wake (default `1`), dispatching them through a bounded pool of at most
`CADENCE_SCHEDULER_CONCURRENCY` simultaneous runs (default `4`). `MAX_RUNS` is
the per-tick throughput ceiling and `CONCURRENCY` the parallel width: a fleet
of twenty projects raises `MAX_RUNS` to cover demand and keeps `CONCURRENCY`
small for API-rate and cost safety. A tick lasts roughly
`ceil(MAX_RUNS / CONCURRENCY)` times the longest run, and each run is capped
at `CADENCE_SCHEDULER_RUN_TIMEOUT` seconds so a hung run cannot hold a pool
slot forever.

`cadence schedule` with no argument prints the stage cadence for the active
config. `cadence schedule status` prints the projects file and whether each
registered project has scheduling enabled.

| Variable | Default | Scope | Description |
| --- | --- | --- | --- |
| `CADENCE_PROJECTS_FILE` | `$CADENCE_STATE_DIR/projects.txt` | scheduler | Newline-separated project folders or explicit `cadence/.env` paths. |
| `CADENCE_SCHEDULER_INTERVAL` | `300` | scheduler | Launchd wake interval in seconds. |
| `CADENCE_SCHEDULER_MAX_RUNS` | `1` | scheduler | Maximum scheduled stage runs per tick across all projects (the throughput ceiling). |
| `CADENCE_SCHEDULER_CONCURRENCY` | `4` | scheduler | How many of a tick's runs execute at once (the width). Effective only when `CADENCE_SCHEDULER_MAX_RUNS` allows more than one run; keep it small for API-rate and cost safety. |
| `CADENCE_SCHEDULER_RUN_TIMEOUT` | `3600` | scheduler | Wall-clock cap in seconds per scheduled run; the child is killed on expiry and the run reported as failed. `0` disables. Sits above `ORCH_TIMEOUT`, which bounds only the model call inside the run. |
| `CADENCE_SCHEDULER_WINDOW_MINUTES` | `5` | scheduler | Due window used to tolerate launchd jitter without catching up old missed runs. |
| `CADENCE_SCHEDULED` | unset/off | project | Set to `1`, `on`, `true`, or `yes` to let the scheduler run this project. |

| Variable | Default | Job |
| --- | --- | --- |
| `SCHED_TRIAGE` | `:00` | triage loop |
| `SCHED_SPEC` | `:15` | spec loop |
| `SCHED_BUILD` | `:30` | build loop |
| `SCHED_REVISE` | `:45` | revise loop |
| `SCHED_ADVANCE` | `:55` | autonomous advancer |
| `SCHED_CONDUCT` | `3h@50` | conductor |

Value format — every cadence is clock-aligned to midnight, so firing times are
predictable; stagger loops by giving them distinct minutes:

- `:MM` — hourly, at minute MM (e.g. `:15` runs every hour at `:15`).
- `Nh` — every N hours, at minute 0 (e.g. `4h` → 00:00, 04:00, 08:00, …).
- `Nh@MM` — every N hours, at minute MM (e.g. `4h@30` → 00:30, 04:30, …).
- `off` — do not schedule this stage for this project.

N is 1–24. `cadence schedule apply` validates the active config before writing
the scheduler plist; project configs are checked when the scheduler reads them.
The scheduler records a small marker in each project's state dir so a jittery
launchd wake cannot run the same stage twice in one due window.

## Verification Gates

| Variable | Required | Description |
| --- | --- | --- |
| `GATE_LINT` | No | Shell command run after build/revise changes. Blank means skip. |
| `GATE_TEST` | No | Shell command for tests. Blank means skip. |
| `GATE_ANALYSE` | No | Shell command for static analysis or type checks. Blank means skip. |

**Scope every gate to the change, not the whole repo.** A gate that runs the
full suite or lints the entire codebase fails on *pre-existing* debt unrelated to
the issue being built — and that blocks **every** build from opening a PR, even a
correct one. CI runs the full suite on the PR; the local gate's only job is to
catch what *this* change broke. `cadence doctor` warns when a gate looks
repo-wide. Prefer, per ecosystem:

```dotenv
# Good — change-scoped
GATE_LINT="./vendor/bin/pint --test --dirty"   # only the worktree's uncommitted change
GATE_TEST="composer test:filter"               # a scoped script, not the full suite
GATE_ANALYSE="./vendor/bin/phpstan analyse"    # after: phpstan analyse --generate-baseline

# Avoid — repo-wide; trips on pre-existing debt and strands unrelated builds
# GATE_LINT="composer lint"   GATE_TEST="composer test"   GATE_ANALYSE="composer analyse"
```

For an analyser with no change-scoped mode, commit a **baseline** (e.g. PHPStan's
`--generate-baseline`) so it flags only newly introduced errors. If a gate can't
be scoped and its debt can't be cleared, blank it — the folded draft-PR review
and CI remain the net.

Commands run from the generated worktree. Keep them deterministic and non-
interactive. If a gate fails, the build loop gives the implementer one repair
turn, then escalates to `agent:needs-attention` if it still fails.

## Runtime

| Variable | Default | Description |
| --- | --- | --- |
| `CADENCE_STATE_DIR` | `$HOME/.cadence` | Logs, digests, activity feed, machine ledger, and pause flag. **Set a unique value per project** — see below. |
| `NOTIFY` | `on` | macOS notifications for runs that did work, paused, or **failed**. Failures (non-zero exit or reported errors) use a distinct title and "Basso" sound and are always also recorded in the dated digest and activity feed. `off` silences the notifications only; the digest/feed records are kept. |
| `RUNNER_PATH_PREPEND` | unset | Optional directory prepended to `PATH` for loop runners. |
| `ORCH_TIMEOUT` | `2700` | Max seconds for any single orchestrator run (all stages). Caps a hung or wedged run — e.g. a model idling in a self-monitoring loop — so it cannot hold the shared build/revise worktree lock indefinitely. Applies to every existing and new project by default; override per profile for unusually slow build+gate cycles. |
| `CADENCE_LOCK_MAX_AGE_SECONDS` | `7200` | Hard ceiling after which a build/revise worktree lock is reclaimed even if its holder PID is still alive (guards against PID recycling and wedged holders). Kept well above `ORCH_TIMEOUT` so a legitimate in-flight build is never stolen. |

`ORCH_TIMEOUT` is the primary robustness lever against a stuck run: the build/revise
worktree lock is released when the run ends, so a lower cap bounds how long a wedged
run can block a project's builds. The default (45 minutes) leaves an honest build in a
fresh worktree — dependency install plus gates — room to finish while still killing
anything genuinely stuck.

**Every project profile must set its own `CADENCE_STATE_DIR`.** If two projects
share one — most easily by both leaving it blank, which defaults to
`$HOME/.cadence` — their pause flag, logs, digests, and scheduler run-markers
collide: pausing one pauses the other, and one project's activity is written over
the other's. Point each project at a unique directory, for example:

```dotenv
CADENCE_STATE_DIR=$HOME/.cadence/projects/<name>
```

Create that directory with normal permissions (`chmod 700`) so the loop can make
its own `logs/` and `runs/` subdirectories. A directory created without the
execute bit fails at run time with `mkdir: .../logs: Permission denied`.

`cadence schedule status` flags any registered projects that resolve to the same
state dir, and the scheduler prints the same warning on each tick — so a shared
dir is caught at setup time rather than silently dropping runs.

Use `RUNNER_PATH_PREPEND` when launchd cannot find project-specific tooling. For
scheduled jobs, put it in the config file the launchd job actually loads; current
generated jobs use the root compatibility config unless explicit launchd config
support is added.

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

TASK_BACKEND=linear
TASK_FILE=cadence/tasks.md

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

# Legacy fallback aliases retained for compatibility with older profiles.
# These are model names only; provider switching belongs in ORCHESTRATOR_*.
MODEL_TRIAGE=sonnet
MODEL_SPEC=opus
MODEL_BUILD=opus
MODEL_REVISE=sonnet
MODEL_ADVANCE=sonnet

GATE_LINT=
GATE_TEST=
GATE_ANALYSE=

MEMORY_BACKEND=markdown
CADENCE_STATE_DIR=$HOME/.cadence/projects/app   # unique per project; chmod 700
```

Leaving `CADENCE_STATE_DIR` blank uses `$HOME/.cadence`. That default is only safe
for a single project — give every project a unique state dir (see **Runtime**
above).
