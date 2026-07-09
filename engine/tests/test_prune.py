import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(__file__), *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load("cadence_prune_cli", "..", "prune", "cli.py")


class TestPrune(unittest.TestCase):
    def test_prunes_old_run_history_and_keeps_recent_or_unparseable_records(self):
        with tempfile.TemporaryDirectory() as state:
            runs = os.path.join(state, "runs")
            logs = os.path.join(state, "logs")
            os.makedirs(runs)
            os.makedirs(logs)

            for name in ("2026-06-01.md", "2026-07-05.md", "notes.txt"):
                with open(os.path.join(runs, name), "w", encoding="utf-8") as f:
                    f.write(name)

            old_log = os.path.join(logs, "old.log")
            new_log = os.path.join(logs, "new.log")
            for path in (old_log, new_log):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(os.path.basename(path))
            os.utime(old_log, (100, 100))
            new_log_ts = datetime(2026, 7, 7, tzinfo=timezone.utc).timestamp()
            os.utime(new_log, (new_log_ts, new_log_ts))

            with open(os.path.join(runs, "runs.jsonl"), "w", encoding="utf-8") as f:
                f.write(json.dumps({"ts": "2026-06-01T00:00:00Z", "stage": "old"}) + "\n")
                f.write(json.dumps({"ts": "2026-07-05T00:00:00Z", "stage": "new"}) + "\n")
                f.write(json.dumps({"stage": "undated"}) + "\n")
                f.write("not json\n")

            with open(os.path.join(runs, "activity.log"), "w", encoding="utf-8") as f:
                f.write("[2026-06-01T00:00:00Z] old\n")
                f.write("[2026-07-05T00:00:00Z] new\n")
                f.write("undated\n")

            summary = cli.prune(
                state, days=30, now=datetime(2026, 7, 9, tzinfo=timezone.utc))

            self.assertEqual(summary["daily_files"], 1)
            self.assertEqual(summary["log_files"], 1)
            self.assertEqual(summary["jsonl_records"], 1)
            self.assertEqual(summary["activity_lines"], 1)
            self.assertFalse(os.path.exists(os.path.join(runs, "2026-06-01.md")))
            self.assertTrue(os.path.exists(os.path.join(runs, "2026-07-05.md")))
            self.assertTrue(os.path.exists(os.path.join(runs, "notes.txt")))
            self.assertFalse(os.path.exists(old_log))
            self.assertTrue(os.path.exists(new_log))

            with open(os.path.join(runs, "runs.jsonl"), encoding="utf-8") as f:
                ledger = f.read()
            self.assertNotIn('"stage": "old"', ledger)
            self.assertIn('"stage": "new"', ledger)
            self.assertIn('"stage": "undated"', ledger)
            self.assertIn("not json", ledger)

            with open(os.path.join(runs, "activity.log"), encoding="utf-8") as f:
                activity = f.read()
            self.assertNotIn("old", activity)
            self.assertIn("new", activity)
            self.assertIn("undated", activity)

    def test_dry_run_reports_without_deleting_or_rewriting(self):
        with tempfile.TemporaryDirectory() as state:
            runs = os.path.join(state, "runs")
            os.makedirs(runs)
            old = os.path.join(runs, "2026-06-01.md")
            with open(old, "w", encoding="utf-8") as f:
                f.write("old")
            ledger = os.path.join(runs, "runs.jsonl")
            with open(ledger, "w", encoding="utf-8") as f:
                f.write(json.dumps({"ts": "2026-06-01T00:00:00Z"}) + "\n")

            summary = cli.prune(
                state, days=30, dry_run=True,
                now=datetime(2026, 7, 9, tzinfo=timezone.utc))

            self.assertEqual(summary["daily_files"], 1)
            self.assertEqual(summary["jsonl_records"], 1)
            self.assertTrue(os.path.exists(old))
            with open(ledger, encoding="utf-8") as f:
                self.assertIn("2026-06-01", f.read())


if __name__ == "__main__":
    unittest.main()
