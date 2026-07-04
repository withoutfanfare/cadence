# Operating Cadence

This guide covers the commands you use after installation.

## Command Overview

Daily read-only commands:

```bash
cadence status          # live/paused state, launchd jobs, recent runs (one project)
cadence overview        # cross-project glance: health + last run per stage, all projects
cadence overview --json # same, machine-readable (used by the menu-bar plugin)
cadence doctor          # verify local setup (providers, models, key, gates, labels)
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
cadence onboard [path]  # put a project on the scheduler in one step (registry, CADENCE_SCHEDULED=1, scheduler job, doctor); new projects start paused
cadence offboard [path] [--purge]  # take a project off the scheduler: pause, CADENCE_SCHEDULED=0, unregister; deletes nothing without --purge
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
already-auto, anything without acceptance criteria, and, for Linear, blocked or
parent issues with children), and tops up `agent:auto` to `CONDUCT_WIP`
(default 1) — one issue in flight at a time until you raise it. A task with no
acceptance criteria is never queued, so triage stubs them in. An issue that
stalls into `agent:needs-attention` (or `agent:hold`) releases its WIP slot, so
one stuck item cannot freeze the whole queue — the conductor moves on and feeds
the next.

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

## Roadmapper mode (opt-in)

An advisory scout: on its schedule, a high-reasoning model scans the codebase
read-only and files at most `ROADMAP_MAX_OPEN` proposal issues carrying
`agent:proposed`. It never gates anything, and autonomous mode never picks a
proposal up until you accept it.

1. **Turn it on for a project.** It is opt-in: set `SCHED_ROADMAP` to a cadence
   (e.g. `SCHED_ROADMAP=24h@20` for daily at 00:20) in that project's
   `cadence/.env`. Default is `off`, so no project runs it until you enable it.
2. **Optionally steer it.** Write a goal — the Linear project description, or
   `cadence/goal.md` (or `GOAL_FILE`) on the file backend — and it looks for work
   that serves that goal. With no goal it works against a standing quality rubric
   (real bugs, performance, accessibility, security, dead code, consistency).
3. **Let it run**, or run one now: `cadence run roadmap` (`--dry-run` to see what
   it would propose without filing anything).
4. **Review proposals** on the board:
   - **Accept** — set `agent:spec` (the spec loop strips `agent:proposed`), or
     just remove `agent:proposed` to leave it as normal backlog.
   - **Dismiss for good** — cancel the issue (file backend:
     `status: dismissed`). It will never be re-proposed.
   - **Not now** — cancel **and** add `agent:later`; it may return after 30
     days if it still serves the goal or rubric.

Ignore it and it goes quiet: once `ROADMAP_MAX_OPEN` open proposals sit
unreviewed, runs report "at cap" and file nothing.

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

### Adding and removing projects

`cadence onboard /path/to/app` puts a project on the scheduler in one step and
leaves it paused; `cadence offboard /path/to/app` takes it off again (pause,
`CADENCE_SCHEDULED=0`, unregister — nothing deleted). `--purge` also removes
the project's run history; the config (`cadence/.env`) always stays. When the
last project is offboarded the scheduler job itself is unloaded;
`cadence schedule apply` restores it. The registry primitives remain available
as `cadence schedule register|unregister [path]`.

## Menu bar (SwiftBar)

One optional [SwiftBar](https://swiftbar.app) plugin, `assets/swiftbar/cadence.2m.py`,
gives an ambient, multi-project view covering **every registered project** in a
single menu. It answers one question first — *do I need to do anything?* — then
lets you act.

- **Menu-bar glyph** — the worst state across all projects, in priority order:
  ⚠️ a run failed → 📥 *N* tasks awaiting your move → ⏸ paused → a calm green tick
  when nothing is broken and nothing is waiting. The number is the count of
  time-sensitive tasks (PRs + escalations) across every project.
- **Per project** — an honest one-line status rather than a blanket tick: a glyph
  (⚠️ needs attention · 🔴 *N* awaiting you · ⏸ paused · 🟢 active · ⚪ idle), the
  plain-English state, and a **relative** timestamp ("2h ago", never raw UTC) so you
  can see at a glance whether the status is fresh. Underneath sit the tasks awaiting
  your move (one-click gate grants via `assets/cadence-grant.sh`, scoped to that
  project's config and backend), following each project's `TASK_BACKEND`: Linear
  projects list `linear issues-list`; **file projects** (`TASK_BACKEND=file`) also
  show an **Open · backlog** section of ungated open tasks, so the whole `tasks.md`
  is visible before anything is gated.
- **Stages & controls** — a submenu per project holding the technical detail kept
  out of the main view: each work stage's last result with its relative time and
  its next scheduled run (`next in 12m`, from the project's `SCHED_*` config), a
  single grey `Autonomous  off/on` line (read straight from the project's
  `AUTONOMOUS` config value, not inferred from the last run), then pause/resume,
  run-a-stage, view-logs, and open-board/tasks actions. Backed by
  `cadence overview --json`, which now reports each project's `autonomous` flag.

Install by symlinking it into your SwiftBar plugin folder:

```bash
ln -s "$PWD/assets/swiftbar/cadence.2m.py" "$HOME/path/to/SwiftBar/Plugins/"
```

The refresh interval is in the filename (`.2m.`); it polls every two minutes
because it calls the Linear API once per project. Run
`assets/swiftbar/cadence.2m.py selftest` to check the status and relative-time
logic without touching cadence.

### Controlling a task from the menu bar

Every task in the gate inbox — Linear or file-backed alike — carries a submenu:

- **▶ Advance to <stage>** — grants the next gate (backlog/triaged → spec,
  specced → build, pr-open/revised → revise). Shown only when a forward move
  exists.
- **Set stage** — jump the task to any stage (Triage, Spec, Build, Revise),
  forwards or backwards. Setting a stage grants that gate and clears the others,
  so only one "go" is ever pending. "Triage" clears `agent:triaged` to force a
  clean re-triage.
- **Hold / Release hold** — toggles `agent:hold`, the brake every loop honours.
- **Open** — file tasks open `tasks.md` for hand-editing; Linear issues open in
  Linear.

Each task shows under exactly one stage — its furthest point in the pipeline —
so there is never any ambiguity about where a task actually is.

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
