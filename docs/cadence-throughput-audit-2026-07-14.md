# Cadence throughput and app audit — 14 July 2026

## Outcome

Cadence is not presently limited by model speed. Its effective throughput is
being constrained before useful work starts:

1. the global scheduler admits only one run every five minutes;
2. eight of ten registered projects were paused at the time of review, but
   still consume scheduler admission slots;
3. autonomous mode is intentionally configured for one item in flight per
   project and does not enrol the existing specced backlog; and
4. the app does not accurately show the fleet's health or make the human
   decisions that unblock the backlog quick to perform.

The result is a system which is mostly spending scheduler turns on no-op paused
runs, while work that is ready for the next human gate remains idle. This
matches the reported feeling that Cadence is running but little happens.

No source code, project configuration, scheduler configuration, or task state
was changed by this audit.

## Scope and evidence

This was a read-only review of the current Cadence checkout, native macOS app,
live scheduler/launchd state, project registry, queue state, and seven days of
run records. Runtime observations were collected at approximately 08:21 UTC on
14 July 2026.

The checkout already had unrelated modifications in:

- docs/ARCHITECTURE.md
- engine/prompts/render.py
- engine/tests/test_prompt_render.py

They were preserved and are not assessed here.

### Live fleet snapshot

| Measure | Observed state |
| --- | --- |
| Registered projects | 10 |
| Paused projects | 8 |
| Active projects | 2: Scanway and Portfolio |
| Effective global scheduler capacity | 1 run per five-minute tick |
| Configured concurrent width | 4, but ineffective while capacity is 1 |
| Scheduler under-capacity warnings in current log | 422 |
| Human actions waiting in visible queues, excluding holds | 42 |
| Ready-for-build items | 30 |
| Draft PRs awaiting a human | 3 |
| Failed/needs-attention items | 9 |

The scheduled launchd job is healthy in the narrow sense that it exits zero.
That is not a useful throughput signal: its output shows it continually
launching a single paused project, which then exits cheaply. It is therefore
working as configured, rather than working towards the desired outcome.

## Ranked findings

Severity describes effect on throughput or operator safety. Confidence describes
how directly the current source and live data prove the finding.

### CT-01 — Blocker — paused projects consume the only scheduler slot

**Confidence: confirmed.**

The scheduler considers every project with CADENCE_SCHEDULED=1 as a candidate
(engine/schedule/cli.py:734-742), but does not inspect that project's
CADENCE_STATE_DIR/runs/PAUSED flag before admission. It marks a paused project
as served before launching it (lines 778-788). Run-loop then correctly exits as
paused, but the one permitted scheduler turn has already been spent.

At review time, eight of the ten registered profiles were paused. The scheduler
log showed repeated launches such as a paused Notes revise run and a paused
Modern Print Works advance run, while Portfolio had ready build work. Because
all projects use the same default schedule offsets, each due window is shared
by the entire fleet and fair rotation gives paused projects the same entitlement
as active ones.

**Effect:** active projects get roughly one tenth of the already-small
capacity, even though the paused projects cannot produce work.

**Fix:** exclude a project with its own PAUSED flag from candidate and due
counts, log it as “skipped (paused)”, and do not write its served marker. Keep
the run-loop pause guard as the authoritative race-safe backstop.

### CT-02 — Blocker — global scheduler capacity is effectively fixed at one

**Confidence: confirmed.**

The scheduler reads CADENCE_SCHEDULER_MAX_RUNS from its own launch
environment before it reads any project profile (engine/schedule/cli.py:703-741).
The current launchd job has no scheduler capacity environment values and the
global Cadence home configuration file is absent. None of the project profiles
sets a scheduler limit. Consequently the live process uses the hard-coded
default of one run per tick (line 712).

The configured concurrency of four only controls the executor width after
admission. With one admitted run it cannot create concurrency. The scheduler
has correctly warned “N projects due but max_runs=1” 422 times, yet its status
does not make the missing global configuration ownership clear enough for an
operator to correct it safely.

