# Current Capabilities

This page summarises what the current Cadence runtime can do and where the
important files live.

## Runtime Model

Cadence is one generic engine that runs against one active project profile at a
time. The engine lives in the Cadence checkout (`CADENCE_HOME`); project-specific
facts live in the active config file.

An active config can be selected by:

1. `cadence --config /path/to/app/cadence/.env ...`
2. `cadence --profile name ...`, where `$CADENCE_HOME/profiles/name` contains the
   target config path
3. ambient `CADENCE_CONFIG`
4. running from a project checkout that contains `cadence/.env`
5. legacy fallback `$CADENCE_HOME/.env`

New project profiles should use `<project repo>/cadence/.env`. That file is
separate from the application's own `.env`.

## Task Backends

Cadence can read task state from either:

- `TASK_BACKEND=linear` - Linear remains the full workflow backend. Labels are
  the state machine, and Linear project/team/assignee ids scope all issue access.
- `TASK_BACKEND=file` - a small local markdown backend using `TASK_FILE`, default
  `cadence/tasks.md` under `PROJECT_DIR`. It supports `cadence tasks`, `queue`,
  `conduct`, and model loop prompts without requiring Linear credentials.

The same labels drive both backends: `agent:triaged`, `agent:specced`,
`agent:pr-open`, `agent:revised`, `agent:auto`, `agent:proposed`/`agent:later`
for roadmap proposals, and the hold/failure labels.

## Agent Loops

Cadence runs four human-gated loops, plus an optional goal-gated roadmap loop:

- `triage` fills blanks and leaves `agent:triaged` or `agent:needs-human`.
- `spec` runs only after a human adds `agent:spec`, then leaves `agent:specced`.
- `build` runs only after a human adds `agent:build`, creates isolated code work,
  runs gates, and opens a draft PR.
- `revise` runs only after a human adds `agent:revise`, then updates the same
  draft PR and leaves `agent:revised`.
- `roadmap` (optional) is opt-in per project via `SCHED_ROADMAP` (default
  `off`). When enabled it scouts the codebase read-only and files at most
  `ROADMAP_MAX_OPEN` proposal issues carrying `agent:proposed` for a human
  verdict. An optional goal — the Linear project description, or `GOAL_FILE` on
  the file backend — steers it; with no goal it works against a standing
  engineering-quality rubric.

Autonomous mode is opt-in. With `AUTONOMOUS=on`, the advancer can grant gates for
items carrying `agent:auto`, and the conductor can top up that queue. Work still
stops at a draft PR for human merge.

## Worktree-Based Repositories

Code-writing loops are isolated from the base checkout:

- `PROJECT_DIR` is the normal application checkout. This is the base repo Cadence
  reads configuration from and returns to for non-code-writing work.
- `WORKTREE_BASE` is a separate directory where generated worktrees live.
- `WORKTREE_TOOL=git` uses plain `git worktree` and creates paths like
  `$WORKTREE_BASE/<branch>`.
- `WORKTREE_TOOL=grove` delegates add/remove to `grove` for Laravel Herd sites.

The worktree helper is `cadence worktree add|remove|path`. For `git`, `add`
reuses an existing local branch, recovers an existing remote branch when present,
or creates a new branch from `BASE_BRANCH`. `remove` deletes the worktree, deletes
the branch, and prunes stale worktree metadata. For `grove`, the same verbs call
`grove add` and `grove rm`.

The project config does not move into generated worktrees. Keep it in
`<PROJECT_DIR>/cadence/.env`; generated worktrees are disposable code workspaces.

## Scheduling

Scheduling uses one launchd job: `com.cadence.scheduler`. It runs
`cadence schedule tick`, which reads `CADENCE_PROJECTS_FILE` (default
`$CADENCE_STATE_DIR/projects.txt`).

Each line is a project folder or explicit `cadence/.env` path; add one with
`cadence schedule register [path]` (idempotent). A project only runs when its own
config contains `CADENCE_SCHEDULED=1`. The global tick is capped by
`CADENCE_SCHEDULER_MAX_RUNS`, default `1`, so adding projects does not create
unbounded fan-out. See
[Running multiple projects](OPERATING.md#running-multiple-projects).

## State and Logs

Runtime state lives under `CADENCE_STATE_DIR`, default `$HOME/.cadence`:

- `runs/PAUSED` stops all loops for that profile.
- `runs/activity.log` is the chronological feed.
- `runs/runs.jsonl` is the machine-readable ledger.
- `runs/YYYY-MM-DD.md` is the human digest.
- `logs/<stage>.log` stores stage output.

**Give every project profile its own `CADENCE_STATE_DIR`.** Projects that share
one state dir (for example by both leaving it blank, which defaults to
`$HOME/.cadence`) share the same pause flag, logs, digests, and scheduler
run-markers — so pausing one pauses the other and their activity records collide.
Use a unique path per project, such as `$HOME/.cadence/projects/<name>`, and
create it with `chmod 700` so the loop can make its own `logs/` and `runs/`
subdirectories.

## Safety Boundaries

Cadence preserves these boundaries:

- The engine stores no project ids or application paths.
- Every loop checks `PAUSED` before work.
- Linear projects must pass the workspace guard before model launch.
- File-backed projects must have a valid task file before model launch.
- Only build and revise write code, and they do it through isolated worktrees.
- Agents do not grant downstream gate labels, mark PRs ready, merge, or write
  outside the configured project/worktree.

## File Locations

| Purpose | Location |
| --- | --- |
| Cadence engine | `CADENCE_HOME`, the Cadence repo checkout |
| Project config | `<PROJECT_DIR>/cadence/.env` |
| Optional profile alias | `$CADENCE_HOME/profiles/<name>` |
| Local task file | `<PROJECT_DIR>/cadence/tasks.md` by default |
| Generated worktrees | `$WORKTREE_BASE/<branch>` |
| Runtime state and logs | `CADENCE_STATE_DIR` |
| Scheduler project registry | `CADENCE_PROJECTS_FILE`, default `$CADENCE_STATE_DIR/projects.txt` |
