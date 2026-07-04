# Cadence command cheatsheet

Manual `cadence` commands you can run by hand from the terminal, grouped by what
you'd reach for. `cadence` is `bin/cadence` on your `PATH`.

Global flags: `cadence [--config <path>|--profile <name>] <command>` picks which
project's config to use. `cadence help` prints the built-in summary.

> ⚠️ `cadence run …` **writes**. Pause first (`cadence pause`) if you're only
> inspecting.

## Everyday — check what's happening

| Command | What it does |
|---|---|
| `cadence status` | Live/paused state, launchd jobs, last run per stage |
| `cadence queue` | What needs *you* now — board grouped by agent state (`-v` for detail) |
| `cadence queue --why` | Failed issues grouped by root cause, each with a one-line fix — fix a shared cause once, not N times |
| `cadence feed [n]` | Recent activity feed (default 20 lines) |
| `cadence logs [stage]` | Tail a stage log; no stage = summary of all |
| `cadence digest [date]` | Full run digest for a day (default: today) |
| `cadence overview [--json]` | Cross-project status for every registered project |
| `cadence throughput [days]` | Per-stage rollup of recent runs (default 7 days) |
| `cadence inspect` | One bundle: doctor + status + autonomous + schedule + queue + feed |

## Control the loops

| Command | What it does |
|---|---|
| `cadence pause` | Stop every loop (sets the PAUSED flag) |
| `cadence resume` | Allow loops again |
| `cadence run <stage>` | **Live** — run one loop now. Stages: `triage spec build revise roadmap` |
| `cadence run advance [--dry-run]` | Autonomous advancer (grants gates on `agent:auto`) |
| `cadence restart` | Reload launchd jobs after editing plists |

## Setup & health

| Command | What it does |
|---|---|
| `cadence doctor [--labels]` | Verify config, API key, labels, provider CLIs, schedule |
| `cadence onboard [path]` | Put a project on the scheduler in one step (registry, schedule, doctor); starts paused |
| `cadence offboard [path] [--purge]` | Take a project off the scheduler; deletes nothing without `--purge` |
| `cadence labels init` | Create the Linear label vocabulary |
| `cadence labels list` | Show current labels |
| `cadence labels ensure <name>` | Create one label if missing |
| `cadence providers roles\|show\|set\|help` | Inspect / change which AI runs each role |

## Scheduling & autonomous mode

| Command | What it does |
|---|---|
| `cadence schedule show\|status\|register\|unregister\|tick\|apply` | Manage the single scheduler + project registry |
| `cadence autonomous on\|off\|status` | Flip autonomous mode in the active config |
| `cadence conduct [--dry-run]` | Feed the WIP-limited autonomous queue |

## Task state (read/write the board directly)

| Command | What it does |
|---|---|
| `cadence linear <verb>` | Linear adapter — `teams me projects project-get issues-list issue-get issue-update bulk-label issue-comment issue-relate cycles-list issue-create labels-list` |
| `cadence tasks <verb>` | Local file backend — `list get add update path validate` |

## Occasional / advanced

| Command | What it does |
|---|---|
| `cadence worktree add\|remove\|path` | Build-worktree helper (git or grove) |
| `cadence memory recall\|remember` | Memory adapter |
| `cadence advance decide\|criteria\|repairs` | Advancer decision core |
| `cadence prompt render <stage> … --output <file>` | Render a loop prompt without running it |
| `cadence bakeoff <brief> <filter> [impls]` | Compare implementer CLIs in isolated worktrees |
| `cadence tend` | Run the Clio memory-hygiene pass |
