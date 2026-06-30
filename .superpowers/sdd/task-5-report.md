# Task 5 Report: Doctor and Documentation

## What I implemented

- Added provider-aware checks to `engine/scripts/doctor.sh` for `ORCHESTRATOR_TRIAGE`, `ORCHESTRATOR_SPEC`, `ORCHESTRATOR_BUILD`, `ORCHESTRATOR_REVISE`, `ORCHESTRATOR_ADVANCE`, and `REVIEW_PROVIDER`.
- Kept the existing implementer check for `BUILD_IMPLEMENTER`.
- Added an offline unittest file, `engine/tests/test_doctor.py`, that exercises the new provider validation without hitting live services.
- Updated the public docs to describe provider-neutral orchestration, including README requirements, configuration variables, architecture flow, implementer dispatch, install troubleshooting, and the AI provider spike acceptance note.

## TDD evidence

RED:

```bash
cd engine && python3 -m unittest tests.test_doctor
```

Relevant failure output:

```text
AssertionError: "triage orchestrator provider 'codex' found" not found in ...
AssertionError: 0 == 0
```

GREEN:

```bash
cd engine && python3 -m unittest tests.test_doctor
```

Result:

```text
..
----------------------------------------------------------------------
Ran 2 tests in 0.186s

OK
```

## Tests run and results

- `cd engine && python3 -m unittest tests.test_doctor tests.test_front_door tests.test_run_orchestrator tests.test_run_reviewer`
  - Passed: 11 tests
- `bash -n engine/scripts/doctor.sh`
  - Passed
- `shellcheck engine/scripts/doctor.sh`
  - Passed
- `git diff --check`
  - Passed

## Files changed

- `/Users/dannyharding/Development/Code/Project/cadence/engine/scripts/doctor.sh`
- `/Users/dannyharding/Development/Code/Project/cadence/engine/tests/test_doctor.py`
- `/Users/dannyharding/Development/Code/Project/cadence/README.md`
- `/Users/dannyharding/Development/Code/Project/cadence/docs/ARCHITECTURE.md`
- `/Users/dannyharding/Development/Code/Project/cadence/docs/CONFIGURATION.md`
- `/Users/dannyharding/Development/Code/Project/cadence/docs/IMPLEMENTERS.md`
- `/Users/dannyharding/Development/Code/Project/cadence/docs/INSTALL.md`
- `/Users/dannyharding/Development/Code/Project/cadence/docs/spikes/2026-06-30-ai-provider-abstraction.md`

## Self-review findings or concerns

- No functional concerns remain from the checks I ran.
- I added a new `How a run executes` subsection in `docs/ARCHITECTURE.md` because that section was not present in the current file and the requested step-3 wording needed a home.

## Review fix

- Reworked `docs/spikes/2026-06-30-ai-provider-abstraction.md` so it reads as historical spike context plus the accepted provider-neutral path at current HEAD, with remaining caveats framed as follow-up work rather than active blockers.
- Updated `docs/INSTALL.md` to remove the Claude-only prerequisite and stale `claude not on PATH` troubleshooting entry in favour of provider-neutral orchestration checks.
- Updated `docs/CONFIGURATION.md` so the Autonomous Mode table uses `ORCHESTRATOR_ADVANCE`, `REVIEW_PROVIDER`, and `REVIEW_MODEL`, and the minimal profile example now shows `ORCHESTRATOR_*` values with `MODEL_*` clearly labelled as legacy fallback aliases.
- Verification:
  - `git diff --check`
  - `rg -n "claude not on PATH|code-reviewer|MODEL_ADVANCE|Claude CLI for orchestration|cannot be swapped|invokes Claude directly" docs/INSTALL.md docs/CONFIGURATION.md docs/spikes/2026-06-30-ai-provider-abstraction.md`
  - Remaining `code-reviewer` and `MODEL_ADVANCE` hits are historical or legacy-labelled, not current guidance.
