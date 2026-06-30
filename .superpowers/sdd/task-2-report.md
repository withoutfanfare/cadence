# Task 2 Report — Orchestrator Provider Adapter

## What I implemented
- Added `engine/scripts/run-orchestrator.sh` with provider dispatch for `claude`, `codex`, `kimi`, and `opencode`, plus timeout handling, argument validation, and standardised `run-orchestrator:` stderr diagnostics.
- Added adapter tests in `engine/tests/test_run_orchestrator.py` using a temporary PATH-injected binary directory.
- Added orchestrator/review env defaults in `engine/lib/lib-env.sh`:
  - `ORCHESTRATOR_*` provider:model pair defaults
  - `REVIEW_PROVIDER` and `REVIEW_MODEL`
- Updated `.env.example` with orchestrator/review config block and retained legacy model aliases as fallback values.

## TDD RED → GREEN evidence
- RED (`run-orchestrator` missing):
  - Command: `cd engine && python3 -m unittest tests.test_run_orchestrator`
  - Relevant output:
    - `FFFF`
    - `AssertionError: 127 != 0 : bash: .../engine/scripts/run-orchestrator.sh: No such file or directory`
- GREEN (after implementing script + test adjustment):
  - Command: `cd engine && python3 -m unittest tests.test_run_orchestrator`
  - Relevant output:
    - `....`
    - `Ran 4 tests in 0.407s`
    - `OK`

## Tests run and results
- `cd engine && python3 -m unittest tests.test_run_orchestrator` → PASS
- `bash -n engine/scripts/run-orchestrator.sh engine/lib/lib-env.sh` → PASS (`shellcheck:pass` in same command chain)

## Files changed
- `.env.example`
- `engine/lib/lib-env.sh`
- `engine/scripts/run-orchestrator.sh` (created)
- `engine/tests/test_run_orchestrator.py` (created)

## Self-review findings / concerns
- Concern: the test stub in `test_run_orchestrator.py` needed `${10}` in a helper print to correctly read positional arg 10 under `sh`; without this, bash positional expansion yields `arg1`+`0`. This was fixed locally in the test to make the codex invocation assertion reliable.

## Review fix
- `engine/scripts/run-orchestrator.sh`: restored controlled `PATH` initialization to omit inherited `PATH` leakage:
  - from: `export PATH="${_pp:+$_pp:}${PATH:+$PATH:}$_base_path"`
  - to: `export PATH="${_pp:+$_pp:}$_base_path"`
- `engine/tests/test_run_orchestrator.py`: switched provider fake binary injection to `RUNNER_PATH_PREPEND` and kept test fixture `PATH` untouched.
- Added focused regression test `test_provider_nonzero_exit_code_propagates` (`fake provider exits 42`) and assert script returns `42`.
- Command: `cd engine && python3 -m unittest tests.test_run_orchestrator` → PASS (`Ran 5 tests` / `OK`)
- Command: `bash -n engine/scripts/run-orchestrator.sh engine/lib/lib-env.sh` → PASS (syntax clean)

## Second review fix
- `engine/scripts/run-orchestrator.sh` now uses a Python-stdlib timeout wrapper via `python3` instead of GNU `timeout`, preserving provider exit code passthrough and returning `124` on timeout.
- `engine/tests/test_run_orchestrator.py`: updated `_run()` to inject timeout duration and added `test_timeout_returns_exit_code_124` (fake `claude` sleep command) to assert timed-out behavior and stderr timeout diagnostic.
- Command: `cd engine && python3 -m unittest tests.test_run_orchestrator` → PASS (`Ran 6 tests` / `OK`, including timeout exit-code regression)
- Command: `bash -n engine/scripts/run-orchestrator.sh engine/lib/lib-env.sh` → PASS
