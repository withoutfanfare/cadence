import importlib.util
import json
import os
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "conduct_cli", os.path.join(os.path.dirname(__file__), "..", "conduct", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

AC = "## Acceptance criteria\n- it works\n"


def issue(ident, labels, **kw):
    d = {"identifier": ident, "title": ident, "labels": list(labels),
         "description": AC, "state_type": "started", "priority": 2,
         "cycle": None, "createdAt": "2026-06-01T00:00:00Z"}
    d.update(kw)
    return d


class TestEligible(unittest.TestCase):
    def test_keeps_ready_triaged_with_criteria(self):
        out = cli.eligible([issue("A-1", ["agent:triaged"])])
        self.assertEqual([i["identifier"] for i in out], ["A-1"])

    def test_drops_without_criteria(self):
        out = cli.eligible([issue("A-2", ["agent:triaged"], description="no criteria here")])
        self.assertEqual(out, [])

    def test_drops_held_superseded_needshuman_and_already_auto(self):
        for lab in ("agent:hold", "agent:superseded", "agent:needs-human",
                    "agent:needs-attention", "agent:auto"):
            self.assertEqual(cli.eligible([issue("A", ["agent:triaged", lab])]), [])

    def test_drops_not_triaged(self):
        self.assertEqual(cli.eligible([issue("A-3", ["Bug"])]), [])

    def test_drops_roadmap_proposals_until_a_human_accepts(self):
        self.assertEqual(
            cli.eligible([issue("A-9", ["agent:triaged", "agent:proposed"])]), [])

    def test_drops_completed_or_canceled_state(self):
        self.assertEqual(cli.eligible([issue("A-4", ["agent:triaged"], state_type="completed")]), [])
        self.assertEqual(cli.eligible([issue("A-5", ["agent:triaged"], state_type="canceled")]), [])


class TestRank(unittest.TestCase):
    def test_priority_dominates_then_cycle_then_age(self):
        a = issue("A", ["agent:triaged"], priority=1, createdAt="2026-06-02T00:00:00Z")  # urgent
        b = issue("B", ["agent:triaged"], priority=4, createdAt="2026-06-03T00:00:00Z")  # low
        c = issue("C", ["agent:triaged"], priority=4, cycle=7, createdAt="2026-06-05T00:00:00Z")  # low, in-cycle
        out = [i["identifier"] for i in cli.rank([a, b, c], active_cycle=7)]
        # priority desc dominates: urgent A first; among the two low (P4), in-cycle C beats B
        self.assertEqual(out, ["A", "C", "B"])

    def test_none_priority_sorts_after_set_priorities(self):
        p1 = issue("P1", ["agent:triaged"], priority=1)   # urgent
        nun = issue("N", ["agent:triaged"], priority=0)   # none
        out = [i["identifier"] for i in cli.rank([nun, p1], active_cycle=None)]
        self.assertEqual(out, ["P1", "N"])

    def test_oldest_first_within_same_priority_and_cycle(self):
        older = issue("OLD", ["agent:triaged"], priority=3, createdAt="2026-06-01T00:00:00Z")
        newer = issue("NEW", ["agent:triaged"], priority=3, createdAt="2026-06-09T00:00:00Z")
        out = [i["identifier"] for i in cli.rank([newer, older], active_cycle=None)]
        self.assertEqual(out, ["OLD", "NEW"])


class TestIsBlocked(unittest.TestCase):
    def test_blocked_by_unfinished_blocker(self):
        detail = {"inverseRelations": [
            {"type": "blocks", "issue": {"identifier": "B-1", "state": {"type": "started"}}}]}
        self.assertTrue(cli.is_blocked(detail))

    def test_not_blocked_when_blocker_done(self):
        detail = {"inverseRelations": [
            {"type": "blocks", "issue": {"identifier": "B-1", "state": {"type": "completed"}}}]}
        self.assertFalse(cli.is_blocked(detail))

    def test_non_blocks_relations_ignored(self):
        detail = {"inverseRelations": [
            {"type": "related", "issue": {"identifier": "B-1", "state": {"type": "started"}}}]}
        self.assertFalse(cli.is_blocked(detail))

    def test_no_relations_not_blocked(self):
        self.assertFalse(cli.is_blocked({}))


class TestConduct(unittest.TestCase):
    def test_skips_parent_issue_with_children_before_tagging(self):
        calls = []

        def fake_linear(*args):
            calls.append(args)
            if args[:2] == ("issues-list", "--assignee"):
                return [issue("PARENT", ["agent:triaged"])]
            if args == ("cycles-list",):
                return []
            if args == ("issue-get", "PARENT"):
                return {"children": [{"identifier": "CHILD"}], "inverseRelations": []}
            if args[:2] == ("issue-update", "PARENT"):
                raise AssertionError("parent issue should not be tagged")
            raise AssertionError(args)

        old = cli._linear
        try:
            cli._linear = fake_linear
            # Point at a temp state dir so the pass does not read a real
            # ~/.cadence/runs/PAUSED flag on the developer's machine.
            with tempfile.TemporaryDirectory() as tmp:
                out = cli.conduct(
                    {"AUTONOMOUS": "on", "CONDUCT_WIP": "1", "CADENCE_STATE_DIR": tmp},
                    dry_run=False,
                )
        finally:
            cli._linear = old

        self.assertEqual(out["tagged"], [])
        self.assertEqual(out["skipped_parent"], ["PARENT"])

    def test_file_backend_tags_ready_task_without_linear(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_file = os.path.join(tmp, "tasks.md")
            with open(task_file, "w", encoding="utf-8") as f:
                f.write("""# Cadence Tasks

## TASK-1: Ready
status: open
labels: agent:triaged

## Acceptance criteria
- it works
""")

            old_linear = cli._linear
            try:
                cli._linear = lambda *args: (_ for _ in ()).throw(
                    AssertionError("file backend should not use Linear"))
                out = cli.conduct({
                    "AUTONOMOUS": "on",
                    "CONDUCT_WIP": "1",
                    "TASK_BACKEND": "file",
                    "TASK_FILE": task_file,
                    "CADENCE_STATE_DIR": tmp,
                }, dry_run=False)
            finally:
                cli._linear = old_linear

            self.assertEqual(out["tagged"], ["TASK-1"])
            with open(task_file, encoding="utf-8") as f:
                self.assertIn("labels: agent:triaged, agent:auto", f.read())

    def test_file_backend_skips_completed_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_file = os.path.join(tmp, "tasks.md")
            with open(task_file, "w", encoding="utf-8") as f:
                f.write("""# Cadence Tasks

## TASK-1: Done
status: completed
labels: agent:triaged

## Acceptance criteria
- it works
""")

            out = cli.conduct({
                "AUTONOMOUS": "on",
                "CONDUCT_WIP": "1",
                "TASK_BACKEND": "file",
                "TASK_FILE": task_file,
                "CADENCE_STATE_DIR": tmp,
            }, dry_run=False)

            self.assertEqual(out["tagged"], [])
            with open(task_file, encoding="utf-8") as f:
                self.assertNotIn("agent:auto", f.read())


class TestLedger(unittest.TestCase):
    def test_append_ledger_records_activity_and_machine_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            summary = {"loop": "conduct", "dry_run": True,
                       "tagged": ["STU-1"], "skipped_blocked": ["STU-2"],
                       "skipped_parent": ["STU-3"]}

            cli.append_ledger(summary, env, ts="2026-06-30T10:00:00Z")

            with open(os.path.join(tmp, "runs", "runs.jsonl"), encoding="utf-8") as f:
                ledger = json.loads(f.read())
            self.assertEqual(ledger["loop"], "conduct")
            self.assertEqual(ledger["ts"], "2026-06-30T10:00:00Z")
            self.assertEqual(ledger["tagged"], ["STU-1"])

            with open(os.path.join(tmp, "runs", "activity.log"), encoding="utf-8") as f:
                activity = f.read()
            self.assertIn("conduct", activity)
            self.assertIn("1 tagged", activity)
            self.assertIn("1 blocked", activity)
            self.assertIn("1 parent", activity)

            with open(os.path.join(tmp, "logs", "conduct.log"), encoding="utf-8") as f:
                log = f.read()
            self.assertIn("conduct — 1 tagged, 1 blocked, 1 parent", log)

            with open(os.path.join(tmp, "runs", "2026-06-30.md"), encoding="utf-8") as f:
                digest = f.read()
            self.assertIn("## conduct · dry-run · 2026-06-30T10:00:00Z", digest)
            self.assertIn("1 tagged, 1 blocked, 1 parent", digest)

    def test_main_records_failed_conduct_when_adapter_exits(self):
        # An adapter sys.exit mid-run must still leave a FAILED trace in the ledger.
        with tempfile.TemporaryDirectory() as tmp:
            old_linear = cli._linear
            old_load = cli._cadence_env.load_env
            try:
                cli._cadence_env.load_env = lambda *a, **k: {
                    "CADENCE_STATE_DIR": tmp, "AUTONOMOUS": "on",
                    "TASK_BACKEND": "linear", "CONDUCT_WIP": "1",
                }

                def boom(*_args):
                    raise SystemExit(1)

                cli._linear = boom
                with self.assertRaises(SystemExit):
                    cli.main([])
            finally:
                cli._linear = old_linear
                cli._cadence_env.load_env = old_load

            # Check inside the with-block, before the temp dir is cleaned up.
            jsonl = os.path.join(tmp, "runs", "runs.jsonl")
            self.assertTrue(os.path.exists(jsonl), "a failed conduct must still write a ledger")
            record = json.loads(open(jsonl, encoding="utf-8").read().strip().splitlines()[-1])
            self.assertEqual(record["loop"], "conduct")
            self.assertIn("error", record)


if __name__ == "__main__":
    unittest.main()
