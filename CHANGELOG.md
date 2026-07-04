# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- SwiftBar menu status icons are now an SF Symbol traffic light instead of
  emoji. Red is reserved for a genuinely failed run; "your move" (a decision
  waiting on you) is amber — attention, not alarm — so a board full of pending
  work no longer reads as a board full of errors. Green is running, grey is
  dormant (paused/idle), and every state has a distinct shape as well as colour
  for a clear glance and colour-blind legibility.

- The single-position label invariant is now **engine-enforced on every write**,
  not reconstructed by prose in each skill. `agent:specced`, `agent:pr-open` and
  `agent:revised` are mutually exclusive; a shared `resolve_labels` (used by
  `linear issue-update`, `bulk-label`, and `tasks update`) drops the superseded
  label whenever a new position is added, and self-heals stray residue on any
  write. A forgotten `--remove-label` — by a loop or a human on the CLI — can no
  longer strand an issue on two lifecycle labels (the corruption that accumulated
  silently until the queue's conflict check surfaced it). Documented in `LABELS.md`.

- Completing an issue now **clears its `agent:*` workflow labels automatically**.
  A done/cancelled issue holds no live gate, status, or flag, so `tasks update
  --status completed` and `linear issue-update` to a completed/cancelled state
  strip every `agent:*` label (user labels like `Bug` are kept) — enforced in the
  adapters, not left to a manual sweep. Any write to an already-done issue
  self-heals leftover labels, so completed tasks stop appearing as phantom work.

- Build **always titles its PR `<ID> — <title>`** (the task identifier and its
  title) instead of letting `gh` infer the title from the commit, so every PR is
  trackable from the GitHub PR list and links back to the task. Applies to both
  the Linear skill and the file-backend build prompt.

### Added

- One-command project onboarding and offboarding. `cadence onboard [path]` does
  everything that was manual — auto-fills a blank per-project `CADENCE_STATE_DIR`
  (refusing a dir another registered project already uses), sets `CADENCE_SCHEDULED=1`,
  registers the project, loads the launchd scheduler, and runs doctor — leaving
  newly registered projects **paused** so a human resumes deliberately. `cadence offboard [path]`
  reverses it (pause, `CADENCE_SCHEDULED=0`, unregister) and unloads the scheduler
  job once the registry empties; `--purge` also deletes the project's own state
  dir, never the config or the shared default. New `cadence schedule unregister`
  primitive mirrors `register`, and a `cadence-offboard` skill drives the
  conversational path. Documented in `INSTALL.md`, `OPERATING.md`, and the
  cheatsheet.

- Parallel scheduler dispatch with a per-run timeout. A tick now launches its
  admitted runs through a bounded pool: `CADENCE_SCHEDULER_MAX_RUNS` remains the
  per-tick throughput ceiling, new `CADENCE_SCHEDULER_CONCURRENCY` (default `4`)
  is how many run at once, and new `CADENCE_SCHEDULER_RUN_TIMEOUT` (default
  `3600`, `0` disables) kills any single run that overstays and reports it as a
  failure without disturbing the other runs in the same tick. Defaults preserve
  the old serial behaviour (`MAX_RUNS=1`). Documented in `CONFIGURATION.md`.

- `ORCH_TIMEOUT` (default `2700` = 45m): a hard cap on any single orchestrator
  run, applied to **every existing and new project by default** (was a hard-coded
  3600s). Bounds a hung or wedged run — e.g. a model idling in a self-monitoring
  loop instead of building — so it cannot hold the shared build/revise worktree
  lock for an hour. Override per profile for unusually slow build+gate cycles.
  Documented in `CONFIGURATION.md` alongside `CADENCE_LOCK_MAX_AGE_SECONDS`.

- Merged-PR reconciliation: once a human merges a task's draft PR into
  `BASE_BRANCH`, the task/issue is closed and `agent:pr-open` cleared — two ways.
  A **"✓ Mark merged"** button appears on PR-open items in the SwiftBar menu, and
  **triage's PR back-fill** now also closes any tracked `agent:pr-open` item whose
  recorded PR has merged (previously it only created issues for *unlinked* merged
  PRs). This is a narrow, documented relaxation of the "no loop moves an issue past
  In Review" invariant: it records a merge a human already made, never advancing
  unmerged work. Linear closes to a completed-*type* state via the new
  `cadence linear issue-update --state-type` (no state name hard-coded in the
  engine); file tasks close to `status: completed`.

- `cadence queue --why`: failed (`agent:needs-attention`) issues grouped by root
  cause, each with a one-line fix. A systemic problem parks many issues with the
  same failure (a broken worktree killed 8; an engine gap killed 4) but they
  surface as N separate red items. This reads each issue's reason (a file task's
  run note, or a Linear issue's last comment), classifies it, and groups
  largest-cause-first — turning "17 items to triage" into "3 things to fix once".
  Documented in the cheatsheet.

- `cadence linear doc-get <id>` plus a `documents` list on `issue-get`, so the
  advance loop can fetch a linked spec document and verify its acceptance criteria
  at the specced gate. Previously the adapter could only *write* documents
  (`doc-upsert`), so the autonomous advancer could not confirm a spec and parked
  the issue as `agent:needs-attention`. `doc-get` is scope-checked to the
  configured team.

- `WORKTREE_REPO` overrides the grove repo name when the checkout directory
  differs from the bare repo (e.g. a `stuntrocketv3` worktree off the
  `stuntrocket` grove repo). Previously the grove repo name was hard-derived from
  `PROJECT_DIR`'s basename, so such a project's every build failed at worktree
  creation. `cadence doctor` now probes `grove ls <repo>` and fails at setup if
  the repo does not resolve, instead of letting it fail silently on every build.
  Documented in `CONFIGURATION.md`.

- `cadence doctor` warns when a verification gate looks repo-wide (a full test
  suite, or a linter/analyser over the whole tree). Such a gate fails on
  pre-existing debt unrelated to a change and blocks every build from opening a
  PR. `CONFIGURATION.md` documents the change-scope rule with per-ecosystem
  scoped examples and the baseline fallback.

### Fixed

- Prompt rendering crashed under Python < 3.10. `render.py` used `str | None`
  union hints evaluated at definition time, so the module raised `TypeError` on
  import under Python 3.9 — breaking file-backend prompt rendering (and every
  test that shells into it) on older interpreters. A `from __future__ import
  annotations` keeps the hints lazy so they never evaluate at runtime.

- A timed-out orchestrator run no longer orphans the provider's children.
  `run-orchestrator.sh` now launches the provider in its own session and kills
  the whole process group on timeout (SIGTERM, then SIGKILL after a grace
  period) — previously only the direct provider process was killed, leaving gate
  children (cargo/pnpm/git) mutating the worktree after `run-loop.sh` released
  the lock and started the next run.

- `cadence offboard --purge` now refuses to delete a `CADENCE_STATE_DIR` that is
  the shared default state root or is still used by another registered project,
  and no longer swallows delete failures — guarding against a misconfigured
  config wiping `~/.cadence` or another project's state.

- The folded reviewer ran with **no tools**. `run-reviewer.sh` invokes the
  orchestrator with stage `review`, which has no loop skill, so the allowed-tools
  lookup hit a missing file and returned an empty list — the reviewer then could
  not inspect the diff and never confirmed `review_clean`, parking the issue. It
  now falls back to a read-only toolset (`Bash,Read,Grep,Glob`) when a stage has
  no skill.

- Two label transitions leaked a superseded label: `grant-build` left
  `agent:specced` and `revise` left `agent:pr-open`, stranding issues on two
  lifecycle labels. Both skills now drop the old label — and the engine-level
  invariant above makes the whole class impossible regardless.

- `cadence queue` flagged healthy issues as "inconsistent labels". The check
  counted the deliberately-sticky `agent:triaged` as a conflict, so nearly every
  advanced issue tripped it, burying real crash residue in noise. It now flags
  only two-or-more mutually-exclusive position labels.

- `cadence overview` reported projects as "paused" after the pause was lifted. A
  paused run is a skipped tick, not a stage result; it no longer masks a stage's
  real last outcome (current pause is shown by the `PAUSED` flag).

- SwiftBar "Mark merged" (and "Release hold") silently did nothing. SwiftBar
  drops a menu param whose value is empty, shifting every later positional arg
  one slot left — and these are the only actions that send an empty "labels to
  add" slot. So a merge click re-added `agent:pr-open` and dropped the status
  change instead of closing the task, all with a success exit code. The plugin
  now sends `-` for any empty value and `cadence-grant.sh` maps it back to empty.

- Multi-project scheduler fairness: the tick served registered projects in
  registry order and stopped after `max_runs`, so several projects sharing the
  same `SCHED_*` offsets would starve the ones behind them — a later project with
  identical offsets could get **zero** runs indefinitely while earlier ones ran
  dozens of times. The tick now orders due projects **least-recently-served
  first**, warns when more projects are due than `max_runs` can serve in one tick,
  and `cadence schedule status` shows each project's last-run age with a starved
  flag.

- Human gate labels are now protected in the engine, not just in prompt text. A
  scheduled loop could remove a human-granted `agent:spec` / `agent:build` /
  `agent:revise` (a triage run did exactly this, reverting granted work to
  `agent:triaged`). `cadence tasks update` and `cadence linear
  issue-update`/`bulk-label` now refuse to remove a gate label unless the caller
  is a human (no `CADENCE_STAGE`) or the stage that owns the gate; `run-loop.sh`
  exports `CADENCE_STAGE` for every run.

- Build loop: interrupted work is now resumed instead of skipped. The skip rule
  treated "branch has commits ahead of `BASE_BRANCH`" as in-progress work but
  compared against a stale origin ref, so base history looked like branch work
  and an issue with stranded, unpushed implementation was re-skipped every run
  with no PR. The loop now fetches the base before comparing, and leftover work
  with no open PR is carried through gates → commit → push → draft PR.
  `lib-env.sh` also exports `WORKTREE_BASE` so external tooling (e.g. user git
  hooks) can recognise the loop's own worktrees.

- `tests/test_providers_cli.py` was not hermetic: it spawned the providers CLI
  with the repo root as its working directory, so the `<cwd>/cadence/.env`
  fallback read — and the `set` test rewrote — the repo's live config instead
  of the test fixture. The subprocess now runs from a temp directory with any
  inherited `CADENCE_CONFIG` dropped.

- SwiftBar menu: file tasks with `status: completed` were treated as still-open
  and leaked into the actionable list; `completed` now counts as closed.

- `cadence overview [--json]`: a cross-project status view — health, last run per
  stage, and recent activity for every registered project in one glance. Read-only.
- Multi-project menu bar: a single SwiftBar plugin (`assets/swiftbar/cadence.2m.py`)
  covers every registered project in one menu. The menu-bar glyph answers "do I need
  to do anything?" first (⚠️ a run failed → 📥 *N* awaiting your move → ⏸ paused →
  calm tick). Each project shows an honest one-line status — a glyph, plain-English
  state, and a **relative** timestamp ("2h ago", not raw UTC) — with the tasks
  awaiting your move underneath (config-scoped one-click grants) and the technical
  detail (per-stage results, autonomous line, pause/run/logs) tucked into a
  **Stages & controls** submenu. Backend-aware: file projects (`TASK_BACKEND=file`)
  are read via `tasks list` and also show an "Open · backlog" of ungated tasks so the
  whole `tasks.md` is visible; grants route through `tasks update`. Backed by
  `cadence overview --json`. (Replaces the earlier split loop-monitor / gate-inbox
  pair.)
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
- SwiftBar gate inbox now gives every task — file-backed and Linear — a single
  canonical stage and a per-task submenu to advance, set any stage, hold/release,
  and open it. New `cadence tasks path` verb; the `stage` field is emitted by
  `cadence tasks list` and `cadence linear issues-list`.
