---
name: cadence-deep
description: >-
  Show the full per-run digest for the Cadence agent loops — what each run
  changed (issues triaged, specs written, PRs opened, review verdicts). Use
  for 'loop digest', 'what did the loops change', 'cadence deep', or 'show me
  the detail'.
argument-hint: "[YYYY-MM-DD]"
---

# cadence-deep

Show the dated digest (today UTC by default, or the date the user gave):

```bash
DATE="${ARG:-$(date -u +%F)}"
F="$CADENCE_STATE_DIR/runs/$DATE.md"
[ -f "$F" ] && wc -l "$F" && echo "---" && cat "$F" || echo "No digest for $DATE"
```

The file can be long (one section per run). Present the **most recent 2–3 run
sections** in full (that's what the user usually wants), and note how many run
sections the file holds in total. Offer to show a specific earlier run if asked.
For the machine-readable view, point them at `$CADENCE_STATE_DIR/runs/runs.jsonl`.
