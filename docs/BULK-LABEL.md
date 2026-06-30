# Bulk Label — Cheatsheet

Add or remove Linear labels across many issues in one command. Read-only by
default behaviour is *not* assumed: a live run writes, so it confirms first.

## Synopsis

```text
cadence linear bulk-label [ISSUE ...] [--where-label NAME]
                          [--add NAME ...] [--remove NAME ...]
                          [--dry-run] [-y|--yes]
```

Pick the **targets** one of two ways, then say which labels to **add/remove**.

## Flags

| Flag | Meaning |
|---|---|
| `ISSUE ...` | Explicit issue keys, e.g. `STU-201 STU-202`. |
| `--where-label NAME` | Target every in-scope issue currently carrying `NAME`. |
| `--add NAME` | Label to add. Repeat for several: `--add a --add b`. |
| `--remove NAME` | Label to remove. Repeatable. |
| `--dry-run` | Print the plan, write nothing. |
| `-y`, `--yes` | Skip the confirmation prompt (for scripts / autonomous use). |

You **cannot** combine explicit `ISSUE` keys with `--where-label` — it errors
rather than guess. You **must** give at least one `--add` or `--remove`.

## Recipes

```bash
# Gate a hand-picked batch for spec
cadence linear bulk-label STU-201 STU-202 STU-205 --add agent:spec

# Preview gating every triaged issue for spec (writes nothing)
cadence linear bulk-label --where-label agent:triaged --add agent:spec --dry-run

# Do it for real (prompts before writing)
cadence linear bulk-label --where-label agent:triaged --add agent:spec

# Clear the Stale flag from everything carrying it
cadence linear bulk-label --where-label Stale --remove Stale

# Swap one gate for another on a single issue
cadence linear bulk-label STU-210 --add agent:build --remove agent:spec

# Scripted: tag a batch agent:auto with no prompt
cadence linear bulk-label --where-label agent:triaged --add agent:auto -y
```

## Safety

- **Scope guard** — every target is checked against your configured team,
  project, and assignee *before* any write. It cannot touch out-of-scope issues.
- **Confirmation** — a live run prints the plan and waits for `y`. Any other
  answer (or no input) aborts with nothing written.
- **Per-issue isolation** — an out-of-scope or missing issue becomes an entry in
  `errors`; it does not stop the rest of the batch.

## Output (JSON, on stdout)

| Field | When | Meaning |
|---|---|---|
| `dry_run: true`, `targets`, `count` | `--dry-run` | What would change. |
| `aborted: true`, `count` | declined at prompt | Nothing was written. |
| `updated`, `errors`, `count` | live run | Keys changed, and any per-issue failures. |
| `note` | no match | e.g. `--where-label` matched nothing. |

The confirmation prompt is written to stderr, so stdout stays clean JSON for
piping.
