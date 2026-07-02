# Operating Cadence

This guide covers the commands you use after installation.

## Command Overview

Daily read-only commands:

```bash
cadence status          # live/paused state, launchd jobs, recent runs (one project)
cadence overview        # cross-project glance: health + last run per stage, all projects
cadence overview --json # same, machine-readable (used by the menu-bar plugin)
cadence doctor          # verify local setup (providers, models, key, labels)
cadence doctor --labels # verify the Linear label vocabulary exists
cadence logs triage     # tail one stage log; conduct is supported too
cadence feed 30         # recent activity lines
cadence queue [-v]      # your move: board overview grouped by agent state
cadence digest          # today's full digest, UTC date
cadence throughput 30   # per-stage rollup from the machine ledger
cadence schedule        # show the active config's stage cadence
cadence schedule status # show registered scheduled projects
cadence inspect         # read-only support bundle
```

Live control commands:

```bash
cadence pause           # stop all loops before they do work
cadence resume          # allow loops to run again
cadence run triage      # run one stage now; live unless paused
cadence restart         # reload launchd jobs
cadence schedule apply  # regenerate and reload the single scheduler plist
cadence schedule register [path]  # add a project to the scheduler registry
```

Autonomous and maintainer commands:

```bash
cadence autonomous on|off|status
cadence conduct --dry-run
cadence labels init|list|ensure <name>
cadence bakeoff <brief-file> <test-filter> [implementers]
cadence memory recall
cadence worktree add|remove|path
```

## Pause and Resume

Pause before changing config, moving the checkout, editing labels manually, or
testing a new install:

```bash
cadence pause
```

This creates:

```text
$CADENCE_STATE_DIR/runs/PAUSED
```

Every loop checks that file before doing work. Resume with:

```bash
cadence resume
```

Manual runs check the same pause flag. If Cadence is paused, `cadence run
triage` exits without reading or writing work.

## Running a Stage Manually

Manual runs are useful for setup verification and debugging:

```bash
cadence run triage
cadence run spec
cadence run build
cadence run revise
```

All manual runs are live. Only run `spec`, `build`, or `revise` when the relevant
Linear issue has been deliberately gated by a human with `agent:spec`,
`agent:build`, or `agent:revise`.

## Reading Results

Use the board overview to see what needs you right now:

```bash
cadence queue [-v]
```

Issues are grouped by agent state (grant spec, grant build, review PR, needs-you,
failed), with in-flight and parked counts. Read-only — safe even while paused;
`-v` expands each actionable issue to its title and URL.

Use the short feed for a glance:

```bash
cadence feed 20
```

Use the digest for the full human-readable record:

```bash
cadence digest
cadence digest 2026-06-26
```

The files live under:

```text
$CADENCE_STATE_DIR/runs/
```

For a per-stage rollup of recent activity (how much each loop produced, and any
errors), use throughput — it aggregates the machine ledger over a day window and
includes autonomous `advance` and `conduct` activity:

```bash
cadence throughput        # last 7 days
cadence throughput 30     # last 30 days
```

Read-only. Runs with no timestamp in the ledger are reported separately rather
than silently dropped.

## Logs

For one loop:

```bash
cadence logs build
```

For a summary across loops:

```bash
cadence logs
```

launchd stdout and stderr logs live under:

```text
$CADENCE_STATE_DIR/logs/
```

`cadence logs conduct` shows conductor activity recorded by `cadence conduct`.

## Notifications and Failure Alerts

When `NOTIFY=on` (the default), a run that does something fires a macOS
notification:

- A **live run that produced work** — or one that needs your move
  (spec/build/revise) — with the "Glass" sound.
- A **paused** run — its reason, with the "Funk" sound.
- A **failed** run — a loop that exited non-zero or reported errors — titled
  `Cadence <stage> — FAILED` with the "Basso" sound.

