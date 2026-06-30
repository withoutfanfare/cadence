# Operating Cadence

This guide covers the commands you use after installation.

## Command Overview

```bash
cadence status          # live/paused state, launchd jobs, recent runs
cadence doctor          # verify local setup
cadence pause           # stop all loops before they do work
cadence resume          # allow loops to run again
cadence run triage      # run one stage now; live unless paused
cadence logs triage     # tail one stage log
cadence feed 30         # recent activity lines
cadence queue [-v]      # your move: board overview grouped by agent state
cadence digest          # today's full digest, UTC date
cadence restart         # reload launchd jobs
cadence schedule        # show the live schedule (apply to change it)
cadence autonomous on   # enable autonomous mode + schedule its jobs (off to reverse)
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
errors), use throughput — it aggregates the machine ledger over a day window:

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
prompt for scripted use. Full flag and recipe reference: [Bulk Label
cheatsheet](BULK-LABEL.md).

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

   This sets `AUTONOMOUS=on` in `.env` and loads two launchd jobs — the advancer
   (hourly, just after the gated loops, so it sees a fresh board) and the conductor
   (every 3 hours). Keep `AUTO_MAX_ISSUES_PER_RUN=1` and `CONDUCT_WIP=1` at first.

   - `cadence autonomous status` shows the flag and whether both jobs are loaded.
   - `cadence autonomous off` reverses everything: sets `AUTONOMOUS=0` and unloads
     both jobs. The four gated loops (triage/spec/build/revise) are never touched.

On accept it removes `agent:auto` (re-add it if you want more autonomous work
after reviewing). A run with nothing to do — autonomous off, or no `agent:auto`
issues — exits before any model cost. Done/Cancelled issues are skipped even if
still tagged.

### The conductor (what to work on next)

With autonomous mode on, the conductor feeds the queue so you do not have to tag
issues by hand. Every 3 hours it ranks the ready backlog (priority → current cycle
→ oldest), skips anything blocked, and tops up `agent:auto` to `CONDUCT_WIP`
(default 1) — one issue in flight at a time until you raise it.

- **Shadow it first:** `AUTONOMOUS=on cadence conduct --dry-run` prints which issue
  it would set loose (and which it skipped as blocked), writing nothing.
- **Schedule it:** `cadence autonomous on` loads it (every 3 hours) alongside the
  advancer (hourly) — no manual plist editing. The advancer carries tagged issues
  through the stages between conductor passes.
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

Each loop's cadence is config-driven. See the current schedule:

```bash
cadence schedule
```

To change it, set the relevant `SCHED_<STAGE>` value in `.env` (format and defaults
in [Configuration](CONFIGURATION.md#schedule)), then apply:

```bash
cadence schedule apply
```

`apply` validates every `SCHED_*` value, regenerates the launchd plists, and reloads
them. For example, `SCHED_BUILD=:05` moves the build loop to `:05` each hour;
`SCHED_TRIAGE=4h@0` runs triage every four hours (00:00, 04:00, …).

`cadence restart` is the lighter sibling: it reloads the existing plist files
without regenerating them — use it after the Cadence repo moves, or after editing a
plist by hand.

## Troubleshooting

### A loop does nothing

Check:

```bash
cadence status
cadence logs
```

Common causes:

- Cadence is paused.
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
