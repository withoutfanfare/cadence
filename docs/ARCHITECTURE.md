# Cadence — Architecture

The master control model for the Cadence engine. Four loop skills each implement
one stage; this document is the single source of truth for how the stages connect,
who holds authority, and what each label means. If a skill and this document
disagree on a *fact* (an id, a path), the skill wins; if they disagree on
*control flow* (a gate, a transition), this document wins.

For setup and daily use, start with [Installation](INSTALL.md),
[Configuration](CONFIGURATION.md), and [Operating Cadence](OPERATING.md).

---

## 1. The principle — human gates, agents execute

The loops do the work; the human grants the authority. Between every automated
stage there is a **gate**: a point where a human decision is required before the
next loop may act. An agent never grants authority to the stage after it — it
finishes its own work, records the result on the issue with a label, and stops.
Moving an issue forward across a gate is always a human action.

Guarantee: nothing gets specced, built, or merged that a human did not explicitly
authorise, even though no human has to open the issue tracker to keep the board
tidy or to read what the agents produced.

---

## 2. The board is the state machine — label vocabulary

An issue's labels are its state. The loops read labels to decide what to act on
and write labels to record what they did. Full label vocabulary:
[Agent Labels](LABELS.md).

### Gate labels — set by a human only, never by an agent

| Label | Meaning | Authorises |
|---|---|---|
| `agent:spec` | Human wants this issue specced | the **spec** loop |
| `agent:build` | Human approved the spec, wants it built | the **build** loop |
| `agent:revise` | Human reviewed the PR and wants changes | the **revise** loop |

### Status / "your move" labels — set by a loop

| Label | Set by | Meaning |
|---|---|---|
| `agent:claimed` | any loop | a run is working this issue now (see §6) |
| `agent:triaged` | triage | every determinable field filled; settled |
| `agent:needs-human` | triage | cannot be classified; parked, surfaced once |
| `agent:dupe-candidate` | triage | proposed member of a duplicate cluster |
| `agent:specced` | spec | spec written — your move: review, then set `agent:build` |
| `agent:pr-open` | build | draft PR opened + reviewed — your move: review |
| `agent:revised` | revise | revise loop pushed — your move: re-review |
| `agent:superseded` | spec | confirmed duplicate, collapsed into canonical |
| `agent:needs-attention` | any loop | a run failed — see the run log / digest |
| `Stale` | triage | no update in 30 days; flagged, not closed |

### Exception label

`agent:hold` — human override; every loop skips the issue regardless of other labels.

---

## 3. The lifecycle

```bash
   NEW issue (no agent label)
        │
        │  TRIAGE loop — no gate; any in-scope, non-terminal issue
        ▼
   agent:triaged  (+ agent:dupe-candidate?)   ──cannot classify──▶  agent:needs-human
        │
        │  ◆ GATE 1 — human sets  agent:spec
        ▼
   SPEC loop  (agent:claimed)  → writes spec doc; validates dupes (siblings → agent:superseded)
        ▼
   agent:specced
        │
        │  ◆ GATE 2 — human approves spec, sets  agent:build
        ▼
   BUILD loop  (agent:claimed)  → worktree off base branch · gates · DRAFT PR · code review
        ▼
   agent:pr-open  +  In Review  +  draft PR        ◀─────────────┐
        │                                                        │
        │  ◆ GATE 3 — human reviews the draft PR                 │
        ├── satisfied → human marks PR ready / merges (human-only)│
        └── changes → human sets agent:revise                    │
                   │                                             │
                   ▼                                             │
            REVISE loop (agent:claimed) → push to SAME draft PR ─┘
                   → agent:revised (back to Gate 3)
```

`agent:superseded` / `agent:hold` / `agent:needs-human` take an issue out of play.

---

## 4. The gates

- **Gate 0 (triage)** — no gate. Triage only fills blanks and proposes; it runs on
  any in-scope, non-terminal issue. Its terminal markers stop it re-chewing the same
  issue.