**Effect:** at most one project/stage can start in a five-minute window,
regardless of how much ready work exists or how many projects are enabled.

**Fix:** give the global scheduler a first-class, discoverable configuration
source and show both its file and effective values in cadence schedule status.
Then set a deliberately measured fleet baseline there, rather than relying on
per-project configuration which the scheduler cannot read at admission time.

**Initial operating baseline, after CT-01 is fixed:** maximum four admissions
per tick and width two, limited to two deliberately enabled projects first.
Observe cost, API rate limits, lock contention, and completed output for a day
before enabling more projects or raising the width.

### CT-03 — Major — Cadence's throughput ledger misses successful agent work

**Confidence: confirmed.**

Run-loop parses each model summary and writes a useful human activity line
(engine/scripts/run-loop.sh:370-461). However, it writes to runs.jsonl only
when the runner reports a failure (lines 462-475). The throughput command reads
only runs.jsonl (engine/throughput/cli.py:104-118).

Portfolio activity proves the discrepancy: several successful spec, build and
advance runs were present in activity.log, including “LIVE 1 specced” and “LIVE
1 advanced”, but its ledger contained only paused and conductor records. Some
successful model runs also exited zero without emitting a parseable summary.

**Effect:** the primary throughput view materially under-reports successful
work, so an operator cannot tell whether the system is idle, blocked, or doing
useful work. Capacity changes cannot be evaluated reliably.

**Fix:** make the runner append exactly one normalised, timestamped record to
runs.jsonl for every invocation, using the parsed summary when present and a
runner-owned “no summary” record otherwise. Treat the agent's own ledger write
as optional duplicate input, not as the only source of truth. Add a regression
test proving that every exit path creates one ledger record.

### CT-04 — Major — autonomous mode cannot drain the existing ready backlog

**Confidence: confirmed.**

The conductor only selects items carrying agent:triaged
(engine/conduct/cli.py:58-70), then marks enough of those as agent:auto to meet
CONDUCT_WIP. It will not enrol the 30 items already carrying agent:specced and
waiting for a build gate. At the same time, the app offers a project-wide
“Autonomous mode” toggle but no per-item or batch action to add or remove
agent:auto (apps/Cadence/Sources/CadenceCore/CadenceActions.swift:23-101 and
apps/Cadence/Sources/Cadence/PanelView.swift:614-637).

This is a deliberate safety boundary, not a licence for the system to make a
human's gate decision. It is nevertheless a product workflow gap: turning
autonomy on looks like it should increase throughput, while the existing
backlog remains entirely manual.

**Effect:** the real ready queue is stranded until a human clicks one gate at a
time. The default WIP of one and one issue advanced per pass further limit each
enabled project to a single item in flight.

**Fix:** add an explicit, auditable batch intake action such as “Queue selected
specced items for autonomous build”, with a confirmation that states the
allowed downstream behaviour and the WIP cap. It must only add agent:auto; it
must not grant agent:build itself. For existing queues, the human must choose
which reviewed specced items are eligible for this policy before any bulk
change is made.

### CT-05 — Major — the menu-bar app reports misleading project health

**Confidence: confirmed.**

The overall menu renders every unpaused project with a green circle
(apps/Cadence/Sources/Cadence/StatusItemController.swift:122-154), ignoring
the project's failed, waiting, or idle status. Separately, setStatus receives a
semantic symbol and colour but replaces it with the fixed Cadence SVG whenever
the normal menu-bar icon is used (lines 431-451); the colour is then deliberately
not applied. Thus the top-level status icon does not communicate the calculated
state.

**Effect:** a project with failures or a queue awaiting a human can look healthy
and a fleet with no productive capacity does not look blocked. This directly
undermines the operator's ability to notice and clear the bottlenecks above.

**Fix:** derive the per-project menu colour from the computed project status,
not merely paused/unpaused. Render the menu-bar state with an accessible
template/tint or status badge that preserves the Cadence mark while visibly
distinguishing failed, waiting, paused, active and idle. Add screenshot or
model tests for all five states.

