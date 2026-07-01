# Multi-Profile Runtime Design

## Goal

Let one Cadence engine work against many project repos without colliding with
each repo's own `.env`, while keeping the first implementation small enough to
trust: manual project-local runs first, named profiles and scheduled
multi-profile runs later.

## Scope

First slice:

- Load project configuration from `cadence/.env` in a target project repo.
- Keep the current repo-root `.env` path as a compatibility fallback.
- Allow an explicit `CADENCE_CONFIG=/path/to/cadence/.env` override.
- Add a small `--config <path>` front-door option for manual commands.
- Auto-detect `$PWD/cadence/.env` when Cadence is launched from a project repo.
- Preserve existing `WORKTREE_TOOL=git|grove` behaviour.
- Define and implement one global launchd scheduler that dispatches per-folder
  configs.

Follow-up slice:

- Add friendly profile aliases, for example `cadence --profile mpw run build`.
- Add a local tasks-file backend once profile loading is stable.

Out of scope for the first slice:

- Running one process across several projects in one invocation.
- Storing arrays of projects in one config file.
- Replacing Linear in existing loop skills.
- Changing how git or grove worktrees are created.

## Configuration Model

Cadence should stop treating the engine repo root as the only natural home for
project configuration. Many app repos already have their own `.env`, so Cadence
uses a namespaced file:

```text
<project repo>/cadence/.env
```

Resolution order:

1. `CADENCE_CONFIG` when set.
2. `--config <path>` from the front-door command, exported as `CADENCE_CONFIG`.
3. `$PWD/cadence/.env` when present.
4. Existing engine-root `$CADENCE_HOME/.env` fallback.

The fallback keeps current installs working. New docs should prefer
`cadence/.env`.

Values inside `cadence/.env` keep the existing shape:

```dotenv
PROJECT_DIR=/Users/you/Code/app
WORKTREE_BASE=/Users/you/Code/app-worktrees
WORKTREE_TOOL=git
LINEAR_PROJECT_ID=...
CADENCE_STATE_DIR=/Users/you/.cadence/app
```

The file remains bash-sourceable. Values containing spaces must stay quoted.

## Command Shape

First slice:

```bash
cadence --config /Users/you/Code/app/cadence/.env doctor
cadence --config /Users/you/Code/app/cadence/.env run triage
cadence --config /Users/you/Code/app/cadence/.env status
```

Or, from the project repo:

```bash
cd /Users/you/Code/app
cadence doctor
cadence run triage
```

This is deliberately more explicit than profiles. It proves the runtime can load
isolated project config before adding a registry.

Second slice:

```bash
cadence --profile app doctor
cadence --profile app run build
```

Profile aliases should be a thin lookup layer over `CADENCE_CONFIG`, not a new
config model.

## State Isolation

Every project profile must have its own `CADENCE_STATE_DIR`. If omitted, the
compatibility default remains `$HOME/.cadence`, but new project-local examples
should set an explicit value such as:

```dotenv
CADENCE_STATE_DIR=$HOME/.cadence/projects/app
```

The pause flag stays per state dir:

```text
$CADENCE_STATE_DIR/runs/PAUSED
```

That keeps pausing one project from stopping every other project.

## Work Backend

The existing switch is enough:

```dotenv
WORKTREE_TOOL=git
WORKTREE_TOOL=grove
```

No extra abstraction is needed in this slice. `git` remains the default and
requires only Git. `grove` remains opt-in for Laravel Herd projects.

## Task Backend

The first implementation should not replace Linear. The backend split is a
separate follow-up after project-local config works.

Target shape:

```dotenv
TASK_BACKEND=linear
TASK_BACKEND=file
TASK_FILE=cadence/tasks.md
```

`linear` keeps the current adapter and label-driven workflow.

`file` should be intentionally modest: a local human-editable tasks file with
status, title, body, and agent labels/states. It should support local planning
and implementation loops without requiring Linear. It does not need GitHub PR
automation in its first version.

## Scheduling

Scheduling uses one launchd job:

```text
com.cadence.scheduler
```

That job runs `cadence schedule tick`. The tick reads an explicit project
registry, loads each project's `cadence/.env`, skips projects without
`CADENCE_SCHEDULED=1`, and runs due stages with `cadence --config ...`.

Default registry:

```text
$CADENCE_STATE_DIR/projects.txt
```

Each non-comment line is either a project folder or an explicit
`cadence/.env` path. The scheduler runs at most `CADENCE_SCHEDULER_MAX_RUNS`
stages per wake, default `1`, and records per-project markers to avoid duplicate
runs when launchd wakes twice in the same due window. This keeps the moving parts
small: one plist, one status command, one global cap.

## Safety

The existing Step 0 safety boundary stays unchanged:

- load config
- create state dirs
- check `PAUSED`
- verify Linear workspace when `TASK_BACKEND=linear`
- only then launch a model

For file-backed tasks, the workspace guard should become a backend-specific
guard. A missing Linear key is not an error when `TASK_BACKEND=file`.

No loop may gain authority to approve its own downstream gate, mark PRs ready,
merge, or write outside its configured project/worktree.

## Implementation Plan Boundary

The implementation plan should split this into small testable tasks:

1. Teach the shell and Python env loaders to read `CADENCE_CONFIG`.
2. Teach the loaders to auto-detect `$PWD/cadence/.env`.
3. Add front-door `--config <path>` handling and tests.
4. Update doctor/docs/examples to prefer `cadence/.env`.
5. Add the single launchd scheduler and avoid per-project/per-stage plists.
6. Defer `--profile` aliases and `TASK_BACKEND=file` to follow-up specs unless
   the first slice stays very small after implementation.

This avoids a big-bang rewrite while still pointing Cadence towards multi-project
use.