- **Gate 1 (spec)** — human sets `agent:spec`. Only then may the spec loop act.
- **Gate 2 (build)** — spec loop stops at `agent:specced`; human reads the spec doc
  and sets `agent:build`. This is the gate that lets code be written.
- **Gate 3 (review)** — build loop stops at `agent:pr-open` with a draft PR. Human
  either merges (human-only) or sets `agent:revise`; the revise loop pushes to the
  same draft PR and stops at `agent:revised` — back to Gate 3, repeatable.

---

## 5. Global invariants — every loop obeys these

1. **Consume your trigger, set a terminal.** A loop removes the gate/status label
   that triggered it and leaves exactly one terminal marker.
2. **Never grant downstream authority.** No loop sets `agent:spec` / `agent:build` /
   `agent:revise`, moves an issue past the review state, merges, or marks a PR ready.
3. **Write defaults differ per stage.** Triage is opt-in to writes: it analyses and
   writes nothing unless invoked with `--live`. Spec, build, and revise are live by
   default and opt *out* with `--dry-run`. `cadence run <stage>` invokes the live path
   for every stage (it adds `--live` for triage); pause the loops to hold them. Either
   way a run writes only what that stage is permitted to write.
4. **Draft-only PRs against the base branch.** Build/revise work in a worktree,
   rebase on origin, PR is always a draft — never merged, never marked ready, by an
   agent.
5. **Never overwrite a human's field.** Fill blanks only.
6. **Read-only on the codebase except build/revise.** Triage and spec investigate
   read-only. Only build and revise edit files inside their own worktree.
7. **Report and meter.** Every run writes a dated digest file (§7) and prints a
   JSON summary to stdout.

---

## 5a. PAUSED + workspace guard — Step 0 of every loop

Before any read, write, or claim, every loop runs two pause checks. If either
trips it writes nothing, fires a notification, appends a `⏸` line to the dated
run log, prints `{"stage":…,"paused":true,"reason":…}`, and exits.

1. **Manual pause.** If `$CADENCE_STATE_DIR/runs/PAUSED` exists, every loop is off.
   Create that file to stop all loops (e.g. during a deploy or while you work on
   the board yourself); delete it to resume. `reason: manual`. The runner
   (`run-loop.sh`) also checks this flag *before* invoking the model, so a paused
   stage exits immediately and costs nothing — enforcement does not depend on the
   prompt.
2. **Workspace guard.** The loop calls `cadence linear teams` and proceeds only
   if the configured team id is present in the response. If the API key cannot
   see that team, the loop pauses with `reason: wrong-workspace`. It resumes
   automatically once `.env` and the Linear API key point at the intended
   workspace again.

This guard exists because the Linear API key is the runtime authority boundary.
The workspace it can currently reach is treated as the authoritative signal for
whether it is safe to run.

The `advance` runner also exits before invoking the model when autonomous mode is
on but no in-scope issue carries `agent:auto`. That is recorded as an idle run,
not a pause: there is no safety fault, just no autonomous work to advance.

---

## 6. Engine vs profile

**Engine** — the generic control-flow code, scripts, and skills in this repo.
Skills hold no ids, no project names, no repo paths.

**Profile** — the project-specific facts loaded at runtime from `.env` and
`memory/`. A profile supplies: the team id, project filter, assignee id, repo
remote, base branch, worktree root, and the Clio namespace. The engine reads these
from environment variables at runtime.

This separation means the same engine code can run against multiple projects by
switching `.env` — without touching the skills or scripts.

### `.env` conventions

See [Configuration](CONFIGURATION.md) for the full profile reference.

- **Quote any value containing spaces.** The bash loader (`engine/lib/lib-env.sh`)
  *sources* `.env`, so a multi-word value must be quoted or sourcing breaks, e.g.
  `GATE_TEST="composer test:filter"` (not `GATE_TEST=composer test:filter`).
