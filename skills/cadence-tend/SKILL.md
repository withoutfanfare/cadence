---
name: cadence-tend
description: Periodic hygiene "dream" pass over a Clio memory namespace — dedupe near-identical memories, re-score importance against the current priority scale, archive stale/transient/superseded entries, and re-file misclassified ones. Clio auto-consolidates into summaries but does NOT archive duplicates or re-prioritise as priorities change; this fills that gap. Use when the user says "clean up Clio", "tidy the memories", "re-prioritise memories", "memory hygiene", "clio dream/tend", or on a schedule.
argument-hint: "[namespace] [--apply]"
---

# cadence-tend — Clio memory hygiene ("dream") pass

Keep a Clio namespace healthy: no duplicates, importance scores that reflect current
priorities, and no stale clutter. Reusable for any project's namespace.

## Mode
- **Default: dry-run** — inventory and propose changes, write nothing.
- **`--apply`** — execute the changes. (Scheduled runs pass `--apply`.)

## Scope
- One namespace: the first arg, else auto-detect from the cwd (pass `cwd` to the
  `memory_*` tools, using `$MEMORY_NAMESPACE` when set). Never touch any other namespace.

## When to run — self-gate (lets it be scheduled often, stays cheap)

So a frequent schedule (every few hours) doesn't waste a full pass on a clean store,
gate at the very start and exit early when there's little to do:

1. Read the marker `~/.claude/schedules/cadence-tend.<ns>.last` where `<ns>` is the
   namespace with `:` and `/` replaced by `-` — an ISO-8601 timestamp of the last full
   pass; absent on first run → always run.
2. `memory_recall` recent memories (`sort_by: created_desc`, `limit: 30`) and count how
   many were **created after** the marker timestamp.
3. **Skip** — log `store fresh — N new since <ts>; skipping` and exit — if **fewer than
   8** new since last pass **and** the last pass was **< 3 days** ago (the 3-day backstop
   forces an occasional pass even when quiet, to catch slow drift / re-prioritisation).
4. Otherwise do the full pass below, and at the end write the current UTC timestamp
   (`date -u +%FT%TZ`) to the marker file.

This makes "run every 6h" behave like "tend after ~8 new memories" — responsive during
busy spells, near-free when idle. Tune the threshold (8) / backstop (3 days) to taste.

## Importance scale (re-score against this)
- **5** — breaking it causes real harm: security, money / data-integrity, auth,
  payment, correctness rules.
- **4** — codebase conventions, durable gotchas, operating rules.
- **3** — useful context, not an enforceable rule.
- **≤2** — minor; an archive candidate if also stale.

## Procedure
1. **Inventory.** `memory_recall` all non-archived memories in the namespace
   (`response_format: json`, paginate with `offset`/`limit` until exhausted). Note id,
   kind, title, importance, tags, source_ref, created/updated, access_count.
2. **Dedupe.** Group memories on the same topic (near-identical title/content). For
   each group keep **one canonical** — the most complete, highest-importance one; give
   it a stable `source_ref` (e.g. `constraint:<slug>`) and `upsert` it. **Archive** the
   rest. (Recall: a single rule re-stored every run with no `source_ref` is the usual
   cause — fix by giving it a stable ref so future writes update it.)
3. **Re-score.** Compare each kept memory's importance to the scale. If miscalibrated,
   `memory_remember` it again with the corrected `importance` and its stable
   `source_ref` (upsert). Bump under-scored critical rules (money / security /
   data-integrity) to 5; demote transient or opinion notes.
4. **Re-file.** A `fact` that is really an enforceable rule → `kind: constraint`.
5. **Archive stale/transient.** Session-specific observations that no longer matter,
   superseded decisions, dated status reports whose content is captured elsewhere.
   **Conservative — when unsure, KEEP.** Never archive a current high-importance rule.
6. **Report.** Counts (deduped, re-scored, re-filed, archived, kept) and a per-action
   list with ids, so anything can be reviewed / `memory_unarchive`d.

## Safety (hard rules)
- **Archive, never delete** — every removal is reversible via `memory_unarchive`.
- **Cap archives at ~15 per run.** If more look stale, list them and stop — don't
  mass-archive in one pass.
- Never act outside the target namespace.
- Preserve human-authored, current, high-importance memories unless clearly superseded.

## Pairs with Clio's own consolidation
Clio's auto-consolidation *summarises* many memories into one; `cadence-tend` *prunes and
re-prioritises*. Run them together: consolidation for the long tail, cadence-tend weekly
for dupes + scores. Schedule via `/cadence-tend`, passing `--apply`.
