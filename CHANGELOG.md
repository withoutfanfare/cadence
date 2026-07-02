# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `cadence overview [--json]`: a cross-project status view — health, last run per
  stage, and recent activity for every registered project in one glance. Read-only.
- Multi-project menu bar: both SwiftBar plugins (`assets/swiftbar/`) now cover every
  registered project. The loop monitor aggregates health and gives per-project
  pause/run/logs actions (via `cadence overview --json`); the gate inbox lists each
  project's issues awaiting a move with config-scoped one-click grants. The inbox is
  **backend-aware** — file projects (`TASK_BACKEND=file`) are read via `tasks list`
  and also show an "Open tasks" backlog of ungated tasks so the whole `tasks.md` is
  visible; grants route through `tasks update` rather than `linear bulk-label`.
- `cadence doctor` now validates the configured **model**, not just the provider
  CLI — for `kimi` it checks the model exists in `~/.kimi-code/config.toml` (so a
  wrong name like `kimi:k2` is caught at setup rather than at the first run), and it
  prints the resolved `provider:model` for the others.
- Guided project setup: the `cadence-setup` skill lets any agent (Claude, Codex, or
  other) set up a project interactively — "set up this project with Cadence". It
  interviews the user for folders and choices, discovers Linear ids, picks the Linear
  or task-file backend, detects Grove/Clio, writes `cadence/.env`, and validates with
  `cadence doctor`.
- `cadence linear me` (the API key's own user, for `LINEAR_ASSIGNEE_ID`) and
  `cadence linear projects` (the configured team's projects, for `LINEAR_PROJECT_ID`),
  so setup no longer needs the Linear API explorer.
- `cadence schedule register [path]` adds a project to the scheduler registry
  (idempotent; defaults to the current directory), replacing the manual edit of
  `projects.txt`.
- Per-project state-dir guard: `cadence schedule status` and each scheduler tick now
  warn when two registered projects resolve to the same `CADENCE_STATE_DIR`, which would
  otherwise make them collide on the pause flag, logs, and scheduler run-markers (one
  project silently skipping the other's slot). Give each project its own state dir.
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
- `cadence inspect`, `cadence labels init|list|ensure`, and `cadence bakeoff`
  helper commands for setup support, label maintenance, and implementer comparison.

### Changed

- Failed runs are now alerted, not silent: a loop that exits non-zero or reports
  errors fires a macOS notification titled `Cadence <stage> — FAILED` (distinct
  "Basso" sound) and is recorded in the dated digest as well as the activity feed.
- `cadence restart` now reloads every installed `com.cadence.*.plist` (advance and
  conduct included), not just the four gated loops.
- `cadence conduct` now records decisions in the activity feed, dated digest,
  machine ledger, and `logs/conduct.log`; `cadence throughput` now includes
  `advance` and `conduct`.
- Loop skill prompts now use the configured `BASE_BRANCH` for worktrees,
  investigation, PR creation, and PR back-fill instead of hardcoding `develop`.
- Loop skill prompts keep Step 0 as a short defence-in-depth check and defer the
  detailed pause-recording mechanics to `docs/ARCHITECTURE.md`.
- Run summaries are now located on stdout via an explicit `CADENCE_SUMMARY ` marker
  (the old bare-JSON heuristic is kept as a fallback); the ledger line stays the bare
  object. A run that exits cleanly but emits no locatable summary is recorded as
  notable rather than passing silently as quiet.

### Fixed

- Run-summary marker is now authoritative: a `CADENCE_SUMMARY` line from a run's own
  stdout is accepted even when the summary has no `stage`/`loop` key (triage carries
  `mode`), so a clean triage run is no longer mislabelled "no summary". The triage
  summary now also includes `"stage":"triage"` so `cadence throughput` and `cadence
  overview` can attribute it.
- Linear adapter: transient failures (429, 5xx, network) retry up to three times with
  exponential backoff, honouring a numeric `Retry-After` (capped at 60s so a hostile
  value can't stall the slot), instead of failing the whole scheduled slot on one blip;
  issue pagination is capped at 100 pages as a safety stop.
- Build/revise worktree lock refreshes via a heartbeat while its holder is alive, so a
  legitimate build still running past the 2-hour mark is no longer reclaimed mid-flight;
  the rendered prompt file is now also removed on signal interruption.
- Autonomous advancer coerces its repair counts, so a missing or malformed count can no
  longer silently disable the repair cap; the escalation reason now shows the count.
- Skill frontmatter parsing tolerates CRLF and trailing spaces on the `---` delimiters,
  and warns instead of silently leaking the frontmatter when the closing delimiter is
  missing.
- Config loader warns (naming the key) when a quoted `.env` value is unterminated or
  contains a backslash-escaped quote it cannot mirror from bash.
- `cadence queue` warns when an issue carries conflicting `agent:*` state labels.
- Memory adapter tolerates CRLF-authored rule files and normalises a multi-line title so
  it cannot corrupt the `description` frontmatter it writes.
- Advance idle probe fetches a single issue rather than full issue nodes.

- Local task file: a body line starting `status:` or `labels:` (e.g. `status: 200`
  in a spec) is kept as body text instead of being silently absorbed into the
  task's metadata on the next read.
- Scheduler: a non-numeric `CADENCE_SCHEDULER_MAX_RUNS` or
  `CADENCE_SCHEDULER_WINDOW_MINUTES` now degrades to the default instead of
  crashing every tick; two stages due in the same window each run rather than the
  first starving the rest; and `KEY = value` (space before `=`) is ignored, matching
  bash, so the scheduler's view can't diverge from the loaded config.
- `cadence conduct` now records a FAILED entry in the ledger when a Linear/tasks
  adapter fails, so a scheduled feeder run no longer stops without a trace.
- Config loading tolerates CRLF (`.env` and profile files) and expands a leading
  `~/` in `--config`/profile paths; a stray `CADENCE_HOME=` line can no longer
  repoint the install, and triage/spec-only configs without `PROJECT_DIR` no longer
  crash under `set -u`.
- Build/revise worktree lock reclaims by age (survives macOS PID reuse) and reclaims
  stale locks atomically so two racers can't both acquire it; a timed-out run with no
  summary no longer reports the previous run's counts.
- Registered projects that share a `CADENCE_STATE_DIR` are flagged by
  `cadence schedule status` and each tick.
- Linear adapter: a non-JSON API response surfaces as a clean error, not a traceback.

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
- `cadence autonomous on` now renders advance/conduct launchd plists atomically
  instead of writing directly to the active paths.
- `cadence linear bulk-label --where-label` now uses the paginated issue-list
  path instead of calling the paginated GraphQL query without required variables.
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
