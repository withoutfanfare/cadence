---
name: cadence-glance
description: Glanceable status of the Cadence agent loops — live/paused state, launchd jobs and last exit codes, last run per stage, and the recent activity feed. Use when the user asks "loop status", "how are the loops", "cadence glance", "what are the agents doing", or invokes /cadence-glance.
---

# cadence-glance

Run this and show the output verbatim:

```bash
cadence status
```

Then add **one** line of interpretation only if something needs attention:
- a launchd job with a non-zero last-exit code,
- a `PAUSED` state,
- `ERROR`/`needs-attention` in the recent activity,
- or no runs in the last ~90 min (the schedule may not be firing).

If everything looks healthy, just say so in a few words. Don't pad.
