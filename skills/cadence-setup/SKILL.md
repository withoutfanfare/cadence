---
name: cadence-setup
description: Guided, interactive setup of a Cadence project for any agent (Claude, Codex, or other). Interviews the user for folders and choices, discovers Linear ids for them, chooses the Linear or task-file backend, detects Grove/Clio, writes the project config, and validates it. Use when the user says "set up this project", "set up Cadence", "onboard a project", "configure Cadence for this repo", "cadence setup", or invokes /cadence-setup.
---

# cadence-setup

You are setting up a **new Cadence project** for the user, interactively. Cadence
is a human-gated agent loop; this skill only writes configuration and validates
it — it never runs a gated stage (spec/build/revise) on its own.

Work in **British English**. This skill is provider-neutral: use only the shell
and the `cadence` CLI, so it runs the same under Claude, Codex, or any agent.

## Ground rules

- **Ask one thing at a time and wait** for the answer. Do not assume folders,
  ids, or preferences — this is the one place where guessing is expensive.
- **Fill blanks only.** If a `cadence/.env` already exists for the project, show
  it and ask before changing anything; never overwrite a value the user has set.
- **Confirm before every write** to the config or the scheduler registry.
- Get any timestamp from the shell (`date -u +%FT%TZ`); never invent one.
- If a step needs a tool the user doesn't have, say so plainly and offer the
  alternative (e.g. task-file backend instead of Linear) rather than pushing on.

## Step 0 — preconditions

Confirm the CLI resolves and note the engine home:

```bash
cadence help | head -1
echo "CADENCE_HOME=${CADENCE_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v cadence)")")")}"
```

If `cadence` is not found, stop and point the user at
`docs/INSTALL.md` §3 (put `cadence` on PATH), then resume.

## Step 1 — which folder is the project?

Ask for the **code repository the build loop will edit** (`PROJECT_DIR`). If the
user is already in it, offer the current directory as the default. Confirm it is
a git checkout. The config will live at `<PROJECT_DIR>/cadence/.env`.

Create the config directory and start a draft from the template:

```bash
mkdir -p "<PROJECT_DIR>/cadence"
cp "$CADENCE_HOME/.env.example" "<PROJECT_DIR>/cadence/.env"
```

For the rest of this skill, run `cadence` with `--config <PROJECT_DIR>/cadence/.env`
so every command reads the draft you are filling in.

## Step 2 — task backend: Linear or a local file?

Ask: **"Do you want Cadence to work from Linear, or from a local task file?"**

### If Linear

1. Ask for a **personal API key** (Linear → Settings → API → Personal API keys).
   Write it into the draft config as `LINEAR_API_KEY=...`.
2. List the teams the key can see and let the user pick one:
   ```bash
   cadence --config <PROJECT_DIR>/cadence/.env linear teams
   ```
   Set `LINEAR_TEAM_ID` (the `id`) and `LINEAR_TEAM_NAME` (quote it if it has
   spaces).
3. List that team's projects and let the user pick one:
   ```bash
   cadence --config <PROJECT_DIR>/cadence/.env linear projects
   ```
   Set `LINEAR_PROJECT_ID`.
4. Find the user's own Linear id for the assignee scope (Cadence only acts on
   issues assigned to this user):
   ```bash
   cadence --config <PROJECT_DIR>/cadence/.env linear me
   ```
   Confirm the returned name/email is the right person, then set
   `LINEAR_ASSIGNEE_ID` to that `id`. Leave `TASK_BACKEND=linear`.

### If a local task file

Set `TASK_BACKEND=file` and `TASK_FILE=cadence/tasks.md` (relative to
`PROJECT_DIR`), leave the `LINEAR_*` values blank, and create the file:

```bash
printf '# Cadence Tasks\n' > "<PROJECT_DIR>/cadence/tasks.md"
```

Point the user at `docs/CONFIGURATION.md#task-backend` for the task format.

## Step 3 — repo and worktrees

Ask for and set:

