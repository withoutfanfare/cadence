---
name: cadence-feed
description: >-
  Show the recent chronological activity feed for the Cadence agent loops —
  one plain line per run. Use for 'loop activity', 'what have the loops been
  doing', 'cadence feed', or 'recent runs'.
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
