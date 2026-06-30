import importlib.util
import os
import unittest
from datetime import datetime, timezone

# Load under a unique name: engine/queue/cli.py and engine/throughput/cli.py
# share the basename `cli`, so a plain `import cli` would collide across test
# modules. Loading by explicit path keeps them isolated.
_spec = importlib.util.spec_from_file_location(
    "throughput_cli", os.path.join(os.path.dirname(__file__), "..", "throughput", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

UTC = timezone.utc


class TestAggregate(unittest.TestCase):
    def test_sums_produced_per_stage(self):
        recs = [
            {"stage": "triage", "ts": "2026-06-29T10:00:00Z", "triaged": 3,
             "dupe_candidates": 2, "errors": 0},
            {"loop": "build", "ts": "2026-06-29T11:00:00Z", "built": 1,
             "pr_numbers": [5, 6], "errors": 1},
        ]
        agg = cli.aggregate(recs)  # since None -> all
        self.assertEqual(agg["stages"]["triage"]["triaged"], 3)
        self.assertEqual(agg["stages"]["triage"]["dupe_candidates"], 2)
        self.assertEqual(agg["stages"]["triage"]["runs"], 1)
        self.assertEqual(agg["stages"]["build"]["built"], 1)
        self.assertEqual(agg["stages"]["build"]["prs"], 2)
        self.assertEqual(agg["stages"]["build"]["errors"], 1)

    def test_window_excludes_old_and_counts_undated(self):
        since = datetime(2026, 6, 29, tzinfo=UTC)
        recs = [
            {"stage": "triage", "ts": "2026-06-29T10:00:00Z", "triaged": 1},  # in window
            {"stage": "triage", "ts": "2026-06-01T10:00:00Z", "triaged": 9},  # too old
            {"loop": "spec", "paused": True, "reason": "x"},                  # undated
        ]
        agg = cli.aggregate(recs, since=since)
        self.assertEqual(agg["stages"]["triage"]["triaged"], 1)
        self.assertEqual(agg["stages"]["triage"]["runs"], 1)
        self.assertEqual(agg["undated"], 1)

    def test_paused_counted_when_dated(self):
        recs = [{"loop": "spec", "ts": "2026-06-29T10:00:00Z", "paused": True}]
        agg = cli.aggregate(recs)
        self.assertEqual(agg["stages"]["spec"]["paused"], 1)

    def test_unknown_stage_ignored(self):
        agg = cli.aggregate([{"stage": "nonsense", "ts": "2026-06-29T10:00:00Z"}])
        self.assertTrue(all(agg["stages"][s]["runs"] == 0 for s in cli.STAGES))


class TestRender(unittest.TestCase):
    def test_shows_produced_and_pr_count(self):
        agg = cli.aggregate([
            {"stage": "triage", "ts": "2026-06-29T10:00:00Z", "triaged": 3, "dupe_candidates": 2},
            {"loop": "build", "ts": "2026-06-29T11:00:00Z", "built": 1, "pr_numbers": [5]},
        ])
        out = cli.render(agg, 7)
        self.assertIn("3 triaged", out)
        self.assertIn("2 dupes", out)
        self.assertIn("1 built", out)
        self.assertIn("1 PRs", out)
        self.assertIn("last 7 days", out)

    def test_empty_stage_shows_dash(self):
        out = cli.render(cli.aggregate([]), 7)
        self.assertIn("—", out)

    def test_undated_footer(self):
        agg = cli.aggregate(
            [{"loop": "spec", "paused": True}], since=datetime(2026, 6, 1, tzinfo=UTC))
        self.assertIn("undated run(s) skipped", cli.render(agg, 7))


if __name__ == "__main__":
    unittest.main()
