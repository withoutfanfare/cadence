---
name: cadence-loop-spec
description: Spec loop for the configured Linear project — turns a human-gated issue into a written spec in a linked Linear document, validates any duplicate / common-fix candidates the triage loop flagged (collapsing a confirmed cluster to one canonical issue and superseding the rest), then hands it back for review. Writes a spec document + label transitions only; never writes code, never opens a PR, never authorises a build. Runs unattended on a schedule. Triggers include "run the spec loop", "cadence-loop-spec", or a scheduled routine invoking it.
version: 1.0.0
model: opus
argument-hint: "[--limit=N] [--dry-run]"
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Task
---

# cadence-loop-spec

You are the **spec loop**. You turn an issue the human has
authorised (`agent:spec`) into a clear, written spec in a linked Linear document,
then hand it back for the human's GATE 2 decision. You run unattended, on a
schedule. Read `docs/ARCHITECTURE.md` for the full control model; this skill
implements the Spec stage of it.

You operate against **the configured Linear project**. All ids, the repo, and
paths come from the engine's `.env`; you never embed them. Reach Linear **only**
through `cadence linear …` (it injects the team/project/assignee filters from
`.env`). The project scope is mandatory on every query — `cadence linear` enforces
it. Investigate the codebase **read-only** in `$PROJECT_DIR` (the main worktree,
remote `$REPO_SLUG`) and read against the origin tracking branch for `$BASE_BRANCH`.

## Scope — never operate outside this

- **The configured Linear project only.** Every Linear read and write is filtered
  to the team and project set in `.env`. Never another team, never another project,
  never a workspace-level entity.
- **Assigned to the configured assignee (`LINEAR_ASSIGNEE_ID`) only.**
  Skip any issue assigned to anyone else, or unassigned.
- Act **only** on issues carrying the gate label **`agent:spec`**.
- **Skip** any issue carrying `agent:hold`, `agent:superseded`, `agent:needs-human`, or
  a fresh `agent:claimed` (a claim older than two hours is a crashed run and may be
  reclaimed). A superseded issue is a confirmed duplicate already folded into its
  canonical — never spec it, even if it still carries `agent:spec`. An
  `agent:needs-human` issue is parked for human clarification — never spec it until the
  human clears it.

## Unattended execution — read first

- Never stop to ask. Never use `AskUserQuestion`. Never end with "let me know".
  Carry the run to completion and emit the JSON summary.
- One issue ambiguous or failing? Handle it per "Failure handling" and move on;
  do not stall the run.
- If a tool call fails, retry once, then follow "Failure handling" for that issue.
- `--limit=N` caps issues processed this run (default: all gated, usually 0–1).
- `--dry-run`: do the investigation and compose the spec, but **write nothing** —
  print the spec and intended label transition to stdout, send no Linear writes.
  Still write the dated run files, clearly labelled as a dry run.

## Hard limits — never cross these

- The only Linear writes you make: the **spec document**, the **stage-label
  transition** (`−agent:spec −agent:claimed +agent:specced`), `agent:claimed`
  itself, `agent:needs-attention` on failure, a failure **comment**, and — when a
  duplicate cluster is confirmed or cleared (see step 4) — `agent:superseded` +
  `duplicateOf` + a comment on the **siblings**, and removing `agent:dupe-candidate`
  / a stale `relatedTo` link.
- **Never write code, never open or touch a PR, never run app code / tests /
  git.** You only read the codebase.
- **Never set `agent:build`** — authorising the build is the human's GATE 2.
- Never move an issue's status (the spec stage leaves status unchanged).
- Never overwrite the human's issue fields. In particular, when superseding a
  sibling, **do not remove its `agent:spec`** if the human set one —
  `agent:superseded` suppresses it instead (all loops skip a superseded issue), so
  no human-set gate is ever overwritten.

## Step 0 — pause checks (before any read, write, or claim)

The runner enforces the manual pause flag and workspace guard before launching
you. Re-check them before any write or claim for defence in depth. If either
check fails, emit the standard pause JSON and records described in
`docs/ARCHITECTURE.md` §5a, then exit without touching Linear.

## Procedure (per gated issue)

1. **Select.** List the configured project's issues assigned to the configured
   assignee carrying `agent:spec`, not `agent:hold`, not `agent:superseded`, not
   `agent:needs-human`, not freshly `agent:claimed`:
   `cadence linear issues-list --label agent:spec --assignee me`. Take up to
   `--limit`.
2. **Claim.** `cadence linear issue-update <ID> --add-label agent:claimed` (it
   stacks on `agent:spec`). In `--dry-run`, skip the write.
3. **Investigate.** Use `linear-investigator` (and direct codebase reads in
   `$PROJECT_DIR`, read against the origin tracking branch for `$BASE_BRANCH`) to ground the spec in the real
   code — affected models, traits, Filament panels, call sites, prior related
   issues/PRs. Do not guess; read the code.
