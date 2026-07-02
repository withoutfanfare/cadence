# Installing Cadence

This guide takes a fresh machine from clone to a working Cadence setup.

Cadence is currently a command-line engine. Scheduled runs are macOS-specific
because the included scheduler uses `launchd`.

## Guided setup (fast path)

Once `cadence` is on your `PATH` (steps 1–3 below), you don't have to fill the
config by hand. From inside your project, ask your AI agent — Claude, Codex, or
any agent that can run a shell — to **"set up this project with Cadence"**. It
runs the `cadence-setup` skill, which interviews you for the folders and choices,
discovers your Linear ids (`cadence linear teams|projects|me`), picks the Linear
or task-file backend, detects Grove/Clio, writes `cadence/.env`, and validates it
with `cadence doctor`. The manual steps below are the same process done by hand,
and remain the reference.

## 1. Prerequisites

Install or confirm these commands are available:

```bash
git --version
python3 --version
bash --version
```

Optional, depending on your profile:

```bash
gh --version        # useful for GitHub PR operations
grove --version     # only if WORKTREE_TOOL=grove (Laravel Herd worktrees)
claude --help       # if ORCHESTRATOR_* resolves to claude
codex --help        # if ORCHESTRATOR_* resolves to codex
kimi --help         # if ORCHESTRATOR_* resolves to kimi
opencode --help     # if ORCHESTRATOR_* resolves to opencode
```

