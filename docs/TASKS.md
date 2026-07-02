# Cadence — Local Task File Format

When a project sets `TASK_BACKEND=file`, its board lives in a single markdown
file (`TASK_FILE`, default `cadence/tasks.md`). This is the format people and
agents must follow when adding or editing tasks. `cadence doctor` validates the
file against these rules; run it after editing by hand.

The loops treat this file exactly as they treat a Linear board: the `labels:`
line is the state machine (see [LABELS.md](LABELS.md)), and the same invariants
hold — gate labels are set by a human only, agents fill blanks and record
status, PRs are always drafts.

## Layout

```markdown
# Cadence Tasks

## TASK-1: Short imperative title
status: open
labels: agent:triaged, Bug

Free-form body: context, acceptance criteria, notes. Markdown is fine.
Use `###` or deeper for any sub-headings inside a body.

## TASK-2: Another task
status: open
labels:

Body for the second task.
```

## The rules (what `doctor` checks)

1. **Each task starts with `## <ID>: <Title>`.** The ID must not contain a
   colon; a title must follow the colon. `## TASK-2 no colon` is invalid — it is
   silently swallowed into the previous task's body, so `doctor` flags it.
2. **`## ` is reserved for task headers.** Do not start a body line with `## `.
   Use `###` or more for sub-sections.
3. **`status:` and `labels:` must be the two lines immediately below the
   header**, with no blank line between. A blank line ends the header block, so
   metadata placed after it becomes body text and is lost — `doctor` flags this.
4. **`labels:` is comma-separated** (may be empty). Everything after the blank
   line following the header is the description.
5. **IDs are unique.** Two tasks with the same ID: only the first is reachable
   by `cadence tasks get/update`. `doctor` flags duplicates.

Inside the body, lines that happen to start with `status:` or `labels:` (for
example `status: 200` in a spec) are kept as body text — they are only metadata
in the header block. Only the *first* body line is checked, so ordinary prose is
never mistaken for a stranded field.

## Adding a task by hand or by agent

- New task → `status: open` and **no gate label** (or `agent:triaged` if it is
  already ready for a human to grant spec). It then waits for a human, same as a
  fresh Linear issue.
- **Never add a gate label** (`agent:spec`, `agent:build`, `agent:revise`,
  `agent:auto`) unless you are the human granting that gate. Loops write the
  status labels (`agent:specced`, `agent:pr-open`, …) themselves.

## Editing via the CLI

```bash
cadence tasks list [--label L] [--status S]   # read the board
cadence tasks get <ID>                         # one task as JSON
cadence tasks update <ID> --status S --add-label L --remove-label L [--body-file F]
cadence tasks validate                         # check the file (what doctor runs)
```

The CLI always re-renders the file in canonical form, so round-tripping through
`update` fixes spacing automatically. Hand edits are where the rules above
matter — run `cadence doctor` (or `cadence tasks validate`) afterwards.