- An optional fifth loop, `roadmap`: an advisory scout — `cadence run roadmap
  [--dry-run]` and the `SCHED_ROADMAP`, `ROADMAP_MAX_OPEN`, and `GOAL_FILE`
  settings. It scans the codebase read-only and files proposal issues carrying
  `agent:proposed`, capped at `ROADMAP_MAX_OPEN` open at once by the create
  verbs, not just the prompt. It is opt-in per project via `SCHED_ROADMAP`
  (default `off`) — enabling the schedule turns it on, not a stated goal. A
  goal (the Linear project description, or `GOAL_FILE` on the file backend)
  *steers* what it looks for; with none it works against a standing
  engineering-quality rubric (real bugs, performance, accessibility, security,
  dead code, consistency). It never grants a gate, and the conductor fences
  `agent:proposed` out of the autonomous queue until a human accepts it.
  Dismissal has two flavours: cancel for good, or cancel and add `agent:later`
  for "not now", which allows re-proposal after a 30-day cool-off.

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

- File-backend build and revise loops now carry the full worktree/draft-PR
  contract. The rendered file prompts told build only to "implement inside the
  configured project/worktree" and flip `agent:build` to `agent:pr-open`, so
  orchestrators edited the main checkout directly and labelled tasks as having
  a PR that never existed (the advance loop then escalated
  `agent:needs-attention` on phantom PRs). Build now creates an isolated
  worktree off the base branch, runs gates there, opens a draft PR, and records
  the PR URL in the task body before setting `agent:pr-open`; revise pushes to
  the task's existing PR branch only.
