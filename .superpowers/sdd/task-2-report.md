# Task 2 Report: Shell Config Resolution and Front-Door `--config`

## Scope

Implemented the Bash/front-door side of config precedence only.

Files changed:

- `bin/cadence`
- `engine/lib/lib-env.sh`
- `engine/tests/test_front_door.py`

## TDD Evidence

### RED

Added two front-door regression tests first:

- `test_config_option_selects_project_config_before_command`
- `test_project_cadence_env_is_auto_detected_from_cwd`

Verified the failures with:

```bash
cd engine && python3 -m unittest tests.test_front_door
```

Observed failures:

- `--config` was still treated as an unknown command.
- `status` from a project cwd still loaded `$HOME/.cadence/.env` instead of the project-local `cadence/.env`.

### GREEN

Implemented the minimal Bash changes:

- `bin/cadence` now accepts `--config <path>` before sourcing `engine/lib/lib-env.sh`.
- `engine/lib/lib-env.sh` now resolves `CADENCE_CONFIG` in this order:
  1. explicit `CADENCE_CONFIG`
  2. `$PWD/cadence/.env`
  3. `$CADENCE_HOME/.env`
- `CADENCE_CONFIG` is exported before the file is sourced.

Verified the fix with:

```bash
cd engine && python3 -m unittest tests.test_front_door
bash -n bin/cadence engine/lib/lib-env.sh
```

Both commands passed.

## Self-Review

- Kept the Bash change small and limited to the front door plus shared env loader.
- Did not add `--profile`, task-file backend logic, or launchd label changes.
- Left Python resolver code untouched.
- Kept the existing help text update to the new CLI shape.

## Concern

On this macOS host, project-cwd path resolution comes through `/private/var/...` in the shell while the temp path fixture is created as `/var/...`. The test now compares against `os.path.realpath(config_path)` for the cwd-autodetect case so the assertion matches the shell’s physical path output.
