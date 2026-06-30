# Cadence Documentation

This directory is the public manual for installing, configuring, and operating
Cadence.

## Start Here

1. [Installation](INSTALL.md) - clone the repo, install the `cadence` command,
   fill `cadence/.env`, create Linear labels, run `doctor`, smoke-test the setup,
   and schedule the loops.
2. [Configuration](CONFIGURATION.md) - reference for every config setting.
3. [AI Provider Roles](PROVIDERS.md) - how to inspect and switch orchestrators,
   reviewers, and build implementers without confusing legacy `MODEL_*` aliases.
4. [Operating Cadence](OPERATING.md) - daily commands, logs, digests, pausing,
   autonomous monitoring, helper commands, and common troubleshooting.

## Reference

- [Architecture](ARCHITECTURE.md) - control model, human gates, runtime state,
  pause guard, memory convention, and verification gates.
- [Agent Labels](LABELS.md) - the Linear label vocabulary used as the state
  machine.
- [Bulk Label](BULK-LABEL.md) - cheatsheet for `cadence linear bulk-label`:
  batch label changes with scope guard, dry-run, and confirmation.
- [Implementers](IMPLEMENTERS.md) - how the build loop delegates coding work to
  Claude, Kimi, OpenCode, or Codex.
- [AI Provider Roles](PROVIDERS.md) - evergreen provider role map and command
  reference for `cadence providers`.

## Project Files

- [`../README.md`](../README.md) - short public overview and quick install path.
- [`../.env.example`](../.env.example) - copy this to
  `<project repo>/cadence/.env` and fill in your local profile.
- [`../CHANGELOG.md`](../CHANGELOG.md) - notable changes.

The macOS launchd jobs are generated from the `SCHED_*` schedule in the active
config file by `cadence schedule apply` — see
[Configuration](CONFIGURATION.md#schedule).

## Recommended Reading Order

For a first install, read:

```text
README.md -> docs/INSTALL.md -> docs/CONFIGURATION.md -> docs/PROVIDERS.md -> docs/OPERATING.md
```

For maintainers changing the engine, read:

```text
docs/ARCHITECTURE.md -> docs/LABELS.md -> docs/IMPLEMENTERS.md
```
