# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Autonomous mode (Layer 1 — the advancer): the `advance` loop, the `agent:auto`
  opt-in label, `cadence run advance [--dry-run]`, and the `AUTONOMOUS`,
  `AUTO_MAX_ISSUES_PER_RUN`, `AUTO_MAX_REPAIRS`, and `MODEL_ADVANCE` settings. On
  `agent:auto` issues it grants the next gate (spec → build → draft PR) without a
  human, but still stops at a draft PR. Off by default.
- The conductor (Layer 2): a deterministic, WIP-limited feeder — `cadence conduct
  [--dry-run]` and the `CONDUCT_WIP` cap. It ranks the ready backlog (priority →
  current cycle → oldest), skips blocked issues, and tops up `agent:auto` to the
  WIP cap.
- Config-driven schedule: `cadence schedule [show|apply]` and per-loop `SCHED_*`
  settings (`SCHED_TRIAGE` … `SCHED_CONDUCT`). Set an hourly minute (`:15`) or an
  N-hourly cadence (`4h`, `4h@30`) in `.env` and `cadence schedule apply` regenerates
  and reloads the launchd jobs. Every cadence is clock-aligned to midnight, so firing
  times are predictable and loops stay staggered; defaults reproduce the previous
  hourly schedule. Replaces the hand-edited launchd templates.
- `cadence autonomous on|off|status` — one-step switch that writes `AUTONOMOUS` to
  `.env` and loads/unloads the advance + conduct launchd jobs. The four gated loops
  are never touched.
- `cadence queue [-v]` — board overview grouped by agent state (grant spec, grant
  build, review PR, needs-you, failed) with in-flight and parked counts.
- `cadence throughput [days]` — per-stage rollup of recent runs from the machine
  ledger, including errors.
- `cadence linear bulk-label` — batch label add/remove across issues, scope-checked,
  with `--where-label`, `--dry-run`, and `-y`. See `docs/BULK-LABEL.md`.

### Changed

- Failed runs are now alerted, not silent: a loop that exits non-zero or reports
  errors fires a macOS notification titled `Cadence <stage> — FAILED` (distinct
  "Basso" sound) and is recorded in the dated digest as well as the activity feed.
- `cadence restart` now reloads every installed `com.cadence.*.plist` (advance and
  conduct included), not just the four gated loops.
- Loop skill prompts now use the configured `BASE_BRANCH` for worktrees,
  investigation, PR creation, and PR back-fill instead of hardcoding `develop`.
- Loop skill prompts keep Step 0 as a short defence-in-depth check and defer the
  detailed pause-recording mechanics to `docs/ARCHITECTURE.md`.

### Added (engine extraction)

- `WORKTREE_TOOL` config (`git` default, `grove` opt-in) and a `cadence worktree
  add|remove|path` helper. Build/revise create isolated worktrees with plain
  `git worktree` out of the box — grove is no longer required — while grove + Laravel
  Herd remains available by setting `WORKTREE_TOOL=grove`. `cadence doctor` checks
  grove is present only when selected.

- Public engine restructure: engine code, scripts, and skills extracted from a
  single-project dogfood into a generic, profile-driven engine.
- `engine/` — loop runner (`run-loop.sh`), implementer dispatcher
  (`run-implementer.sh`), health check (`doctor.sh`), and supporting scripts.
- `skills/` — four portable loop skills (triage, spec, build, revise) with no
  project-specific identifiers; profile facts injected at runtime from `.env`.
- macOS launchd scheduling (now config-driven via `cadence schedule`; see above).
- `docs/ARCHITECTURE.md` — control model, state machine, gate semantics,
  engine-vs-profile separation, runtime state layout, PAUSED guard, and the
  dated-file log + memory-recall conventions (§7, §7a).
- `docs/LABELS.md` — full `agent:*` label vocabulary with set/clear/gate columns.
- `docs/IMPLEMENTERS.md` — implementer dispatch contract, brief/worktree rules,
  gate + repair-turn flow, `BUILD_IMPLEMENTER` configuration.
- `MIT LICENSE`.
- `.env.example` — reference configuration file.
- Private history moved to `private/` (gitignored); committed tree contains no
  project-specific identifiers.

### Fixed

- Linear issue listing now paginates beyond the first 100 issues and includes
  `createdAt`, so queue/conductor ordering can honour the promised oldest-first
  tie-breaker.
- An `advance` run with autonomous mode enabled but no `agent:auto` issues now
  records a quiet idle result instead of a pause.
- `cadence schedule apply` now renders launchd plists to a temporary file and
  moves them into place only after a successful non-empty render.
- The triage loop prompt now separates normal metadata writes, full-mode PR
  back-fill issue creation, and failure-only comments.
- `cadence worktree add` now refuses to reuse a stale plain directory that is not
  a git worktree, and all worktree verbs consistently reject unknown
  `WORKTREE_TOOL` values.
- Runner pre-launch safety now records manual and wrong-workspace pauses in the
  stage log, activity feed, dated digest, and `runs.jsonl` before invoking Claude.
- Linear adapter issue/document operations now fail closed when required scope
  values are missing, when an issue is outside the configured assignee, or when a
  document ID is not linked to the supplied issue.
