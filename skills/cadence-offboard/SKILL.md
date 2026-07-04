---
name: cadence-offboard
description: Guided offboarding of a project from Cadence — pauses its loops, disables scheduling, and removes it from the scheduler registry, deleting nothing by default. Use when the user says "offboard this project", "remove this project from cadence", "stop cadence running here", "take this project off the scheduler", or invokes /cadence-offboard.
---

# cadence-offboard

You are taking a project **off** Cadence for the user, safely. This skill only
pauses, deschedules, and unregisters — it never deletes the project's config,
and it deletes run history only when the user explicitly asks for a purge.

Work in **British English**. Use only the shell and the `cadence` CLI, so this
runs the same under Claude, Codex, or any agent.

## Step 1 — identify the project

Ask which project to offboard if it is not obvious from the conversation or the
current directory. Confirm what is registered first:

```bash
cadence schedule status
```

Show the user the matching line and confirm it is the right project before
touching anything.

## Step 2 — offboard

```bash
cadence offboard "<PROJECT_DIR>"
```

This pauses the project's loops, writes `CADENCE_SCHEDULED=0` into its config,
and removes it from the scheduler registry. If it was the last registered
project, the launchd scheduler job is unloaded too. Nothing is deleted.

## Step 3 — offer the purge (optional, destructive)

Ask **"Do you also want to delete the project's run history (logs, digests,
run records)?"** Only if the user clearly says yes:

```bash
cadence offboard "<PROJECT_DIR>" --purge
```

`--purge` removes only the project's own state dir. The config
(`cadence/.env`, which holds their API key and settings) always stays — point
out where it is so the user can delete it by hand if they want a full clean-up.

## Step 4 — confirm and hand back

Verify and summarise:

```bash
cadence schedule status
```

Tell the user: the project is paused and unscheduled, what was left in place
(config path, state dir unless purged), and that re-onboarding later is one
command: `cadence onboard "<PROJECT_DIR>"`.
