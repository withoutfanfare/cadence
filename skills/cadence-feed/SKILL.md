---
name: cadence-feed
description: Recent chronological activity feed of the Cadence agent loops — one plain line per run (what each triage/spec/build/revise run did). Use when the user asks "loop activity", "what have the loops been doing", "cadence feed", "recent runs", or invokes /cadence-feed. Optional arg = number of lines.
argument-hint: "[lines]"
---

# cadence-feed

Show the chronological activity feed (newest last). Default 30 lines; if the user
gave a number, use it:

```bash
cadence feed ${ARG:-30}
```

Then summarise in **one** line what the loops have been up to lately — e.g.
"mostly idle no-ops; last real activity: triage enriched 5 issues at 06:14 (go-live)".
Distinguish `LIVE` from `dry` lines. If a `PAUSED` or `ERROR` line appears, call it out.
