# Final Review Fix Report

## Summary

The branch now carries the active-config wording cleanup for the multi-profile runtime first slice:

- `bin/cadence` help now refers to the active config instead of bare `.env`.
- `.env.example` now tells operators to copy into the active config.
- `engine/scripts/schedule.sh`, `engine/scripts/autonomous.sh`, and the shared launchd guard wording now use active-config / project-local `cadence/.env` language.
- The shell loader preserves the resolved `CADENCE_CONFIG` path across sourcing.

The launchd write paths remain fail-closed for project-local configs. `schedule show` and `autonomous status` stay read-only.

## RED / GREEN

### RED

I did not capture a fresh red state from this checkout because the core guards and resolved-config preservation were already present in the live tree when I verified it. The relevant regression tests were already green on first run:

- `tests.test_front_door.TestFrontDoor.test_selected_config_path_survives_values_inside_config`
- `tests.test_schedule.TestScheduleApplyScript.test_apply_rejects_project_local_config_until_launchd_supports_it`
- `tests.test_autonomous_script.TestAutonomousScript.test_on_rejects_project_local_config_until_launchd_supports_it`

### GREEN

Verified on the current tree:

- `cd engine && python3 -m unittest discover -s tests -p 'test_*.py'`
  - Result: `Ran 166 tests in 10.026s OK`
- `shellcheck bin/cadence engine/scripts/*.sh engine/lib/lib-env.sh`
  - Result: clean
- `bash -n bin/cadence engine/scripts/*.sh engine/lib/lib-env.sh && python3 -m py_compile engine/lib/cadence_env.py engine/providers/cli.py`
  - Result: clean
- Manual smoke:
  - `bash engine/scripts/schedule.sh show` under a project-local `CADENCE_CONFIG`
  - `bash engine/scripts/autonomous.sh status` under a project-local `CADENCE_CONFIG`
  - Result: both completed successfully

## Files Changed

- `.env.example`
- `bin/cadence`
- `engine/lib/lib-env.sh`
- `engine/scripts/autonomous.sh`
- `engine/scripts/schedule.sh`
- `engine/tests/test_autonomous_script.py`
- `engine/tests/test_schedule.py`

## Self-Review

- The launchd gating stays conservative: `schedule apply` and `autonomous on` both refuse project-local configs, while read-only status/show paths remain usable.
- The shell loader fix is minimal and keeps the resolved active config stable after sourcing.
- The wording cleanup is scoped to operator-facing text only; no new runtime behavior was added.

## Concerns

- The branch tip already contained the core behavior fix when I verified it, so the visible diff here is mostly wording cleanup plus the report artifact.
- `gitaddall` is brittle in this checkout because ignored root files are present; I staged the report separately rather than widening scope.
