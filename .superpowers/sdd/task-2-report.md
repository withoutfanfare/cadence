# Task 2 Report: Surface `stage` on `tasks list` and add `tasks path`

## Summary

Wired the pure `stage_of(labels)` helper (from Task 1, `engine/lib/stages.py`) into
the local task-file adapter `engine/tasks/cli.py`:

1. Every item returned by `cadence tasks list` now carries a `stage` object
   (`name`, `gate`, `hold`, `exception`, `advance`).
2. Added a new `path` verb: `cadence tasks path` prints the resolved absolute
   `TASK_FILE` (via the existing `task_path(env)` helper) as plain text, not JSON.

Implemented exactly as specified in the brief, via TDD.

## TDD evidence

### RED — tests added first, confirmed failing

Added `test_list_includes_canonical_stage` and `test_path_prints_resolved_task_file`
to `engine/tests/test_tasks_cli.py` (verbatim from the brief), then ran:

```text
cd engine && python3 -m unittest tests.test_tasks_cli -v
```

Result: 2 failures as predicted by the brief.

```bash
test_list_includes_canonical_stage ... ERROR
...
KeyError: 'stage'

test_path_prints_resolved_task_file ... FAIL
...
AssertionError: 2 != 0 : usage: cadence tasks [-h] {validate,list,get,update} ...
cadence tasks: error: argument cmd: invalid choice: 'path' (choose from 'validate', 'list', 'get', 'update')

Ran 12 tests in 0.476s
FAILED (failures=1, errors=1)
```

All other 10 pre-existing tests still passed, confirming the two new tests were
the only failures (no accidental breakage from adding the test methods alone).

### GREEN — implementation, tests pass

Implemented in `engine/tasks/cli.py`:

- Import wiring (below `import sys`, above `HEADER_RE`, mirrors `engine/linear/cli.py`):
  ```python
  sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
  from stages import stage_of  # noqa: E402
  ```
- `cmd_list` now attaches `task["stage"] = stage_of(task.get("labels") or [])`
  to each task before returning.
- `build_parser()` gained `sub.add_parser("path")`.
- `main()` gained a branch before the `validate` check:
  ```python
  if args.cmd == "path":
      print(task_path(env))
      return 0
  ```

Ran:
```text
cd engine && python3 -m unittest tests.test_tasks_cli -v
```

Result: all 12 tests pass.

```bash
Ran 12 tests in 0.457s
OK
```

### Full suite

```text
cd engine && python3 -m unittest discover -s tests -p 'test_*.py'
```

Result: all 239 tests pass (`OK`). Some pre-existing `ResourceWarning`s and
simulated Linear retry log lines appear in output — these come from unrelated,
pre-existing tests (retry/backoff and temp-file cleanup tests) and are not
failures.

## Files changed

- `engine/tasks/cli.py` — import wiring, `stage` field in `cmd_list`, `path` verb
  in `build_parser()` and `main()`. +9 lines.
- `engine/tests/test_tasks_cli.py` — two new test methods, verbatim from the
  brief. +23 lines.

Diff matches the brief's Step 3–5 code exactly; no unrelated lines touched.

## Self-review findings

- Diff is minimal and surgical — only the specified additions, no refactoring
  of adjacent code.
- `path` subparser was placed directly after `validate` in `build_parser()`
  ("next to the others" per the brief) — arbitrary but reasonable ordering,
  does not affect behaviour (argparse subparser registration order only
  affects `--help` listing order, not correctness).
- The `path` branch in `main()` is placed before the `validate` branch inside
  the `try:` block, exactly as the brief specifies, so it prints a plain path
  string (not JSON) and returns before the JSON-printing tail of `main()`.
- Confirmed `task_path(env)` was already implemented and unchanged — reused
  as-is, no duplication.
- No project ids/paths/facts introduced — engine stays profile-free.
- Stdlib only; no new imports beyond the existing `stages` module.
- British English: no new prose added (code/tests only), so nothing to check
  there.
- `gitaddall` printed a "paths are ignored" warning during staging (unrelated
  ignored files like `CLAUDE.md`, `.serena`, `AGENTS.md` at the repo root) —
  this is expected alias behaviour (it deliberately excludes those paths from
  staging and then reports the exclusion as an "ignored" warning) and did not
  affect staging of the two target files. The commit itself was scoped to
  exactly `engine/tasks/cli.py` and `engine/tests/test_tasks_cli.py` via the
  explicit pathspec on `git commit`, per the brief.
- Note: this report file previously held content from an unrelated, earlier
  "Task 2" (Bash front-door `--config` resolution) from a prior SDD run in
  this same directory. It has been overwritten with this task's report, per
  the instruction to write the report to this exact path.

## Concerns

None. Implementation matches the brief exactly, tests are green, full suite
passes, working tree is clean after the commit.

## Commit

`e033e80` — `feat(engine): tasks list emits canonical stage; add tasks path verb`
(2 files changed, 32 insertions, 0 deletions)