A failure is never silent even if you miss the notification: it is also written to
the dated digest (`cadence digest`) and the activity feed (`cadence feed 20`), and
the run's non-zero exit is preserved. Set `NOTIFY=off` in `.env` to silence the
macOS notifications only — the digest and feed records are kept regardless.

## Human Workflow in Linear

1. Let triage fill blanks and flag issues.
2. Review a triaged issue.
3. Add `agent:spec` when you want a spec.
4. Read the generated spec document.
5. Add `agent:build` when you approve implementation.
6. Review the draft PR opened by the build loop.
7. Merge manually if satisfied, or add `agent:revise` for changes.

Agents do not add downstream gate labels. If an issue is not moving, check which
label it has and whether a human gate is still required.

### Setting a gate on many issues at once

To add or remove a label across a batch of issues, use `bulk-label`. Target
issues either by listing their keys or by selecting everything that currently
carries a label with `--where-label`:

```bash
cadence linear bulk-label STU-201 STU-202 --add agent:spec
cadence linear bulk-label --where-label agent:triaged --add agent:spec --dry-run
```

Every target is scope-checked (team, project, assignee) before any write, so it
can only touch your own in-scope issues. A live run prints the plan and asks for
confirmation; `--dry-run` previews without writing, and `-y`/`--yes` skips the
prompt for scripted use. Full flag and recipe reference:
[Bulk Label cheatsheet](BULK-LABEL.md).

For install and maintenance, the short label helpers cover the common cases:

```bash
cadence labels init
cadence labels list
cadence labels ensure agent:spec
cadence doctor --labels
```

## Autonomous mode (opt-in)

Autonomous mode lets the advancer grant gates on `agent:auto` issues, carrying
them spec → build → self-review → draft PR with no human in the loop. It is OFF
unless `AUTONOMOUS` is enabled, and independent of `PAUSED` (which still halts
everything). The advancer grants gates only; the existing loops do the work on
their schedule, and it stops at a draft PR for you to merge.

Roll it out carefully:

1. **Tag a few issues** for autonomous handling:
   `cadence linear bulk-label <IDs…> --add agent:auto` (or
   `--where-label agent:triaged --add agent:auto`).
2. **Shadow first** — see what it WOULD do without writing:
   `AUTONOMOUS=1 cadence run advance --dry-run`.
3. **Go live** once the shadow decisions look right:

   ```bash
   cadence autonomous on
   ```

   This sets `AUTONOMOUS=on` in the active config. Scheduled advance/conduct
   work is picked up by the single scheduler when `CADENCE_SCHEDULED=1`. Keep
   `AUTO_MAX_ISSUES_PER_RUN=1` and `CONDUCT_WIP=1` at first.

   - `cadence autonomous status` shows the flag and scheduler state.
   - `cadence autonomous off` sets `AUTONOMOUS=0` and removes any legacy
     autonomous launchd jobs. The four gated loops (triage/spec/build/revise) are
     never touched.

On accept it removes `agent:auto` (re-add it if you want more autonomous work
after reviewing). A run with nothing to do — autonomous off, or no `agent:auto`
issues — exits before any model cost. Done/Cancelled issues are skipped even if
still tagged.

### The conductor (what to work on next)

With autonomous mode on, the conductor feeds the queue so you do not have to tag
issues by hand. Every 3 hours it ranks the ready backlog (priority → current cycle
→ oldest), skips anything not buildable yet (held, needs-attention, terminal,
already-auto, and, for Linear, blocked or parent issues with children), and tops
up `agent:auto` to `CONDUCT_WIP` (default 1) — one issue in flight at a time
until you raise it.

- **Shadow it first:** `AUTONOMOUS=on cadence conduct --dry-run` prints which issue
  it would set loose (and, for Linear, which it skipped as blocked or parent work),
  writing nothing to the active task backend. The decision summary is still
  recorded in the normal Cadence feed, digest, and throughput ledger.
- **Schedule it:** set `CADENCE_SCHEDULED=1`; the scheduler runs conductor work
  every 3 hours at `:50` by default. The advancer carries tagged issues through
  the stages between conductor passes.
