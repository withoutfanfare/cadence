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

## Fix/Verification

### RED capture (relative `--config` failure before canonicalization)

```bash
cd engine && python3 -m unittest tests.test_front_door
```

Output:

```text
F...
======================================================================
FAIL: test_config_option_selects_project_config_before_command (tests.test_front_door.TestFrontDoor.test_config_option_selects_project_config_before_command)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/Users/dannyharding/Development/Code/Project/cadence/engine/tests/test_front_door.py", line 111, in test_config_option_selects_project_config_before_command
    self.assertIn("%s|%s" % (state, os.path.realpath(os.path.join(root, relative_config_path))), result.stdout)
    ~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: '/var/folders/6m/0mz983295hxb9phsbnbg_9mr0000gn/T/tmp5xj9t6j1/state|/var/folders/6m/0mz983295hxb9phsbnbg_9mr0000gn/T/tmp5xj9t6j1/cadence-engine/app/cadence/.env' not found in '/var/folders/6m/0mz983295hxb9phsbnbg_9mr0000gn/T/tmp5xj9t6j1/state|app/cadence/.env\n'

----------------------------------------------------------------------
Ran 4 tests in 0.141s

FAILED (failures=1)
```

### GREEN capture (patched)

```bash
cd engine && python3 -m unittest tests.test_front_door
```

Output:

```text
....
----------------------------------------------------------------------
Ran 4 tests in 0.141s

OK
```

```bash
cd engine && python3 -m unittest discover -s tests -p 'test_*.py'
```

Output:

```text
...............................................................................................................................................................
----------------------------------------------------------------------
Ran 159 tests in 12.078s

OK
```

```bash
cd /Users/dannyharding/Development/Code/Project/cadence && shellcheck bin/cadence engine/scripts/*.sh engine/lib/lib-env.sh
```

Output:

```text
(no output)
```
