# SwiftBar task parity — file and Linear backends

**Date:** 2026-07-02
**Status:** Approved design, ready for planning

## Goal

Make the SwiftBar menu treat a **file-backed** board (`TASK_BACKEND=file`) as a
first-class citizen, on par with a Linear board: every task is clickable, its
stage is controllable from the menu (advance, set any stage, hold/release), and
its current position in the pipeline is unambiguous. The two backends should feel
the same to operate.

## Non-goals

- **No change to the four loops** (triage/spec/build/revise) or their label
  transitions. The state machine is proven and stays as-is.
- **No change to the `tasks.md` format.** Terminology is already shared —
  `docs/LABELS.md` states the same `agent:*` vocabulary applies to both backends.
- **No new dependencies.** Engine stays stdlib-only.

## Background: the label model (why we present rather than rewrite)

Two kinds of label do two different jobs:

- **Gate labels** — `agent:spec`, `agent:build`, `agent:revise`. The human's
  "go" button. At most one at a time: the human adds it, the loop removes it when
  it starts work.
- **Status/breadcrumb labels** — `agent:triaged`, `agent:specced`,
  `agent:pr-open`, `agent:revised`. Dropped by the loops as they progress. These
  **accumulate**: a task with a PR open still carries `agent:triaged` and
  `agent:specced` underneath.

The accumulation is load-bearing: the triage loop skips a task *because* the
`agent:triaged` breadcrumb persists (`skills/cadence-loop-triage/SKILL.md`).
Stripping breadcrumbs to force "one label at a time" would make triage re-grab
moved tasks. Decision: **keep the labels; present a single canonical stage.**

Today's inbox plugin buckets a task by *every* label it matches, so a
`pr-open` task also appears under "Specced" and "Triaged". That double-listing is
the bug this design removes.

## Design

### 1. `stage_of(labels)` — one canonical stage per task

A small, pure, tested helper in the engine. Given a task's labels it returns the
task's single current stage using **furthest-wins** precedence, plus orthogonal
flags:

- **Stage (furthest breadcrumb):** `revised` > `pr-open` > `specced` >
  `triaged` > `backlog` (no breadcrumb, open).
- **Exceptions that take a task out of the normal flow** (reported as the stage
  when present): `needs-attention` (`agent:needs-attention`), `needs-human`
  (`agent:needs-human`), `superseded` (`agent:superseded`).
- **Pending gate:** whichever of `agent:spec` / `agent:build` / `agent:revise`
  is set (at most one), reported alongside the stage (e.g. stage `specced`,
  gate `build` → "Build queued").
- **Hold:** `agent:hold` present → reported as a flag (orthogonal to stage).

The helper is surfaced as a `stage` object on each item returned by **both**
`cadence tasks list` and `cadence linear issues-list`, so the menu reads one
canonical stage instead of re-deriving it. Shape (illustrative):

```json
{ "stage": "specced", "gate": "build", "hold": false, "exception": null }
```

Location: a shared engine module importable by both `engine/tasks/cli.py` and
`engine/linear/cli.py` (exact module decided in planning). It encodes only the
generic `agent:*` vocabulary (already in `docs/LABELS.md`), no project facts.

### 2. `cadence tasks path`

A new verb on the tasks adapter that prints the resolved absolute `TASK_FILE`
path (honouring `TASK_FILE` / `PROJECT_DIR` the same way `task_path()` already
does). Used by the menu's "Open tasks.md" action.

### 3. Generalised click-wrapper

`assets/cadence-grant.sh` today grants exactly one label. Generalise it to apply
an **add/remove label set** to the correct backend, keeping its two hard-won
properties: the explicit `PATH` (so SwiftBar's stripped environment still finds a
python3 with CA certs) and the per-click log line (so a silent failure is
impossible).

- Invocation carries: backend (`file` | `linear`), config path, identifier, and
  repeated `--add L` / `--remove L`.
- File backend → `cadence [--config C] tasks update <ID> --add-label… --remove-label…`
- Linear backend → `cadence [--config C] linear issue-update <ID> --add-label… --remove-label…`
  (both CLIs already accept repeated `--add-label` / `--remove-label`).

The plugin computes the label deltas; the wrapper just applies them. This one
path serves Advance, Set stage, and Hold/Release on both backends.

### 4. Inbox plugin rework (`assets/swiftbar/cadence-inbox.5m.py`)

For **both** backends, group tasks by their canonical `stage` (one task, one
section — the double-listing is gone) and give every task the same submenu:

```bash
TASK-3  Fix the login redirect
   ▶ Advance to <next stage>          # grants the next gate for the current stage
   ───────────
   Set stage ▸ Triage / Spec / Build / Revise
   ───────────
   Hold   (↔ Release hold)            # toggles agent:hold
   ───────────
   Open tasks.md   (file)   ·   Open in Linear   (Linear)
```

Action semantics — **menu writes only gate + hold labels, never breadcrumbs:**

- **Advance** — add the next gate for the current stage
  (`triaged`/backlog → `agent:spec`; `specced` → `agent:build`;
  `pr-open`/`revised` → `agent:revise`), and clear the other two gate labels so
  only one "go" is ever pending.
- **Set stage → Spec/Build/Revise** — add that gate, clear the other two gates.
  (Lets the human move a task backwards, e.g. pr-open → Spec, without touching
  breadcrumbs.)
- **Set stage → Triage** — the one breadcrumb write: remove `agent:triaged`
  (and any pending gate) to force a clean re-triage, exactly as `docs/LABELS.md`
  sanctions ("Human (to force re-triage)").
- **Hold / Release** — toggle `agent:hold`.
- **Open** — file: `open "$(cadence [--config C] tasks path)"`; Linear: existing
  `href` to the issue URL.

Backlog (ungated, open) tasks get the identical submenu — they are no longer
inert grey text.

The badge keeps its current meaning (time-sensitive set: PRs + escalations).

## What changes

| Area | Change |
|---|---|
| `engine/<shared>/…` | New `stage_of(labels)` helper (+ unit test) |
| `engine/tasks/cli.py` | `stage` field on `list`; new `path` verb |
| `engine/linear/cli.py` | `stage` field on `issues-list` |
| `assets/cadence-grant.sh` | Generalise to add/remove label sets, both backends |
| `assets/swiftbar/cadence-inbox.5m.py` | Group by canonical stage; per-task submenu; backlog first-class |
| `docs/OPERATING.md` | Document the menu controls |
| `docs/TASKS.md` | Document `cadence tasks path` |
| `CHANGELOG.md` | Entry |

## Testing

- `stage_of` — unit test covering furthest-wins precedence, exceptions, pending
  gate, hold, and backlog (no labels). This is the non-trivial logic.
- `cadence tasks path` — covered by existing tasks-cli test patterns (resolved
  path with/without `TASK_FILE`/`PROJECT_DIR`).
- `stage` field present and correct on `tasks list` output (extend
  `test_tasks_cli.py`).
- Wrapper and plugin are SwiftBar assets (not in the unittest suite); verify by
  hand against a file project and a Linear project.

## Invariants preserved

- Gate labels remain human-set; the menu click **is** the human. Loops still own
  the breadcrumb writes.
- No loop grants a downstream gate, marks a PR ready, or merges.
- Fill-blanks-only and the PAUSED/backend guards are untouched.
- Engine stays profile-free and stdlib-only; the stage vocabulary is generic.