- **`RUNNER_PATH_PREPEND`** (optional) — a directory prepended to the runner's `PATH`
  for project tooling, e.g. a specific PHP so bare `php`/`composer` resolve correctly:
  `RUNNER_PATH_PREPEND="$HOME/Library/Application Support/Herd/bin"`. When unset, the
  runner auto-includes Herd's bin if that directory exists, otherwise stays generic.

---

## 7. Runtime state — dated-file log + digest convention

Every run records itself in `$CADENCE_STATE_DIR`:

```bash
$CADENCE_STATE_DIR/
  logs/          launchd stdout/stderr (one file per stage)
  runs/
    activity.log   one line per run (for the feed view)
    YYYY-MM-DD.md  human digest for that day
    runs.jsonl     machine ledger — one JSON object per run, newline-delimited
    PAUSED         touch to pause all loops; delete to resume
```

**Human digest** (`runs/YYYY-MM-DD.md`): append one section per run, headed:

```text
## <stage> · <mode> · <live|dry-run> · <UTC timestamp>
```

Followed by the counts line and the per-issue list. Each entry:
`ISSUE-N — title (url) · <Type> · P<n> / <cycle> — reason`. Skipped issues:
`⚠️ … · skipped — reason`. Dry-run sections are titled `(dry run — nothing written)`.

**Machine ledger** (`runs/runs.jsonl`): append the same JSON object printed to
stdout — one line per run, one object per line. No pretty-printing.

Get the date/timestamp from the shell (`date -u +%FT%TZ`), never invent one.

The `runs/` directory is git-ignored by default — run artefacts, not committed
history. Track it instead if you want the audit trail in git.

---

### 7a. Memory recall convention (Clio / shared knowledge tier)

Clio (`memory_*` tools, project-scoped namespace) holds durable cross-task
knowledge: constraints, conventions, gotchas, decisions, recurring review findings.
It is **not** task state (that's labels) or the per-task brief (that's the spec
doc).

**Importance scale (set on every write):**
- **5** — breaking it causes real harm: security, money handling, data integrity,
  auth, payment correctness.
- **4** — codebase conventions and gotchas ("always use php84", "discounts via
  the canonical helper", "automation fills blanks only").
- **≤3** — minor/contextual; usually not worth storing.

**Reading:** recall with `importance_min: 4`, `sort_by: importance_desc`, a small
`limit` (≈8). Keep any `query` **short — 1 to 3 terms — or omit it entirely.**
Clio's full-text search AND-matches every term in the query, so a long query
("money pence order total payment checkout") silently drops rules that lack even
one of the words. Better to pull the top high-importance rules and let the
orchestrator pick the few relevant to the current change. A wall of rules distracts
a weak model — include only what applies.

**Writing:** score important discoveries high, and deduplicate. When a stage
uncovers a durable rule, or a review flags a *recurring* class of mistake,
`memory_remember` it with:
- `importance` per the scale above
- `kind: constraint` (for codebase rules) or `kind: decision` (for architectural
  choices)
- `upsert: true` with a stable `source_ref` (e.g. `constraint:money-pence`) so
  the entry updates instead of duplicating across runs

Only store durable, non-obvious facts — never transient run state, speculation, or
anything already obvious from the codebase.

---

## 8. Crashes and concurrency — `agent:claimed`

A loop stamps `agent:claimed` when it starts an issue and removes it when done, so
two scheduled runs never act on the same issue at once. A claim **older than two
hours** is a crashed run and may be reclaimed; a **fresh** claim is respected.

---

## 9. Gate semantics — `GATE_LINT`, `GATE_TEST`, `GATE_ANALYSE`

These three environment variables (set in `.env`) control the build loop's
verification step after the implementer writes code.

- A **non-empty value** is the shell command to run (e.g. `composer test -- --no-coverage`).
- A **blank value** means skip that gate entirely.
- **Non-zero exit** from a gate command is a failure. The loop hands the failure
  output back to the implementer for one repair turn, then escalates to
  `agent:needs-attention` if the repair does not pass.

All three gates are optional. Configure only those that apply to the project.
