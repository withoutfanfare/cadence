# Roadmapper mode — design

**Date:** 2026-07-02 · **Status:** approved design, pre-implementation

## Purpose

An optional fifth loop, **roadmap**, that acts as an *advisory scout*: a
high-reasoning model periodically scans the project against a human-stated goal
and files proposed work — bugs and features — as marked backlog issues. The
human reviews, accepts, or dismisses each proposal. It never feeds work into
the pipeline automatically.

## How it switches on

No enable flag. A project opts in by **stating a goal**:

- **Linear backend** — the Linear project description.
- **File backend** — `cadence/goal.md` next to the project's config.

Goal absent or empty → the run idles (exit 0, logged as idle), files nothing.

## The loop, per run

1. **Step 0** — PAUSED flag and backend guard, identical to every other loop.
2. **Read the goal** (per backend, above). Empty → idle.
3. **Scan read-only** — the codebase and recent git history, hunting for gaps
   that matter to the stated goal.
4. **List the board's memory** — every existing issue *and* every past
   `agent:proposed` issue (open, done, cancelled). Mandatory step; overlap
   judgement is the model's job, listing is not optional.
5. **File proposals** — real backlog issues carrying `agent:proposed`, topping
   the board up to at most `ROADMAP_MAX_OPEN` open proposals. Few and strong
   over many and thin; an honest "nothing worth proposing" run files nothing —
   never filler to hit the cap.

Each proposal contains: type (bug or feature), a plain-English description of
the problem or opportunity, where in the code it lives, a one-line
"Goal fit: …" trace to the goal, and an acceptance-criteria stub (the same stub
triage adds, so a later `agent:auto` does not stall at the criteria check).

Downstream, existing machinery takes over: triage fills blanks on proposals
like any other issue; the human decides each proposal's fate.

## Dismissal — two flavours

- **Dismiss for good** — cancel the issue (plain, low-effort gesture; file
  backend: `status: dismissed`). Never re-proposed.
- **Not now** — cancel **and** add `agent:later`. May be re-proposed after a
  30-day cool-off from the cancellation date (matching the Stale threshold) if
  it still serves the goal.

The dedupe step (4) is what enforces both: dismissed-for-good ideas are fenced
forever; `agent:later` ideas are fenced for 30 days.

## Safety — invariants unchanged

- The roadmapper **never grants a gate**, never sets `agent:spec`/`build`/
  `revise`, never touches PRs or code.
- **Conductor fence** — `agent:proposed` joins the conductor's skip-list
  (`_BLOCK_OUT` in `engine/conduct/cli.py`), so autonomous mode never sweeps an
  unreviewed proposal into `agent:auto`. A model-invented idea cannot reach
  code without a human blessing it first (gate it, or remove `agent:proposed`).
- Read-only on the codebase; board writes only through `cadence linear …` /
  `cadence tasks …`; skips anything carrying `agent:hold`.
- The **cap is engine-enforced**, not prompt-promised: the create verbs refuse
  to exceed `ROADMAP_MAX_OPEN` and only ever create with `agent:proposed`
  attached.

## Engine additions

| Piece | Change |
|---|---|
| `cadence linear issue-create` | New verb: backlog issue in the configured team/project/assignee, title + description + labels. Adapter pattern (`cmd_x(args, env, post=graphql)`), fake-`post` testable. Enforces cap + marker label. |
| `cadence tasks add` | New verb: appends a task to `tasks.md` in the documented format (`status: open`, labels line). Enforces cap + marker label. |
| Conductor | `agent:proposed` added to `_BLOCK_OUT`. |
| Labels | `agent:proposed`, `agent:later` in `labels init` and `LABELS.md`. |
| Config | `ORCHESTRATOR_ROADMAP` (default `claude:opus` — judgement-heavy stage, elected per project), `ROADMAP_MAX_OPEN` (default 5). Documented in `CONFIGURATION.md`. |
| Wiring | `roadmap` valid for `cadence run`, scheduler, `status`, run logs. Self-exclusive lock only (no worktrees). |
| Skill | `skills/cadence-loop-roadmap/SKILL.md` — same contract shape as the other loops: scope, Step 0, unattended rules, JSON summary + dated digest. |

## Failure handling

A run that errors records the failure in the run digest and exits non-zero so
the scheduler surfaces it; it stamps no issue (it owns none). Missing/empty
goal is the idle case, not a failure. Never asks questions; never stalls.

## Testing

- `linear issue-create` — fake `post`: asserts team/project/assignee/label
  injection and the cap refusal.
- `tasks add` — temp file: format round-trip via `tasks validate`.
- Conductor fence — an `agent:proposed` candidate is never tagged `agent:auto`.
- Shellcheck on any script changes. No test touches the network.

## Out of scope (deliberate)

- Feeding proposals into autonomous mode in any form.
- Reading production logs, telemetry, or external feedback sources.
- A separate proposals report or holding-pen state — the board is the state
  machine.
