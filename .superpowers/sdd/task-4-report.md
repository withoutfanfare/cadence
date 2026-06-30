# Task 4 Report: Provider-Neutral Folded Reviewer

## What I implemented

Added `engine/scripts/run-reviewer.sh` as a provider-neutral folded-review adapter. It accepts
`<provider> <model> <workdir> <review-brief-file>`, validates inputs, applies the review timeout
from `REVIEW_TIMEOUT` with a default of `1800`, and dispatches the provider with the review brief
contents while preserving caller `PATH` resolution.

Added `engine/tests/test_run_reviewer.py` to cover the same-provider contract path used by the
task brief.

Updated the build, revise, and advance loop prompts to route folded review through
`run-reviewer.sh` instead of the old `Task` / `code-reviewer` wording.

## TDD RED / GREEN evidence

Red:

```bash
cd engine && python3 -m unittest tests.test_run_reviewer
```

Relevant output:

```text
FAIL: test_reviewer_uses_same_provider_contract
AssertionError: 127 != 0 : bash: .../engine/scripts/run-reviewer.sh: No such file or directory
```

Green:

```bash
cd engine && python3 -m unittest tests.test_prompt_contracts tests.test_run_reviewer
bash -n engine/scripts/run-reviewer.sh
```

Relevant output:

```text
..
----------------------------------------------------------------------
Ran 2 tests in 0.217s

OK
```

`bash -n` produced no output.

## Tests run and results

- `cd engine && python3 -m unittest tests.test_run_reviewer` - passed after implementation
- `cd engine && python3 -m unittest tests.test_prompt_contracts tests.test_run_reviewer` - passed
- `bash -n engine/scripts/run-reviewer.sh` - passed

## Files changed

- `engine/scripts/run-reviewer.sh`
- `engine/tests/test_run_reviewer.py`
- `skills/cadence-loop-build/SKILL.md`
- `skills/cadence-loop-revise/SKILL.md`
- `skills/cadence-loop-advance/SKILL.md`

## Self-review findings or concerns

- No functional concerns from the scoped checks.
- `run-reviewer.sh` dispatches providers directly instead of delegating to `run-orchestrator.sh` so the test harness's injected provider on `PATH` is honoured.