The lead loop provider is selected with `cadence providers set`, which updates
the active config file with `ORCHESTRATOR_<STAGE>=provider:model` values.
`provider` must be one of `claude`, `codex`, `kimi`, or `opencode`. Use
`cadence providers roles` to see what each slot does. See
[AI Provider Roles](PROVIDERS.md) and
[Provider Switching Examples](CONFIGURATION.md#provider-switching-examples) for
copyable all-Codex, mixed-provider, Kimi, and OpenCode profiles.

Do not switch providers by putting `provider:model` into `MODEL_*` aliases.
Those are legacy model-name-only fallbacks. Likewise, `BUILD_IMPLEMENTER` takes
only the provider name, for example `codex`, not `codex:gpt-5.4`.

By default the build loop uses plain `git worktree`, so nothing beyond Git is
needed. Set `WORKTREE_TOOL=grove` only if you use grove for Laravel Herd sites.

You also need:

- A Linear personal API key from Linear Settings -> API.
- A Linear team and project that Cadence is allowed to manage.
- A local checkout of the application repo that the build loop will edit.
- A directory where Cadence can create throwaway worktrees.

## 2. Clone Cadence

```bash
git clone https://github.com/withoutfanfare/cadence.git
cd cadence
```

## 3. Put `cadence` on PATH

The repo ships a single executable at `bin/cadence`. Symlink it into a directory
on your `PATH`:

```bash
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/bin/cadence" "$HOME/.local/bin/cadence"
```

If `~/.local/bin` is not already on your `PATH`, add it to your shell startup
file:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.zshrc"
export PATH="$HOME/.local/bin:$PATH"
```

Check the command resolves:

```bash
cadence help
```

## 4. Create the project config

```bash
mkdir -p /path/to/app/cadence
cp .env.example /path/to/app/cadence/.env
$EDITOR /path/to/app/cadence/.env
```

Cadence will find this file when you run manual commands from `/path/to/app`.
Existing root `.env` installs still work, but new project profiles should use
`cadence/.env`.

Optional shortcut:

```bash
mkdir -p "$CADENCE_HOME/profiles"
printf '%s\n' /path/to/app/cadence/.env > "$CADENCE_HOME/profiles/app"
cadence --profile app doctor
```

At minimum, fill:

```dotenv
LINEAR_API_KEY=lin_api_xxx
LINEAR_TEAM_ID=...
LINEAR_PROJECT_ID=...
LINEAR_TEAM_NAME="Your Team"
LINEAR_ASSIGNEE_ID=...

TASK_BACKEND=linear

REPO_SLUG=owner/app
BASE_BRANCH=develop
PROJECT_DIR=/Users/you/Code/app
WORKTREE_BASE=/Users/you/Code/app-worktrees
```

Read [Configuration](CONFIGURATION.md) for the full reference.

For a local task file instead of Linear, set `TASK_BACKEND=file`, create
`cadence/tasks.md`, and leave the Linear values blank. The file format is shown
in [Configuration](CONFIGURATION.md#task-backend).

### Finding Linear IDs

After adding `LINEAR_API_KEY`, use Cadence to list teams:

```bash
cadence linear teams
```

Use the returned team `id` for `LINEAR_TEAM_ID`.

Once `LINEAR_TEAM_ID` is set, Cadence can list that team's projects and your own
user id for you — no API explorer needed:

```bash
cadence linear projects   # pick the id for LINEAR_PROJECT_ID
cadence linear me         # your id, name, and email for LINEAR_ASSIGNEE_ID
```

Set `LINEAR_ASSIGNEE_ID` to the user whose assigned issues Cadence should act
on (usually yourself — `cadence linear me`). Cadence will not intentionally
operate on issues assigned to somebody else.

## 5. Check the Setup

Run:

```bash
cadence doctor
```

The critical checks are:

- The active config file exists, and `cadence doctor` reports which file it is using.
- The selected orchestrator provider CLI and `python3` are on `PATH`.
- The configured **model** is usable, not just the CLI — for `kimi`, doctor checks
  the model exists in `~/.kimi-code/config.toml` (so a wrong name like `kimi:k2`
  is caught at setup, not at the first scheduled run); for other providers it
  prints the resolved `provider:model` so a typo is visible.
- The Linear API key works.
- The configured team is visible to that key.
- The state directory exists.

Warnings about missing launchd plists are expected before you schedule the loops.

## 6. Create the Linear Labels

Cadence uses Linear labels as its state machine. Create the whole set once per
team:

```bash
cadence labels init
```

The command is idempotent — existing labels are reused, and it prints which
labels it created versus which were already present. To add a single label by
hand, use `cadence labels ensure "<name>"`.

Check the full vocabulary is present:

```bash
cadence doctor --labels
```

## 7. Pause Before the First Run

Pause all scheduled and manual loop starts while you inspect the setup:

```bash
cadence pause
cadence status
```

The pause flag lives at:

```text
$CADENCE_STATE_DIR/runs/PAUSED
```

Every loop checks this file before reading or writing work. A paused system skips
manual `cadence run <stage>` commands too.

## 8. Run One Stage Manually

Choose a low-risk first run. Triage is usually best because it only edits Linear
metadata and comments within the configured project.

```bash
cadence resume
cadence run triage
cadence pause
cadence logs triage
cadence feed 20
cadence digest
```

Important: `cadence run <stage>` is live. Do not run `spec`, `build`, or
`revise` until you have deliberately added the matching gate label to an issue
and are ready for the loop to write.

Pausing again immediately after the manual run gives you time to inspect the
Linear changes, logs, and digest before any scheduled loop can continue.

## 9. First 10-minute smoke test

After `cadence doctor` passes and the labels exist, this read-only sequence gives
you a quick picture of the setup:

```bash
cadence help
cadence doctor --labels
cadence queue -v
cadence schedule
cadence inspect
```

`cadence inspect` bundles `doctor`, `status`, `autonomous status`, `schedule`,
`queue -v`, and the recent feed. It is intended for support and onboarding.

The next commands are live, so keep them separate and deliberate:

```bash
cadence resume
cadence run triage
cadence pause
cadence logs triage
cadence feed 20
cadence digest
```

## 10. Schedule Loops on macOS

Project-local `cadence/.env` is supported for manual and scheduled commands.
Scheduled runs use one global launchd job that reads an explicit projects file,
then runs due stages with each project's own config.

First make sure the project has its **own** `CADENCE_STATE_DIR` (see
`CONFIGURATION.md` → Runtime). Sharing one across projects makes their pause flag,
logs, and scheduler markers collide. Create it explicitly, with the execute bit,
so the loop can write to it:

```bash
mkdir -p -m 700 "$HOME/.cadence/projects/app"   # unique per project
```

Set that path in the project's `cadence/.env`:

```dotenv
CADENCE_STATE_DIR=$HOME/.cadence/projects/app
```

Then register the project with the scheduler and opt it in:

```bash
cadence schedule register /path/to/app
printf '\nCADENCE_SCHEDULED=1\n' >> "/path/to/app/cadence/.env"
```

`schedule register` appends the project to the registry file
(`$CADENCE_STATE_DIR/projects.txt` by default) and is idempotent — re-running it
reports "already registered" rather than duplicating the line. Pass a project
directory or a config `.env` path; with no argument it registers the current
directory.

Generate and load the single scheduler job:

```bash
mkdir -p "$HOME/Library/LaunchAgents"
cadence schedule apply
```

This writes `com.cadence.scheduler` and removes older per-stage Cadence plists.
The default cadence is hourly, staggered 15 minutes apart, with conductor work
every 3 hours at `:50`. Change it any time by setting `SCHED_<STAGE>` in a
project config and re-running `cadence schedule apply` — see
[Configuration](CONFIGURATION.md#schedule) for the format.

Check status:

```bash
cadence schedule
cadence schedule status
cadence status
launchctl list | grep cadence
```

Keep Cadence paused until you are ready for scheduled runs:

```bash
cadence pause
```

When ready:

```bash
cadence resume
```

## 11. Update Cadence Later

```bash
cd /path/to/cadence
git pull
cadence doctor
cadence restart
```

Run `cadence restart` after changing launchd plists or moving the Cadence
checkout.

## Troubleshooting

### `cadence: command not found`

Your symlink directory is not on `PATH`, or the symlink points at a moved clone.
Run:

```bash
ls -l "$HOME/.local/bin/cadence"
echo "$PATH"
```

Then recreate the symlink from the Cadence repo:

```bash
ln -sf "$PWD/bin/cadence" "$HOME/.local/bin/cadence"
```

### `LINEAR_API_KEY` missing from the active config

Edit the active config file and set `LINEAR_API_KEY`. The key should be a
personal Linear API key, not a GitHub token and not a Linear webhook secret.

### `team ... not in workspace`

The key is valid but cannot see `LINEAR_TEAM_ID`, or the ID is wrong. Run:

```bash
cadence linear teams
```

Copy the exact `id` value for the intended team.

### selected orchestrator provider not on PATH

Install or log in to the CLI named by `ORCHESTRATOR_TRIAGE`,
`ORCHESTRATOR_SPEC`, `ORCHESTRATOR_BUILD`, `ORCHESTRATOR_REVISE`, and
`ORCHESTRATOR_ADVANCE`, then open a new shell. Run `cadence doctor` again to
verify the provider commands are visible. Scheduled launchd jobs inherit a
smaller environment than your terminal. For scheduled jobs, put
`RUNNER_PATH_PREPEND` in the config file the launchd job actually loads; current
generated jobs use the root `.env` compatibility path unless explicit launchd
config support is added.

For example, to make Codex lead the build loop only:

```bash
cadence providers set --build codex:gpt-5.4 --implementer codex
```

Then run:

```bash
cadence doctor
```