- `cadence tasks validate` (and therefore `cadence doctor`) flags a task
  labelled `agent:pr-open` whose body has no PR URL — the tell that no draft PR
  actually exists and the workflow state needs repair.
- Autonomous queue no longer freezes on one stuck issue. The conductor counted
  every `agent:auto` issue against `CONDUCT_WIP`, including ones parked in
  `agent:needs-attention`/`agent:hold`/terminal states — so a single failed
  issue could hold the only WIP slot indefinitely, reporting "queue full" every
  run while nothing progressed. A parked issue now releases its slot (active and
  `agent:pr-open` issues still count, capping concurrent draft PRs).
- Loop-runner crashes are no longer silent. Any non-zero exit that happens
  before a run's normal logging (a script error, an early failure after the
  pause/backend guards) now appends a `CRASHED (exit N)` line to both the stage
  log and the activity feed, so a dead pipeline shows up in `cadence
  status`/`cadence feed` instead of only in launchd stderr.
- `run-loop.sh` no longer crashes on macOS's `/bin/bash` 3.2 when a stage has no
  extra prompt arguments: expanding the empty `CMD_ARGS` array under `set -u` was a
  fatal "unbound variable" error, so every scheduled spec/revise/live-advance run
  with real work exited 1 before rendering the prompt — silently, with the failure
  visible only in the scheduler's launchd stderr. The expansion now uses the
  bash-3.2-safe `${arr[@]+"${arr[@]}"}` idiom. (`--dry-run` runs passed the arg and
  masked the bug.)
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