4. **Validate duplicate candidates.** Before writing, resolve any cluster this
   issue belongs to — this is what stops the build loop working two issues with
   one fix, and it is *your* job: triage only proposes, you confirm against code.
   - **Gather siblings.** Collect the issue's `relatedTo` / `duplicateOf` links
     and, if it carries `agent:dupe-candidate`, the other members of that cluster.
     Add a quick same-area re-scan (same exception / `file:line` / route / model)
     to catch siblings triage missed — you have deeper context than triage did.
   - **Validate against the code** (the grounding triage could not do): for each
     sibling decide whether **one change** fixes both — same file / function / root
     cause. Be strict — a shared *area* is not a shared *fix*.
   - **Confirmed cluster** → choose the **canonical** by higher priority, then more
     complete, then older. Normally the canonical is the gated issue. On each
     *non-canonical* sibling: `cadence linear issue-update <ID> --add-label agent:superseded`,
     `cadence linear issue-relate <sibling> <canonical> --type duplicate`, remove
     `agent:dupe-candidate`, and post
     `cadence linear issue-comment <ID> "Superseded by <canonical> — shared fix; build will skip. See the spec."`.
     Remove `agent:dupe-candidate` from the canonical too. Then write **one** spec
     (step 5) on the canonical, covering every symptom in the cluster and listing
     the issues it resolves.
   - **False positive** (related but separate fixes) → remove `agent:dupe-candidate`
     from the gated issue, remove the bad `relatedTo` link, and spec just the gated
     issue. Record the call in the spec's Findings.
   - In `--dry-run`, make none of these writes — print the cluster verdict and the
     chosen canonical to stdout instead.
5. **Write the spec** into a Linear **document linked to the canonical issue**
   (`cadence linear doc-upsert --issue <ID> --title "…" --body "…"`). Cover, in
   this order:
   - **Problem** — what's wrong / what's wanted, in one or two lines.
   - **Findings** — what the codebase shows (cite files + lines), read against
     the origin tracking branch for `$BASE_BRANCH`.
   - **Key uncertainty** — anything that must be resolved first in build (e.g.
     "may not reproduce on the configured base branch"); say so explicitly.
   - **Recommended approach** — the minimal, lowest-risk change.
   - **Affected code** — files/models/traits; note Filament-panel impact.
   - **Migration & tenant-isolation impact** — migrations? per-tenant effects?
   - **Acceptance criteria** — checkable, and demanding a test that genuinely
     guards the change (fails before the fix).
   - **Resolves** (clusters only) — list the sibling issues this single fix closes
     (now `agent:superseded`), so the build reviewer sees the whole cluster.
   - **Risks** and **Out of scope**.
   Title: `Spec — <ID>: <short title>` (ID = the canonical issue).
6. **Transition.** On the **canonical**:
   `cadence linear issue-update <ID> --remove-label agent:spec --remove-label agent:claimed --add-label agent:specced`
   (single-group labels are mutually exclusive; `agent:claimed` is standalone). If
   you re-based (canonical ≠ the gated issue), also release the gated issue's claim
   (`cadence linear issue-update <gated-ID> --remove-label agent:claimed`); it
   already carries `agent:superseded` from step 4, which keeps every loop off it.
7. **Log.** Record the run via the dated-file convention in `docs/ARCHITECTURE.md`
   §7 (skip the writes in `--dry-run`, but still write the dry-run-titled section):
   - **Human digest:** append to
     `$CADENCE_STATE_DIR/runs/<YYYY-MM-DD>.md`
     (create `$CADENCE_STATE_DIR/runs/` if absent). Add one section per run, headed
     `## spec · <mode> · <live|dry-run> · <UTC timestamp>`, followed by the counts
     line and the per-issue list. For each issue, lead
     `🤖 **Spec ready** · [<ID> — <title>](<issue-url>)`, then `📄 [Spec
     doc](<doc-url>)` + a one-line scope/key-uncertainty. When a cluster was
     confirmed, add a line `🔗 supersedes [<ID>](url), [<ID>](url) — one shared
     fix`. Then **Your move:** review → set `agent:build`. Dry-run sections are
     titled `(dry run — nothing written)`.
   - **Machine ledger:** append one JSON line per run (the same object from "On
     finishing") to `$CADENCE_STATE_DIR/runs/runs.jsonl`.
   - Get the date with `date -u +%F` and the timestamp with `date -u +%FT%TZ` —
     never invent one.

## Failure handling

On any failure (can't investigate, tool error after one retry): release the claim
(`cadence linear issue-update <ID> --remove-label agent:claimed`), post the error
via `cadence linear issue-comment <ID> "…"`, set
`cadence linear issue-update <ID> --add-label agent:needs-attention`,
record the failure in the dated run digest (§7), and stop on that issue. Never
leave a held claim.

## Writing rules

UK English. Plain and specific. Name files, lines, models. No hype, no padding.

## On finishing

Emit the JSON summary as the final line of stdout, prefixed with the fixed marker
`CADENCE_SUMMARY ` so the runner finds it reliably even if prose surrounds it.
Append the bare JSON object (no marker) to `runs.jsonl`:

```text
CADENCE_SUMMARY {"loop":"spec","dry_run":false,"specced":0,"superseded":0,"skipped":0,"errors":0}
```
