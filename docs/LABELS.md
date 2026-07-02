# Cadence — Agent Label Vocabulary

The `agent:*` labels are the state machine. Loops read labels to decide what to
act on and write labels to record what they did.

Create the whole set during installation with `cadence labels init`; see
[Installation](INSTALL.md#6-create-the-linear-labels).

The same vocabulary applies to the local file backend (`TASK_BACKEND=file`):
the labels below go in a task's `labels:` line in `cadence/tasks.md`, with no
creation step. See [TASKS.md](TASKS.md) for that format.

---

## Gate labels — set by a human only, never by an agent

| Label | Who sets | Who clears | Gates |
|---|---|---|---|
| `agent:spec` | Human | Spec loop (replaces with `agent:specced` or `agent:needs-attention`) | Allows the spec loop to act |
| `agent:build` | Human | Build loop (replaces with `agent:pr-open` or `agent:needs-attention`) | Allows the build loop to act |
| `agent:revise` | Human | Revise loop (replaces with `agent:revised` or `agent:needs-attention`) | Allows the revise loop to act |
| `agent:auto` | Human | Advance loop (on accept/escalate) | Opts the issue into autonomous mode: the advancer may grant its gates (spec→build→PR). Only acts when `AUTONOMOUS` is enabled |

---

## Status / "your move" labels — set by a loop

| Label | Who sets | Who clears | Effect |
|---|---|---|---|
| `agent:triaged` | Triage loop | Human (to force re-triage) | Triage skips the issue; it will not be re-triaged until this label is removed |
| `agent:needs-human` | Triage loop | Human | All loops skip the issue; surface to human for manual classification |
| `agent:dupe-candidate` | Triage loop | Spec loop (on validation) or human | Spec loop validates the duplicate proposal; either supersedes siblings or clears this flag |
| `agent:specced` | Spec loop | Human (sets `agent:build` to proceed) | Signals spec is complete; waiting for human to approve and advance |
| `agent:pr-open` | Build loop | Human (sets `agent:revise` or merges) | Signals a draft PR is open and reviewed; waiting for human gate 3 |
| `agent:revised` | Revise loop | Human (re-reviews PR) | Signals revise loop has pushed; waiting for human to re-review |
| `agent:superseded` | Spec loop | Human (rarely) | Hard suppressor: all loops skip this issue; the canonical issue covers it |
| `agent:needs-attention` | Any loop | Human | A run failed; human must investigate the run log before proceeding |
| `agent:claimed` | Any loop (at run start) | Same loop (at run end or failure) | Concurrency lock; a claim older than 2 hours may be reclaimed |

---

## Exception label

| Label | Who sets | Who clears | Effect |
|---|---|---|---|
| `agent:hold` | Human | Human | Brake: all loops skip this issue regardless of any other labels |

---

## Non-`agent:` label used by the loops

| Label | Who sets | Who clears | Effect |
|---|---|---|---|
| `Stale` | Triage loop | Human | Issue has had no update in 30 days; flagged for revalidation or closure — not auto-closed |

---

## Flow summary

```text
NEW ─(triage)→ agent:triaged
   ──[human: agent:spec]──▶ (spec) → agent:specced
   ──[human: agent:build]──▶ (build) → agent:pr-open
   ──[human review]──▶ merge   OR   [human: agent:revise] → (revise) → agent:revised → re-review
```

`agent:claimed` rides along during any active run.
`agent:hold` / `agent:superseded` / `agent:needs-human` take an issue out of play.
`agent:needs-attention` flags a failed run for the human.