- `REPO_SLUG` — `owner/name` for GitHub PR operations.
- `BASE_BRANCH` — the branch draft PRs target (e.g. `develop`).
- `WORKTREE_BASE` — a directory where Cadence may create throwaway build
  worktrees (kept separate from `PROJECT_DIR`).

## Step 4 — Grove?

Grove is only needed for Laravel Herd worktree sites; the default `git` backend
needs nothing extra. Check and ask:

```bash
command -v grove >/dev/null && echo "grove: installed" || echo "grove: not found"
```

Ask **"Do you use Grove / Laravel Herd sites for this project?"** Set
`WORKTREE_TOOL=grove` only if they say yes and it is installed; otherwise leave
`WORKTREE_TOOL=git`.

## Step 5 — Clio?

Clio is an optional shared-memory MCP server. Ask **"Do you use Clio for shared
memory?"** If yes, set `MEMORY_BACKEND=clio` and ask for `MEMORY_NAMESPACE`;
otherwise leave `MEMORY_BACKEND=markdown` (files under the engine's `memory/`).

## Step 6 — verification gates (optional)

Ask for the project's lint, test, and analyse commands. Any blank gate is
skipped. **Quote any command containing spaces**, and do not use backslash-escaped
quotes inside a value (use the other quote style) — the config is sourced by bash:

```dotenv
GATE_LINT="composer lint"
GATE_TEST="composer test"
GATE_ANALYSE=
```

## Step 7 — provider (optional)

The default lead provider is `claude`. If the user wants a different one for some
or all stages, use the dedicated command rather than editing by hand:

```bash
cadence --config <PROJECT_DIR>/cadence/.env providers roles   # what each slot does
cadence --config <PROJECT_DIR>/cadence/.env providers set --build codex:gpt-5.4 --implementer codex
```

## Step 8 — per-project state directory

Give this project its **own** state directory so its pause flag, logs, and
scheduler markers never collide with another project's:

```bash
mkdir -p -m 700 "$HOME/.cadence/projects/<name>"
```

Set `CADENCE_STATE_DIR=$HOME/.cadence/projects/<name>` in the draft config.

## Step 9 — show, confirm, and validate

Show the user the finished `cadence/.env` (mask the API key) and confirm it reads
correctly. Then validate:

```bash
cadence --config <PROJECT_DIR>/cadence/.env doctor
```

`doctor` verifies the provider CLIs **and** the configured model names (for `kimi`
it checks the model exists in `~/.kimi-code/config.toml`) — so a wrong model like
`kimi:k2` is caught here rather than failing at the first run. Fix any ❌ before
moving on.

For a Linear backend, create the label vocabulary once per team and re-check:

```bash
cadence --config <PROJECT_DIR>/cadence/.env labels init
cadence --config <PROJECT_DIR>/cadence/.env doctor --labels
```

Resolve any red doctor findings before moving on.

## Step 10 — scheduling (opt-in, macOS)

Ask **"Do you want this project to run on the scheduler?"** Scheduled runs are
macOS-only (launchd). If yes:

```bash
cadence schedule register "<PROJECT_DIR>"          # add to the registry
```

Then set `CADENCE_SCHEDULED=1` in the project config and load the single global
scheduler:

```bash
cadence schedule apply
cadence schedule status
```

Adjust per-stage timing later with the `SCHED_*` values
(`docs/CONFIGURATION.md#schedule`).

## Step 11 — hand back safely

Leave the system paused until the user is ready, and tell them the deliberate
first run:

```bash
cadence --config <PROJECT_DIR>/cadence/.env pause
cadence --config <PROJECT_DIR>/cadence/.env run triage   # only when they choose to
```

Finish with a short summary: the config path, the backend, the state dir, whether
scheduling is on, and the next action that is theirs to take (triage first;
gates like `agent:spec`/`agent:build` are added by a human, never by Cadence).
Mention `cadence overview` — once more than one project is set up, it shows all of
them (health, last run per stage) in one glance, as does the SwiftBar menu bar.