### CT-06 — Major — timed-out runs can leave descendant processes and locks live

**Confidence: likely; the code path is unsafe, but no live orphan was observed
during this review.**

The scheduler uses subprocess.run with a timeout
(engine/schedule/cli.py:680-700). Python kills the direct child, not a newly
created process group. The child is a shell run-loop that starts a heartbeat and
an orchestrator/model subprocess. Killing only its parent can leave descendants
running; the heartbeat may keep refreshing the lock and prevent its two-hour
stale-lock recovery.

The app's ProcessRunner uses the same pattern: it terminates and then kills only
the Process PID on timeout (apps/Cadence/Sources/CadenceCore/CadenceClient.swift:41-71).
Cadence's internal run-orchestrator already has a safer process-group timeout
pattern, so the outer wrappers do not meet the same reliability standard.

**Effect:** a rare hang can become a long-lived invisible process, apparent
lock contention, and lost scheduler capacity.

**Fix:** start each scheduled and app-launched command in its own process group,
send TERM to the group at timeout, then KILL the group after a short grace
period, and wait/reap it. Record the process-group timeout in the run ledger.
Exercise this with an integration test that starts a child which itself starts a
sleeping grandchild.

### CT-07 — Moderate — fixed clock slots create bursts and idle gaps

**Confidence: confirmed as a design limit.**

All current profiles inherit the same default stage schedule. The scheduler only
considers a stage in its short clock window and admits at most one stage per
project per tick (engine/schedule/cli.py:751-789). A project with build-ready
work is therefore not scheduled because it is ready; it waits for the build
slot, then competes with every other project using that slot.

The system is batch-polling a state machine rather than pulling the highest
value ready work. Increasing capacity reduces the impact but does not remove
the burstiness or the cost of running stages which have no eligible work.

**Fix, near term:** stagger schedule offsets across projects once a global
capacity limit exists.

**Fix, strategic:** add a queue-aware dispatcher which selects eligible stage
work from state labels and age/priority, still respecting PAUSED, WIP,
project-level limits, user gates, and the build/revise lock. Clock schedules can
remain a bounded wake mechanism rather than the work-selection policy.

### CT-08 — Moderate — native app refresh work grows linearly and bursts network calls

**Confidence: likely; measured current costs are modest, but this will become
visible as the fleet and PR count grow.**

Every 120 seconds the app obtains the overview then starts an item refresh for
every project (apps/Cadence/Sources/Cadence/StatusItemController.swift:258-304).
That means one Cadence subprocess per project, a task-path lookup for every
file profile, and a worktree merged probe for every visible draft/revised item.
The latter can perform a git fetch. Refreshes are single-flight per project but
unbounded across the fleet, and each completed project refresh writes the cache
to disk.

Measured on the current machine, an overview took about 0.08 seconds, a local
file task list 0.07–0.10 seconds, and one Linear item list about 0.80 seconds.
This is not the present throughput root cause, but a ten-project refresh can
already create a burst of CLI, network and git work that competes with agents.

**Fix:** retain cached item data with an explicit freshness time; refresh
expanded, waiting, failed, or recently changed projects first; bound concurrent
subprocesses; and batch or defer worktree merged probes until the user opens the
relevant project. Save the cache once per refresh cycle, not once per project.

### CT-09 — Minor — routine heartbeat shutdown pollutes the scheduler error log

**Confidence: confirmed.**

Run-loop starts a background heartbeat (engine/scripts/run-loop.sh:129-137) and
the EXIT trap kills it without reaping it. The scheduler error log contains
hundreds of “Terminated: 15” lines from normal shutdown, alongside the real
under-capacity warnings.

**Effect:** noisy errors conceal useful signals and make the scheduler appear
less trustworthy. The unbounded current launchd error log also consumes disk
over time.

**Fix:** terminate and wait for the heartbeat quietly in the trap, retain a
real error if the wait fails, and rotate or cap launchd scheduler logs.

