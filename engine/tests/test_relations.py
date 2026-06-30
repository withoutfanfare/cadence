import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "linear_cli", os.path.join(os.path.dirname(__file__), "..", "linear", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def fake_post(payload):
    def post(query, variables, env):
        return payload
    return post


class TestRelations(unittest.TestCase):
    def test_issue_get_passes_through_inverse_relations(self):
        payload = {"issue": {
            "id": "i", "identifier": "X-1", "title": "t", "url": "u",
            "inverseRelations": {"nodes": [
                {"type": "blocks",
                 "issue": {"identifier": "X-2", "url": "https://linear.app/X-2",
                           "state": {"type": "started"}}}]},
        }}
        env = {"LINEAR_TEAM_ID": "T", "LINEAR_PROJECT_ID": "P", "LINEAR_ASSIGNEE_ID": "A"}
        # _assert_in_scope also calls post; return the scope shape for that query.
        def post(query, variables, e):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "T"}, "project": {"id": "P"},
                                  "assignee": {"id": "A"}}}
            return payload
        out = cli.cmd_issue_get(Args(id="X-1"), env, post=post)
        self.assertEqual(out["inverseRelations"][0]["type"], "blocks")
        self.assertEqual(out["inverseRelations"][0]["issue"]["state"]["type"], "started")

    def test_issue_relate_accepts_blocks(self):
        p = cli._build_parser()
        ns = p.parse_args(["issue-relate", "X-1", "X-2", "--type", "blocks"])
        self.assertEqual(ns.type, "blocks")


if __name__ == "__main__":
    unittest.main()