- **Steer it:** `agent:hold` excludes an issue; raise/lower `CONDUCT_WIP` to speed
  up or slow down; `cadence pause` or `AUTONOMOUS=0` stops it. It never starts an
  issue whose blockers are not done.

## Reclaiming a Stuck Issue

`agent:claimed` means a loop is working on an issue. A claim older than two hours
is treated as stale. Before changing it manually:

```bash
cadence logs
cadence digest
```

If the run crashed, remove `agent:claimed` and inspect any
`agent:needs-attention` label or run log entry.

## Changing the Schedule

Each loop's cadence is config-driven per project. See the active config's
schedule and the registered scheduled projects:

```bash
cadence schedule
cadence schedule status
```

To change it, set the relevant `SCHED_<STAGE>` value in the project's
`cadence/.env` (format and defaults in [Configuration](CONFIGURATION.md#schedule)),
then apply the global scheduler:

```bash
cadence schedule apply
```

`apply` validates the active config, writes `com.cadence.scheduler`, removes
older per-stage Cadence plists, and reloads the scheduler. Project configs are
checked when the scheduler reads them. For example, `SCHED_BUILD=:05` moves the
build loop to `:05` each hour; `SCHED_TRIAGE=4h@0` runs triage every four hours
(00:00, 04:00, …). Use `SCHED_BUILD=off` to disable a stage for one project.

`cadence restart` is the lighter sibling: it reloads the existing plist files
without regenerating them — use it after the Cadence repo moves, or after editing a
plist by hand.

## Running Multiple Projects

One Cadence engine runs any number of projects. There is **one** launchd job
(`com.cadence.scheduler`); everything project-specific lives in each project's own
`cadence/.env`. The scheduler does not get a plist per project or per stage.

How it fits together:

- **One config per project** — `<project>/cadence/.env`, holding that project's
  Linear/task ids, repo, gates, providers, and `SCHED_*` timings. Set these up by
  hand ([Installation](INSTALL.md#4-create-the-project-config)) or ask your agent
  to run the `cadence-setup` skill ("set up this project with Cadence").
- **A registry** lists which projects the scheduler should visit — one line per
  project, `$CADENCE_STATE_DIR/projects.txt` by default (override with
  `CADENCE_PROJECTS_FILE`). Add a project with:

  ```bash
  cadence schedule register /path/to/app     # or a config .env path; defaults to cwd
  ```

  It is idempotent and prints the registry and config paths it resolved.
- **Opt each project in** with `CADENCE_SCHEDULED=1` in its config. A registered
  project without that flag is listed but skipped.
- **Give each project its own `CADENCE_STATE_DIR`.** Projects that share one
  collide on the pause flag, logs, and scheduler run-markers — one can silently
  skip another's slot. `cadence schedule status` and every scheduler tick warn
  when two registered projects resolve to the same state directory.
- **Apply once, globally** — `cadence schedule apply` (re)writes the single
  scheduler job. You only re-apply when the launchd job itself must change, not
  when you add a project; the scheduler re-reads the registry every tick.

Check what is registered and whether each project is enabled:

```bash
cadence schedule status
```

For a live cross-project glance — health, per-stage last run, and recent activity
for every registered project in one view — use:

```bash
cadence overview          # human table
cadence overview --json   # machine-readable (the menu-bar plugin consumes this)
```

`overview` is read-only and reads each project's own state directory; a project
shows as `paused`, `failed` (a recent run reported errors), `ok`, or `idle`.

Each tick runs at most `CADENCE_SCHEDULER_MAX_RUNS` stages across all projects
(default 1), so many projects share the scheduler fairly rather than one project
starving the rest. `cadence pause` is per state directory — pausing one project
does not pause the others.

## Menu bar (SwiftBar)

Two optional [SwiftBar](https://swiftbar.app) plugins in `assets/swiftbar/` give an
ambient, multi-project view — both cover **every registered project**, not just one:

- `cadence.1m.sh` — **loop monitor**. The menu-bar glyph aggregates health across
  projects (worst state wins: failed → paused → ok → idle). The dropdown shows one
  section per project — per-stage last result and recent activity — with
  pause/resume, run-a-stage, and view-logs actions scoped to that project. Backed
  by `cadence overview --json`.
- `cadence-inbox.5m.py` — **gate inbox**. One section per project of items awaiting
  your move, with one-click gate grants (via `assets/cadence-grant.sh`, scoped to
  that project's config and backend). It follows each project's `TASK_BACKEND`:
  Linear projects list `linear issues-list`; **file projects** (`TASK_BACKEND=file`)
  list `tasks list` and also show an **Open tasks · backlog** section of ungated,
  open tasks, so the whole `tasks.md` is visible before anything is gated. The badge
  counts only the time-sensitive set (PRs + escalations) across all projects.

Install by symlinking both into your SwiftBar plugin folder, for example:

```bash
ln -s "$PWD/assets/swiftbar/cadence.1m.sh" "$HOME/path/to/SwiftBar/Plugins/"
ln -s "$PWD/assets/swiftbar/cadence-inbox.5m.py" "$HOME/path/to/SwiftBar/Plugins/"
```

The refresh interval is in each filename (`.1m.`, `.5m.`); the inbox polls less
often because it calls the Linear API.

## Maintenance Helpers

### Inspect

`cadence inspect` is a read-only bundle for support and onboarding. It prints
`doctor`, `status`, `autonomous status`, the schedule, `queue -v`, and the recent
feed in one place.

### Implementer bake-off

`cadence bakeoff <brief-file> <test-filter> [implementers]` runs the same
implementation brief through the selected implementer CLIs in isolated worktrees,
runs the configured test gate, and writes a comparison report to
`$CADENCE_STATE_DIR/runs/implementer-bakeoff.md`.

This is an advanced command. It creates and removes worktrees, may delete the
temporary remote branches it creates, calls model CLIs, and can consume model
budget. Keep it for maintainer experiments, not normal issue flow.

## What Writes?

Read-only or local-reporting commands:

```text
status, overview, doctor, doctor --labels, logs, feed, queue, digest, throughput,
schedule, schedule status, inspect, labels list, conduct --dry-run
```

Commands with live side effects:

```text
run, schedule apply, schedule register, autonomous on|off, labels init,
labels ensure, linear issue-update, linear bulk-label without --dry-run,
worktree add/remove, bakeoff
```

`schedule register` only edits the local scheduler registry file; `linear teams`,
`linear me`, and `linear projects` are read-only lookups.

## Troubleshooting

### A loop does nothing

Check:

```bash
cadence status
cadence queue -v
cadence feed 20
cadence logs
cadence digest
cadence doctor
```

Common causes:

- Cadence is paused.
- `TASK_BACKEND=file` is selected and `TASK_FILE` is missing or has no task with
  the required agent label.
- The issue is missing the required human gate label.
- The issue has `agent:hold`, `agent:superseded`, or `agent:needs-human`.
- The issue is not assigned to `LINEAR_ASSIGNEE_ID`.
- The issue is outside `LINEAR_PROJECT_ID`.

### A scheduled job cannot find project tools

launchd has a smaller environment than your terminal. Add the needed tool
directory to `.env`:

```dotenv
RUNNER_PATH_PREPEND="/path/to/tool/bin"
```

Then restart:

```bash
cadence restart
```

### Linear writes land in the wrong place

Pause immediately:

```bash
cadence pause
```

Then verify:

```bash
cadence linear teams
cadence doctor
```

Cadence should only proceed when the configured `LINEAR_TEAM_ID` is visible and
all issue queries are scoped to the configured project.

### Build or revise fails gates

Read the build or revise log and the digest:

```bash
cadence logs build
cadence digest
```

The loop gives the implementer one repair attempt. If gates still fail, the
issue should be labelled `agent:needs-attention` for manual investigation.