## Workflow diagnosis

The human-gated model intentionally prevents Cadence from autonomously granting
build, revise, review-ready, or merge authority. That safety rule is correct
and should not be weakened to increase activity numbers.

The current product experience, however, makes the intended human contribution
far more serial than necessary:

- Modern Print Works has 16 specced items awaiting a build decision.
- Knotbook has 10 specced items, one draft PR and six failed items needing
  attention.
- Portfolio has four specced items and two draft PRs.
- Other projects add three further needs-attention/needs-human items.

Those are 42 visible decisions or interventions, excluding held work. The
system has a substantial queue; it lacks an efficient, trustworthy way to
triage that queue into a bounded set of active lanes.

The app should make the next operator decision the centre of the interface:

1. fleet health first: active capacity, paused projects skipped, runs admitted,
   model runs in progress, failures, and waiting human decisions;
2. a cross-project “your move” queue grouped by action, not by project;
3. batch actions with previews: grant a selected gate, enqueue approved items
   for autonomy, hold, resume selected project, or inspect failure;
4. WIP counters visible beside each project and across the fleet; and
5. clear before/after metrics so raising a limit is a measured operating
   decision, not a blind toggle.

## Recommended recovery and implementation order

### 1. Recover useful capacity safely

Do not resume all eight paused projects at once. First decide which one or two
projects have work worth progressing now, clear their explicit blockers, and
resume only those. After CT-01 is fixed, set the scheduler's actual global
configuration to four admissions and width two for those projects. Keep the
per-project build/revise lock in place.

For autonomy, select a small, reviewed subset of triaged items for
agent:auto. Raising CONDUCT_WIP from one to two is a sensible first experiment
only after the fleet dashboard and ledger show reliable results. Do not bulk
enrol the existing specced backlog without a human policy decision.

### 2. Make capacity visible and trustworthy

Implement CT-01, CT-02 and CT-03 as one first slice. The resulting status
surface should show:

- active versus paused-skipped candidates;
- due, admitted, started, completed, failed and timed-out runs per tick;
- effective scheduler capacity and its configuration source;
- work completed from the runner-owned ledger; and
- per-stage queue age and count.

This slice answers whether more capacity is helping before more autonomy is
enabled.

### 3. Remove the human serial bottleneck without weakening authority

Implement CT-04 and CT-05 next. A fleet queue plus explicit batch enrolment
turns the existing 42 actions into a few deliberate, auditable decisions while
preserving the rule that no agent grants its own downstream gate.

### 4. Improve resilience and scale

Implement CT-06, CT-08 and CT-09 after the above. They reduce stuck capacity,
misleading status and background contention. Then evaluate the strategic
queue-aware dispatcher in CT-07 using real completion and queue-age data.

### 5. Do not remove this safety limit yet

Build and revise deliberately share one project worktree lock. That limits a
single project to one code-writing task at a time, but protects the repository
and is not the immediate fleet bottleneck. Parallel coding within one project
should be a later, separately designed change using per-task isolated
worktrees, safe branch naming, and serialised metadata updates. Raising global
concurrency alone should improve different projects running concurrently; it
must not be used to bypass the existing project lock.

## Verification plan for the first implementation slice

1. Unit-test that paused projects neither count as due nor consume a served
   marker or admission slot.
2. Unit-test a scheduler environment with four admissions and width two, and
   verify at most one selected stage per active project.
3. Unit-test normal summary, no-summary success, failure and timeout ledger
   records; confirm cadence throughput equals the activity-run count.
4. Run an isolated two-project staging profile for one day with WIP one, then
   compare queue age, completed stages, errors, lock holds, provider spend and
   operator interventions before raising WIP or enabling more projects.
5. Manually verify the menu-bar and panel states for failed, waiting, paused,
   active and idle projects.

## Review limitations

This was a production-state and source audit, not an implementation pass. No
destructive commands, model runs, task mutations, configuration changes,
launchd changes, or full test suite were run. The existing worktree was left
unchanged apart from this report.
