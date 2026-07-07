import importlib.util, io, json, os, tempfile, types, unittest
from unittest import mock


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

    def test_issues_list_paginates_and_preserves_created_at(self):
        calls = []
        def post(query, variables, env):
            calls.append(variables)
            node = {
                "id": "i%s" % len(calls),
                "identifier": "STU-%s" % len(calls),
                "title": "T%s" % len(calls),
                "url": "u",
                "createdAt": "2026-06-0%sT00:00:00Z" % len(calls),
                "description": "d",
                "priority": 2,
                "state": {"name": "Todo", "type": "started"},
                "assignee": {"name": "D", "id": "user-1"},
                "labels": {"nodes": []},
                "cycle": None,
            }
            return {"issues": {"nodes": [node], "pageInfo": {
                "hasNextPage": len(calls) == 1,
                "endCursor": "cursor-1" if len(calls) == 1 else None,
            }}}
        args = types.SimpleNamespace(label=None, state=None, assignee="me", limit=None)
        out = cli.cmd_issues_list(args, ENV, post=post)

        self.assertEqual([i["identifier"] for i in out], ["STU-1", "STU-2"])
        self.assertEqual(out[0]["createdAt"], "2026-06-01T00:00:00Z")
        self.assertIsNone(calls[0].get("after"))
        self.assertEqual(calls[1].get("after"), "cursor-1")

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

    def test_issue_get_surfaces_linked_documents(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            return {"issue": {
                "id": "i1", "identifier": "STU-1", "title": "T", "url": "u",
                "documents": {"nodes": [{"id": "doc-9", "title": "Spec — STU-1", "url": "du"}]}}}
        out = cli.cmd_issue_get(types.SimpleNamespace(id="STU-1"), ENV, post=post)
        self.assertEqual(out["documents"], [{"id": "doc-9", "title": "Spec — STU-1", "url": "du"}])

    def test_doc_get_returns_body_when_in_scope(self):
        cap = {"response": {"document": {
            "id": "doc-9", "title": "Spec", "url": "du", "content": "## Problem\n...",
            "issue": {"team": {"id": "team-1"}}}}}
        out = cli.cmd_doc_get(types.SimpleNamespace(id="doc-9"), ENV, post=fake_post(cap))
        self.assertEqual(out["content"], "## Problem\n...")
        self.assertEqual(out["id"], "doc-9")

    def test_doc_get_rejects_out_of_team_scope(self):
        cap = {"response": {"document": {
            "id": "doc-9", "content": "x", "issue": {"team": {"id": "other-team"}}}}}
        with self.assertRaises(cli.LinearError):
            cli.cmd_doc_get(types.SimpleNamespace(id="doc-9"), ENV, post=fake_post(cap))

    def test_doc_get_rejects_missing_document(self):
        with self.assertRaises(cli.LinearError):
            cli.cmd_doc_get(types.SimpleNamespace(id="nope"), ENV,
                            post=fake_post({"response": {"document": None}}))

    def test_issue_get_rejects_out_of_assignee_scope(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-2"}}}
            return {"issue": {"id": "i1"}}
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_get(types.SimpleNamespace(id="i1"), ENV, post=post)

    def test_viewer_returns_current_user(self):
        cap = {"response": {"viewer": {"id": "user-1", "name": "Dee", "email": "d@x"}}}
        out = cli.cmd_viewer(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(out, {"id": "user-1", "name": "Dee", "email": "d@x"})

    def test_projects_list_scopes_to_team(self):
        cap = {"response": {"team": {"projects": {"nodes": [
            {"id": "proj-1", "name": "Alpha"}, {"id": "proj-2", "name": "Beta"}]}}}}
        out = cli.cmd_projects_list(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(out, [{"id": "proj-1", "name": "Alpha"},
                               {"id": "proj-2", "name": "Beta"}])
        self.assertEqual(cap["variables"]["teamId"], "team-1")

    def test_projects_list_requires_team_id(self):
        env = dict(ENV); env["LINEAR_TEAM_ID"] = ""
        with self.assertRaises(cli.LinearError):
            cli.cmd_projects_list(types.SimpleNamespace(), env, post=lambda *a: {})

    def test_cycles_list_shapes(self):
        cap = {"response": {"cycles": {"nodes": [
            {"id": "c1", "number": 5, "name": "C5",
             "startsAt": "2026-06-01", "endsAt": "2026-06-14"}]}}}
        out = cli.cmd_cycles_list(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(out[0]["number"], 5)
        self.assertEqual(out[0]["starts_at"], "2026-06-01")

    def test_issues_list_includes_canonical_stage(self):
        cap = {"response": {"issues": {"nodes": [{
            "id": "i1", "identifier": "ENG-1", "title": "T", "url": "u",
            "labels": {"nodes": [{"name": "agent:specced"}]},
        }]}}}
        args = types.SimpleNamespace(label=None, state=None, assignee=None, limit=None)
        out = cli.cmd_issues_list(args, ENV, post=fake_post(cap))
        self.assertEqual(out[0]["stage"]["name"], "specced")
        self.assertEqual(out[0]["stage"]["advance"], "agent:build")

class TestProjectGet(unittest.TestCase):
    def test_reads_configured_project_description(self):
        cap = {"response": {"project": {
            "id": "proj-1", "name": "App", "description": "Make onboarding self-serve."}}}
        out = cli.cmd_project_get(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(cap["variables"], {"id": "proj-1"})
        self.assertEqual(out, {"id": "proj-1", "name": "App",
                               "description": "Make onboarding self-serve."})

    def test_requires_project_id(self):
        env = dict(ENV); env.pop("LINEAR_PROJECT_ID")
        with self.assertRaises(cli.LinearError):
            cli.cmd_project_get(types.SimpleNamespace(), env, post=fake_post({"response": {}}))


def routing_post(routes, calls):
    """Dispatch a fake response by substring of the query; record every call."""
    def _post(query, variables, env):
        calls.append((query, variables))
        for needle, resp in routes:
            if needle in query:
                return resp
        raise AssertionError("unexpected query: " + query.strip()[:80])
    return _post


class TestIssueCreate(unittest.TestCase):
    def _env(self, **extra):
        env = dict(ENV)
        env.update(extra)
        return env

    def _labels_resp(self):
        return {"issueLabels": {"nodes": [
            {"id": "lbl-proposed", "name": "agent:proposed"},
            {"id": "lbl-bug", "name": "Bug"}]}}

    def _issues_resp(self, n_open, state=("Backlog", "backlog")):
        nodes = [{"id": "i%d" % i, "identifier": "STU-%d" % i, "title": "t",
                  "url": "u", "state": {"name": state[0], "type": state[1]},
                  "labels": {"nodes": [{"name": "agent:proposed"}]}}
                 for i in range(n_open)]
        return {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False}}}

    def _body(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        f.write(text); f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_creates_scoped_proposal_with_forced_label(self):
        calls = []
        post = routing_post([
            ("issues(", self._issues_resp(0)),
            ("issueLabels", self._labels_resp()),
            ("issueCreate", {"issueCreate": {"success": True, "issue": {
                "id": "new-1", "identifier": "STU-9", "url": "https://x"}}}),
        ], calls)
        args = types.SimpleNamespace(
            title="Add retry to importer",
            body_file=self._body("Why this serves the goal.\n"), label=["Bug"])
        out = cli.cmd_issue_create(args, self._env(), post=post)
        inp = calls[-1][1]["input"]
        self.assertEqual(inp["teamId"], "team-1")
        self.assertEqual(inp["projectId"], "proj-1")
        self.assertEqual(inp["assigneeId"], "user-1")
        self.assertEqual(inp["title"], "Add retry to importer")
        self.assertEqual(inp["description"], "Why this serves the goal.")
        self.assertIn("lbl-proposed", inp["labelIds"])
        self.assertIn("lbl-bug", inp["labelIds"])
        self.assertEqual(out, {"id": "new-1", "identifier": "STU-9",
                               "url": "https://x", "success": True})

    def test_refuses_when_open_proposals_reach_cap(self):
        calls = []
        post = routing_post([("issues(", self._issues_resp(2))], calls)
        args = types.SimpleNamespace(title="One more",
                                     body_file=self._body("x"), label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_create(args, self._env(ROADMAP_MAX_OPEN="2"), post=post)
        self.assertFalse(any("issueCreate" in q for q, _ in calls))

    def test_cancelled_proposals_do_not_count_toward_cap(self):
        calls = []
        post = routing_post([
            ("issues(", self._issues_resp(3, state=("Cancelled", "canceled"))),
            ("issueLabels", self._labels_resp()),
            ("issueCreate", {"issueCreate": {"success": True, "issue": {
                "id": "new-2", "identifier": "STU-10", "url": "https://x"}}}),
        ], calls)
        args = types.SimpleNamespace(title="T", body_file=self._body("b"), label=None)
        out = cli.cmd_issue_create(args, self._env(ROADMAP_MAX_OPEN="3"), post=post)
        self.assertTrue(out["success"])


class TestWriteVerbs(unittest.TestCase):
    def test_label_ensure_returns_existing(self):
        cap = {"response": {"issueLabels": {"nodes": [
            {"id": "l1", "name": "agent:build"}]}}}
        args = types.SimpleNamespace(name="agent:build")
        out = cli.cmd_label_ensure(args, ENV, post=fake_post(cap))
        self.assertEqual(out, {"name": "agent:build", "id": "l1", "created": False})

    def test_labels_list_returns_names_and_ids(self):
        cap = {"response": {"issueLabels": {"nodes": [
            {"id": "l1", "name": "agent:build"},
            {"id": "l2", "name": "agent:spec"}]}}}
        out = cli.cmd_labels_list(types.SimpleNamespace(), ENV, post=fake_post(cap))
        self.assertEqual(out, [{"id": "l1", "name": "agent:build"},
                               {"id": "l2", "name": "agent:spec"}])

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

    def test_issue_update_enforces_single_position_label(self):
        # Adding agent:pr-open to an issue that still carries agent:specced must
        # persist only pr-open (+ non-position labels) — the engine drops the
        # superseded specced even though the caller forgot to remove it.
        sent = {}
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": [
                    {"id": "lt", "name": "agent:triaged"},
                    {"id": "ls", "name": "agent:specced"},
                    {"id": "lp", "name": "agent:pr-open"}]}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [
                    {"id": "lt", "name": "agent:triaged"},
                    {"id": "ls", "name": "agent:specced"}]}}}
            if "issueUpdate(" in query:
                sent["ids"] = variables["input"]["labelIds"]
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            state_type=None, cycle=None, add_label=["agent:pr-open"], remove_label=None)
        cli.cmd_issue_update(args, ENV, post=post)
        self.assertEqual(set(sent["ids"]), {"lt", "lp"})   # specced (ls) dropped

    def test_loop_cannot_grant_human_gate_label(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [{"id": "ls", "name": "agent:specced"}]}}}
            raise AssertionError("gate grant should be refused before mutation")
        env = dict(ENV, CADENCE_STAGE="spec")
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            state_type=None, cycle=None, add_label=["agent:build"], remove_label=None)
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, env, post=post)

    def test_blank_stage_cannot_bypass_gate_removal_guard(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            raise AssertionError("blank-stage removal should be refused before mutation")
        env = dict(ENV, CADENCE_STAGE="")
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            state_type=None, cycle=None, add_label=None, remove_label=["agent:spec"])
        with self.assertRaises(cli.LinearError):
            cli.cmd_issue_update(args, env, post=post)

    def test_autonomous_advance_can_grant_gate_on_auto_issue(self):
        sent = {}
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [
                    {"id": "la", "name": "agent:auto"},
                    {"id": "ls", "name": "agent:specced"}]}}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": [
                    {"id": "la", "name": "agent:auto"},
                    {"id": "ls", "name": "agent:specced"},
                    {"id": "lb", "name": "agent:build"}]}}
            if "issueUpdate(" in query:
                sent["ids"] = variables["input"]["labelIds"]
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            raise AssertionError(query)
        env = dict(ENV, CADENCE_STAGE="advance", AUTONOMOUS="on")
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            state_type=None, cycle=None, add_label=["agent:build"], remove_label=None)
        cli.cmd_issue_update(args, env, post=post)
        self.assertEqual(set(sent["ids"]), {"la", "ls", "lb"})

    def test_completing_an_issue_strips_agent_labels(self):
        # closing to a completed-type state clears every agent:* label but keeps
        # user labels — no separate label sweep needed after "Set as merged".
        sent = {}
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "workflowStates(" in query:
                return {"workflowStates": {"nodes": [
                    {"id": "done", "name": "Done", "type": "completed"}]}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": []}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [
                    {"id": "lp", "name": "agent:pr-open"},
                    {"id": "lt", "name": "agent:triaged"},
                    {"id": "lb", "name": "Bug"}]}}}
            if "issueUpdate(" in query:
                sent["ids"] = variables["input"]["labelIds"]
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            state_type="completed", cycle=None, add_label=None, remove_label=None)
        cli.cmd_issue_update(args, ENV, post=post)
        self.assertEqual(sent["ids"], ["lb"])   # only the non-agent label survives

    def test_completing_pr_open_issue_removes_its_worktree(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "workflowStates(" in query:
                return {"workflowStates": {"nodes": [
                    {"id": "done", "name": "Done", "type": "completed"}]}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": []}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [
                    {"id": "lp", "name": "agent:pr-open"},
                    {"id": "lb", "name": "Bug"}]}}}
            if "issueUpdate(" in query:
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="STU-1", priority=None, title=None, estimate=None, state=None,
            state_type="completed", cycle=None, add_label=None,
            remove_label=["agent:pr-open"])
        with mock.patch.object(cli, "_remove_worktree") as remove:
            cli.cmd_issue_update(args, ENV, post=post)
        remove.assert_called_once_with("stu-1", ENV)

    def test_failed_terminal_issue_update_does_not_remove_worktree(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "workflowStates(" in query:
                return {"workflowStates": {"nodes": [
                    {"id": "done", "name": "Done", "type": "completed"}]}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": []}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [
                    {"id": "lp", "name": "agent:pr-open"}]}}}
            if "issueUpdate(" in query:
                return {"issueUpdate": {"success": False, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="STU-1", priority=None, title=None, estimate=None, state=None,
            state_type="completed", cycle=None, add_label=None,
            remove_label=["agent:pr-open"])
        with mock.patch.object(cli, "_remove_worktree") as remove:
            with self.assertRaises(cli.LinearError):
                cli.cmd_issue_update(args, ENV, post=post)
        remove.assert_not_called()

    def test_completing_revised_issue_removes_its_worktree(self):
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "workflowStates(" in query:
                return {"workflowStates": {"nodes": [
                    {"id": "done", "name": "Done", "type": "completed"}]}}
            if "issueLabels(" in query:
                return {"issueLabels": {"nodes": []}}
            if "labels{ nodes{ id name } }" in query:
                return {"issue": {"labels": {"nodes": [
                    {"id": "lr", "name": "agent:revised"},
                    {"id": "lb", "name": "Bug"}]}}}
            if "issueUpdate(" in query:
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="STU-1", priority=None, title=None, estimate=None, state=None,
            state_type="completed", cycle=None, add_label=None,
            remove_label=["agent:revised"])
        with mock.patch.object(cli, "_remove_worktree") as remove:
            cli.cmd_issue_update(args, ENV, post=post)
        remove.assert_called_once_with("stu-1", ENV)

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

    def test_issue_update_state_type_resolves_completed_state(self):
        # The "Set as merged" click and the triage back-fill move an issue to the
        # done state by TYPE, not name — the name varies per workspace.
        seen = {}
        def post(query, variables, env):
            if "team { id } project" in query:
                return {"issue": {"team": {"id": "team-1"},
                                  "project": {"id": "proj-1"},
                                  "assignee": {"id": "user-1"}}}
            if "workflowStates(" in query:
                return {"workflowStates": {"nodes": [
                    {"id": "s-todo", "name": "Todo", "type": "started"},
                    {"id": "s-done", "name": "Merged", "type": "completed"}]}}
            if "issueUpdate(" in query:
                seen["stateId"] = variables["input"].get("stateId")
                return {"issueUpdate": {"success": True, "issue": {"id": "i1"}}}
            return {"issue": {"labels": {"nodes": []}}}
        args = types.SimpleNamespace(
            id="i1", priority=None, title=None, estimate=None, state=None,
            state_type="completed", cycle=None, add_label=None, remove_label=None)
        out = cli.cmd_issue_update(args, ENV, post=post)
        self.assertTrue(out["success"])
        self.assertEqual(seen["stateId"], "s-done")

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


