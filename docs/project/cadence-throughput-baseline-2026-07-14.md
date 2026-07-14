# Cadence throughput baseline — 14 July 2026

Phase 0 "before" snapshot for the throughput-recovery plan
(docs/superpowers/plans/2026-07-14-cadence-throughput-recovery.md).
Captured 2026-07-14T11:14:19Z. Operational counts only. The Phase 5
comparison reads this file against the same measures seven days after the
trial starts.

## Selected trial pair

Scanway and Portfolio (the two currently active projects; both file backend,
both autonomous-enabled).

## Fleet

| Measure | Value |
| --- | --- |
| Registered projects | 10 |
| Paused | 8 |
| Active | 2 (Scanway, Portfolio) |
| Effective scheduler capacity | max runs/tick 1, concurrency 4 |
| Scheduler launchd job | loaded, last exit 0 |
| Under-capacity warnings (live err log) | 257 |
| “Terminated: 15” heartbeat noise lines (live err log) | 221 |

The last observed tick spent its single admission launching a paused clio
spec run (“PAUSED present”) — CT-01 live at capture time.

## Seven-day ledger (runs.jsonl, per selected project)

Ledger records under-count real work: successful runs write no record
(CT-03), so these are almost entirely pause/no-op records.

| Measure | Scanway | Portfolio |
| --- | --- | --- |
| Records (7 days) | 126 | 16 |
| Paused (reason: manual) | 125 | 12 |
| Paused (reason: autonomous-off) | 1 | 0 |
| Lock-held | 0 | 1 |
| Errors / crashed | 0 | 0 |
| Latest record | 2026-07-14T00:56:59Z | 2026-07-14T06:22:55Z |

Throughput report, same window (runs = ledger lines, so mostly pause
records): Scanway triage 2, spec 6, build 5, revise 98, advance 13, conduct 2
— nothing recorded as produced. Portfolio spec 3, revise 9, advance 1,
conduct 3 — conduct produced “2 tagged”. Both ledgers go quiet after the
projects were resumed today: post-resume successful runs leave no record,
which is exactly what Phase 2 fixes.

## Queues (awaiting a human, at capture)

| Measure | Scanway | Portfolio |
| --- | --- | --- |
| Grant build (agent:specced) | 0 | 3 |
| Review PR (agent:pr-open) | 1 | 0 |
| Needs attention | 1 | 0 |
| On hold (parked) | 0 | 4 |
| In flight (agent:claimed) | 0 | 0 |
| Draft PRs open | 1 | 0 |

## Not measurable at baseline

- **Productive admissions / successful runs** — the ledger misses successful
  work until Phase 2 lands; activity.log holds the only human-readable trace.
- **Oldest queue age** — the file backend does not expose item ages in
  `queue -v`.
- **Provider cost per completed item** — not recorded anywhere yet.

These three become measurable (or get a recording home) as the plan lands;
the Phase 5 comparison should note where a “before” value was unavailable.

## Anomalies found at capture

1. **The scheduler plist's log paths point into Portfolio's project state
   directory** (`~/.cadence/projects/portfolio/logs/scheduler.launchd.*`) —
   a previous `schedule apply` baked a project profile's CADENCE_STATE_DIR
   into the global plist. This is the exact hazard Task 2's replaced guard
   prevents; re-applying after Task 2 (with scheduler.env present) moves the
   logs to the global state dir.
2. **A stale scheduler log copy sits at `~/.cadence/logs/scheduler.launchd.*`**
   (last written 8 July, 538 accumulated warnings) from an earlier plist
   generation — ignore it; the live log is the Portfolio-dir one.

## Stop conditions for the first trial

Pause the trial on any of:

- two process-group timeouts;
- one unexpected worktree-lock overlap;
- three consecutive build/revise failures sharing one root cause;
- provider spend above the agreed daily ceiling.
