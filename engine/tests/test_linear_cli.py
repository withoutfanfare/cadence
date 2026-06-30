import importlib.util, os, types, unittest


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(__file__), *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load by unique module name so discovery doesn't collide with the memory
# adapter's identically-named `cli` module (both shadow sys.modules["cli"]).
cli = _load("cadence_linear_cli", "..", "linear", "cli.py")

ENV = {
    "LINEAR_API_KEY": "k",
    "LINEAR_TEAM_ID": "team-1",
    "LINEAR_PROJECT_ID": "proj-1",
    "LINEAR_TEAM_NAME": "Acme",
    "LINEAR_ASSIGNEE_ID": "user-1",
}

def fake_post(captured):
    def _post(query, variables, env):
        captured["query"] = query
        captured["variables"] = variables
        return captured["response"]
    return _post

class TestReadVerbs(unittest.TestCase):
    def test_teams_shapes_result(self):
        cap = {"response": {"teams": {"nodes": [
            {"id": "team-1", "key": "ACM", "name": "Acme"}]}}}
        out = cli.cmd_teams(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(out, [{"id": "team-1", "key": "ACM", "name": "Acme"}])

    def test_issues_list_scopes_to_team_and_project(self):
        cap = {"response": {"issues": {"nodes": []}}}
        args = types.SimpleNamespace(label="agent:build", state=None, assignee=None)
        cli.cmd_issues_list(args, ENV, post=fake_post(cap))
        f = cap["variables"]["filter"]
        self.assertEqual(f["team"]["id"]["eq"], "team-1")
        self.assertEqual(f["project"]["id"]["eq"], "proj-1")
        self.assertEqual(f["labels"]["name"]["eq"], "agent:build")

    def test_issues_list_assignee_me_uses_env(self):
        cap = {"response": {"issues": {"nodes": []}}}
        args = types.SimpleNamespace(label=None, state=None, assignee="me")
        cli.cmd_issues_list(args, ENV, post=fake_post(cap))
        self.assertEqual(
            cap["variables"]["filter"]["assignee"]["id"]["eq"], "user-1")

    def test_issue_get_returns_full_shape(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            return {"issue": {
                "id": "i1", "identifier": "STU-1", "title": "T", "url": "u",
                "description": "d", "state": {"name": "Todo"}, "priority": 2,
                "assignee": {"name": "D"}, "labels": {"nodes": [{"name": "Bug"}]},
                "cycle": {"number": 5}, "comments": {"nodes": []},
                "relations": {"nodes": []}, "children": {"nodes": []}}}
        args = types.SimpleNamespace(id="STU-1")
        out = cli.cmd_issue_get(args, ENV, post=post)
        self.assertEqual(out["identifier"], "STU-1")
        self.assertEqual(out["state"], "Todo")
        self.assertEqual(out["labels"], ["Bug"])
        self.assertEqual(out["cycle"], 5)

    def test_issue_get_rejects_out_of_assignee_scope(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-2"}}}
            return {"issue": {"id": "i1"}}
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_get(types.SimpleNamespace(id="i1"), ENV, post=post)

    def test_cycles_list_shapes(self):
        cap = {"response": {"cycles": {"nodes": [
            {"id": "c1", "number": 5, "name": "C5",
             "startsAt": "2026-06-01", "endsAt": "2026-06-14"}]}}}
        out = cli.cmd_cycles_list(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(out[0]["number"], 5)
        self.assertEqual(out[0]["starts_at"], "2026-06-01")

class TestWriteVerbs(unittest.TestCase):
    def test_label_ensure_returns_existing(self):
        cap = {"response": {"issueLabels": {"nodes": [
            {"id": "l1", "name": "agent:build"}]}}}
        args = types.SimpleNamespace(name="agent:build")
        out = cli.cmd_label_ensure(args, ENV, post=fake_post(cap))
        self.assertEqual(out, {"name": "agent:build", "id": "l1", "created": False})

    def test_labels_init_creates_only_missing(self):
        def post(query, variables, env):
            if "issueLabels(" in query:            # the list query
                return {"issueLabels": {"nodes": [
                    {"id": "l1", "name": "agent:build"}]}}
            return {"issueLabelCreate": {"issueLabel":     # create mutation
                    {"id": "new", "name": variables["input"]["name"]}}}
        out = cli.cmd_labels_init(types.SimpleNamespace(), ENV, post=post)
        self.assertEqual(out["existing"], ["agent:build"])
        self.assertNotIn("agent:build", out["created"])
        self.assertEqual(set(out["created"]),
                         set(cli.AGENT_LABELS) - {"agent:build"})

    def test_issue_update_fails_when_label_missing(self):
        # A missing label must raise, not silently no-op — otherwise the
        # `agent:claimed` concurrency lock can fail open.
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": [
                    {"id": "l1", "name": "agent:build"}]}}
            if "issueUpdate(" in query:
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            cycle=None, add_label=["agent:claimed"], remove_label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, ENV, post=post)

    def test_issue_update_rejects_empty_payload(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            cycle=None, add_label=None, remove_label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, ENV, post=post)

    def test_issue_comment(self):
        seen = {}
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            seen["body"] = variables["input"]["body"]
            return {"commentCreate": {"success": True, "comment": {"id": "c1"}}}
        args = types.SimpleNamespace(id="i1", body="hello")
        out = cli.cmd_issue_comment(args, ENV, post=post)
        self.assertTrue(out["success"])
        self.assertEqual(seen["body"], "hello")

    def test_issue_relate_maps_type(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            self.assertEqual(variables["input"]["type"], "duplicate")
            return {"issueRelationCreate": {"success": True}}
        args = types.SimpleNamespace(a="i1", b="i2", type="duplicate")
        out = cli.cmd_issue_relate(args, ENV, post=post)
        self.assertTrue(out["success"])

    def test_issue_update_rejects_out_of_scope(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-2"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
        args = types.SimpleNamespace(
            id="i1", priority=1, title=None, estimate=None, state=None,
            cycle=None, add_label=None, remove_label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, ENV, post=post)

    def test_issue_comment_rejects_out_of_scope(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-2"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            return {"commentCreate": {"success": True, "comment": {"id": "c1"}}}
        args = types.SimpleNamespace(id="i1", body="x")
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_comment(args, ENV, post=post)

    def test_issue_relate_rejects_out_of_scope_endpoint(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                ok = {"issue": {"team": {"id": "team-1"},
                                "project": {"id": "proj-1"},
                                "assignee": {"id": "user-1"}}}
                bad = {"issue": {"team": {"id": "team-2"},
                                 "project": {"id": "proj-1"},
                                 "assignee": {"id": "user-1"}}}
                return ok if variables["id"] == "i1" else bad
            return {"issueRelationCreate": {"success": True}}
        args = types.SimpleNamespace(a="i1", b="i2", type="related")
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_relate(args, ENV, post=post)

    def test_issue_update_rejects_wrong_assignee(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-2"}}}
            return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
        args = types.SimpleNamespace(
            id="i1", priority=1, title=None, estimate=None, state=None,
            cycle=None, add_label=None, remove_label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, ENV, post=post)

    def test_issue_update_requires_project_scope(self):
        env = dict(ENV)
        env["LINEAR_PROJECT_ID"] = ""
        args = types.SimpleNamespace(
            id="i1", priority=1, title=None, estimate=None, state=None,
            cycle=None, add_label=None, remove_label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, env, post=lambda *a: {})

    def test_doc_upsert_rejects_mismatched_document_issue(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "document(id:" in query:
                return {"document": {"id": "doc-1",
                                     "issue": {"id": "other",
                                               "team": {"id": "team-1"},
                                               "project": {"id": "proj-1"},
                                               "assignee": {"id": "user-1"}}}}
            return {"documentUpdate": {"success": True,
                                       "document": {"id": "doc-1", "url": "u"}}}
        args = types.SimpleNamespace(
            issue="i1", title="Spec", body="Body", doc_id="doc-1")
        with self.assertRaises(cli.LinearError):
            cli.cmd_doc_upsert(args, ENV, post=post)

if __name__ == "__main__":
    unittest.main()