class TestGraphqlErrors(unittest.TestCase):
    def test_non_json_response_raises_linear_error(self):
        # A 2xx with a non-JSON body (e.g. a WAF/CDN HTML page) must surface as the
        # adapter's normal LinearError, not a raw JSONDecodeError traceback.
        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"<html>Access Denied</html>"

        orig = cli.urllib.request.urlopen
        cli.urllib.request.urlopen = lambda req, timeout=None: FakeResp()
        try:
            with self.assertRaises(cli.LinearError):
                cli.graphql("{ viewer { id } }", {}, ENV)
        finally:
            cli.urllib.request.urlopen = orig


class _Resp:
    def __init__(self, body):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class TestGraphqlRetry(unittest.TestCase):
    def setUp(self):
        self._orig_urlopen = cli.urllib.request.urlopen
        self._orig_sleep = cli.time.sleep
        self.slept = []
        cli.time.sleep = lambda s: self.slept.append(s)

    def tearDown(self):
        cli.urllib.request.urlopen = self._orig_urlopen
        cli.time.sleep = self._orig_sleep

    def test_retries_once_then_succeeds_honouring_retry_after(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise cli.urllib.error.HTTPError(
                    "u", 429, "rate", {"Retry-After": "7"}, io.BytesIO(b""))
            return _Resp(json.dumps({"data": {"ok": True}}))

        cli.urllib.request.urlopen = fake
        out = cli.graphql("{ x }", {}, ENV)
        self.assertEqual(out, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.slept, [7])  # numeric Retry-After honoured

    def test_gives_up_after_three_attempts(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise cli.urllib.error.HTTPError("u", 500, "err", {}, io.BytesIO(b"err body"))

        cli.urllib.request.urlopen = fake
        with self.assertRaises(cli.LinearError):
            cli.graphql("{ x }", {}, ENV)
        self.assertEqual(len(calls), 3)          # 3 attempts total
        self.assertEqual(len(self.slept), 2)     # slept between them, not after the last

    def test_non_retryable_status_fails_immediately(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise cli.urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"bad body"))

        cli.urllib.request.urlopen = fake
        with self.assertRaises(cli.LinearError):
            cli.graphql("{ x }", {}, ENV)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.slept, [])

    def test_retry_after_is_capped(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            if len(calls) == 1:
                raise cli.urllib.error.HTTPError(
                    "u", 429, "rate", {"Retry-After": "9999"}, io.BytesIO(b""))
            return _Resp(json.dumps({"data": {"ok": True}}))

        cli.urllib.request.urlopen = fake
        cli.graphql("{ x }", {}, ENV)
        self.assertEqual(self.slept, [cli._MAX_RETRY_DELAY])  # not 9999

    def test_network_error_retries_then_raises(self):
        calls = []

        def fake(req, timeout=None):
            calls.append(1)
            raise cli.urllib.error.URLError("boom")

        cli.urllib.request.urlopen = fake
        with self.assertRaises(cli.LinearError):
            cli.graphql("{ x }", {}, ENV)
        self.assertEqual(len(calls), 3)


class TestAgentLabelVocabulary(unittest.TestCase):
    def test_roadmap_labels_are_in_the_init_set(self):
        self.assertIn("agent:proposed", cli.AGENT_LABELS)
        self.assertIn("agent:later", cli.AGENT_LABELS)


if __name__ == "__main__":
    unittest.main()
