import importlib.util
import io
import os
import unittest

# engine/linear/cli.py shares the basename `cli` with other engine modules;
# load it under a unique name to avoid a sys.modules collision.
_spec = importlib.util.spec_from_file_location(
    "linear_cli", os.path.join(os.path.dirname(__file__), "..", "linear", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

ENV = {"LINEAR_TEAM_ID": "T", "LINEAR_PROJECT_ID": "P", "LINEAR_ASSIGNEE_ID": "A"}


class Args:
    def __init__(self, **kw):
        self.issues = kw.get("issues", [])
        self.where_label = kw.get("where_label")
        self.add_label = kw.get("add_label")
        self.remove_label = kw.get("remove_label")
        self.dry_run = kw.get("dry_run", False)
        self.yes = kw.get("yes", False)


def fake_post(scope_ok=True, where_nodes=None):
    """Return a (post, calls) pair. post answers each query by content."""
    calls = []

    def post(query, variables, env):
        calls.append((query, variables))
        if "issueLabels" in query:               # _LABELS_Q (resolve names -> ids)
            return {"issueLabels": {"nodes": [{"name": "agent:auto", "id": "L1"}]}}
        if "team { id } project" in query:        # _ISSUE_SCOPE_Q
            if not scope_ok:
                return {"issue": {"team": {"id": "OTHER"},
                                  "project": {"id": "P"}, "assignee": {"id": "A"}}}
            return {"issue": {"team": {"id": "T"},
                              "project": {"id": "P"}, "assignee": {"id": "A"}}}
        if "labels{ nodes{ id" in query:          # _ISSUE_GET_LABELS_Q
            return {"issue": {"labels": {"nodes": [{"id": "EXISTING", "name": "Bug"}]}}}
        if "issueUpdate" in query:                # _ISSUE_UPDATE_M
            return {"issueUpdate": {"success": True, "issue": {"id": "i"}}}
        if "issues(filter" in query:              # _ISSUES_Q (where-label)
            if "first" not in variables or "after" not in variables:
                raise cli.LinearError("missing pagination variables")
            return {"issues": {"nodes": where_nodes or []}}
        raise AssertionError("unexpected query: %s" % query[:40])

    return post, calls


class TestBulkLabel(unittest.TestCase):
    def test_nothing_to_do_raises(self):
        post, _ = fake_post()
        with self.assertRaises(cli.LinearError):
            cli.cmd_bulk_label(Args(issues=["STU-1"]), ENV, post=post)

    def test_ids_and_where_label_conflict_raises(self):
        post, _ = fake_post()
        with self.assertRaises(cli.LinearError):
            cli.cmd_bulk_label(
                Args(issues=["STU-1"], where_label="agent:triaged", add_label=["agent:auto"]),
                ENV, post=post)

    def test_dry_run_writes_nothing(self):
        post, calls = fake_post()
        out = cli.cmd_bulk_label(
            Args(issues=["STU-1", "STU-2"], add_label=["agent:auto"], dry_run=True),
            ENV, post=post)
        self.assertTrue(out["dry_run"])
        self.assertEqual(out["targets"], ["STU-1", "STU-2"])
        self.assertFalse(any("issueUpdate" in q for q, _ in calls))  # no mutation

    def test_abort_when_not_confirmed(self):
        post, calls = fake_post()
        cli.sys.stdin = io.StringIO("n\n")
        cli.sys.stderr = io.StringIO()  # swallow the confirmation prompt
        try:
            out = cli.cmd_bulk_label(
                Args(issues=["STU-1"], add_label=["agent:auto"]), ENV, post=post)
        finally:
            _sys = __import__("sys")
            cli.sys.stdin = _sys.__stdin__
            cli.sys.stderr = _sys.__stderr__
        self.assertTrue(out["aborted"])
        self.assertFalse(any("issueUpdate" in q for q, _ in calls))

    def test_yes_applies_and_merges_labels(self):
        post, calls = fake_post()
        out = cli.cmd_bulk_label(
            Args(issues=["STU-1"], add_label=["agent:auto"], yes=True), ENV, post=post)
        self.assertEqual(out["updated"], ["STU-1"])
        # the issueUpdate carries existing + the resolved new label id
        upd = [v for q, v in calls if "issueUpdate" in q][0]
        self.assertIn("EXISTING", upd["input"]["labelIds"])
        self.assertIn("L1", upd["input"]["labelIds"])

    def test_out_of_scope_issue_is_an_error_not_a_write(self):
        post, calls = fake_post(scope_ok=False)
        out = cli.cmd_bulk_label(
            Args(issues=["STU-9"], add_label=["agent:auto"], yes=True), ENV, post=post)
        self.assertEqual(out["updated"], [])
        self.assertEqual(len(out["errors"]), 1)
        self.assertFalse(any("issueUpdate" in q for q, _ in calls))

    def test_where_label_selects_targets(self):
        post, _ = fake_post(where_nodes=[{"identifier": "STU-1"}, {"identifier": "STU-2"}])
        out = cli.cmd_bulk_label(
            Args(where_label="agent:triaged", add_label=["agent:auto"], dry_run=True),
            ENV, post=post)
        self.assertEqual(out["targets"], ["STU-1", "STU-2"])


if __name__ == "__main__":
    unittest.main()
