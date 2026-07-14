import importlib.util
import json
import os
import tempfile
import unittest


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(__file__), *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load("cadence_overview_cli", "..", "overview", "cli.py")


class TestOverview(unittest.TestCase):
    def _project(self, tmp, name, *, scheduled, state, ledger=None, paused=False, activity=None,
                 autonomous=False, roadmap_schedule=None):
        proj = os.path.join(tmp, name)
        os.makedirs(os.path.join(proj, "cadence"))
        with open(os.path.join(proj, "cadence", ".env"), "w", encoding="utf-8") as f:
            f.write("CADENCE_SCHEDULED=%s\n" % ("1" if scheduled else "0"))
            f.write("AUTONOMOUS=%s\n" % ("on" if autonomous else "0"))
            f.write("CADENCE_STATE_DIR=%s\n" % state)
            f.write('LINEAR_TEAM_NAME="Team %s"\n' % name)
            f.write('LINEAR_WORKSPACE_SLUG="workspace-%s"\n' % name)
            if roadmap_schedule:
                f.write("SCHED_ROADMAP=%s\n" % roadmap_schedule)
        os.makedirs(os.path.join(state, "runs"))
        if paused:
            open(os.path.join(state, "runs", "PAUSED"), "w").close()
        if ledger:
            with open(os.path.join(state, "runs", "runs.jsonl"), "w", encoding="utf-8") as f:
                for rec in ledger:
                    f.write(json.dumps(rec) + "\n")
        if activity:
            with open(os.path.join(state, "runs", "activity.log"), "w", encoding="utf-8") as f:
                f.write(activity + "\n")
        return proj

    def test_aggregates_projects_with_health_and_stage_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            p1 = self._project(
                tmp, "app1", scheduled=True, autonomous=True, state=os.path.join(tmp, "s1"),
                ledger=[{"stage": "triage", "mode": "enrich", "errors": 0, "ts": "2026-07-02T08:00:00Z"}],
                activity="[2026-07-02T08:00:00Z] triage — LIVE nothing to do")
            p2 = self._project(
                tmp, "app2", scheduled=False, state=os.path.join(tmp, "s2"), paused=True)
            with open(registry, "w", encoding="utf-8") as f:
                f.write(p1 + "\n" + p2 + "\n")

            data = cli.overview({"CADENCE_PROJECTS_FILE": registry})
            by_name = {p["name"]: p for p in data["projects"]}

            self.assertEqual(set(by_name), {"app1", "app2"})
            self.assertEqual(by_name["app1"]["health"], "ok")
            self.assertTrue(by_name["app1"]["scheduled"])
            self.assertTrue(by_name["app1"]["autonomous"])
            self.assertFalse(by_name["app2"]["autonomous"])
            # scheduled project advertises a next run per stage; paused one does not
            self.assertIsNotNone(by_name["app1"]["schedule"]["triage"])
            self.assertIsNone(by_name["app2"]["schedule"]["triage"])
            self.assertEqual(by_name["app1"]["stages"]["triage"]["result"], "ok")
            self.assertIsNone(by_name["app1"]["stages"]["spec"])
            self.assertEqual(by_name["app1"]["last_activity"],
                             "[2026-07-02T08:00:00Z] triage — LIVE nothing to do")
            self.assertEqual(by_name["app1"]["board_url"], "https://linear.app/workspace-app1/")

            self.assertEqual(by_name["app2"]["health"], "paused")
            self.assertTrue(by_name["app2"]["paused"])
            self.assertFalse(by_name["app2"]["scheduled"])

    def test_error_in_ledger_marks_project_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            p1 = self._project(
                tmp, "app", scheduled=True, state=os.path.join(tmp, "s"),
                ledger=[{"loop": "build", "errors": 2, "ts": "2026-07-02T08:30:00Z"}])
            with open(registry, "w", encoding="utf-8") as f:
                f.write(p1 + "\n")
            data = cli.overview({"CADENCE_PROJECTS_FILE": registry})
            self.assertEqual(data["projects"][0]["health"], "failed")
            self.assertEqual(data["projects"][0]["stages"]["build"]["errors"], 2)

    def test_non_numeric_ledger_errors_field_does_not_crash(self):
        # A misbehaving provider can leave a non-numeric "errors" value (e.g. "none")
        # in a ledger record. Overview must not crash on int() coercion — it should
        # treat the malformed value as 0, same as a malformed JSON line is already
        # skipped rather than sinking the whole overview.
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            p1 = self._project(
                tmp, "app", scheduled=True, state=os.path.join(tmp, "s"),
                ledger=[{"stage": "triage", "errors": "none", "ts": "2026-07-02T08:00:00Z"}])
            with open(registry, "w", encoding="utf-8") as f:
                f.write(p1 + "\n")
            data = cli.overview({"CADENCE_PROJECTS_FILE": registry})
            project = data["projects"][0]
            self.assertEqual(project["health"], "ok")
            self.assertEqual(project["stages"]["triage"]["errors"], 0)
            self.assertEqual(project["stages"]["triage"]["result"], "ok")

    def test_stale_paused_entry_does_not_mask_stage_result(self):
        # Project was paused, then resumed; spec ran once (paused) and hasn't run
        # since. No PAUSED flag now -> health ok, and the stale paused entry must
        # not show as the spec result. triage's real run still shows through.
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            p1 = self._project(
                tmp, "app", scheduled=True, state=os.path.join(tmp, "s"),
                ledger=[
                    {"stage": "triage", "errors": 0, "ts": "2026-07-02T07:00:00Z"},
                    {"stage": "spec", "paused": True, "reason": "manual", "ts": "2026-07-02T08:00:00Z"},
                ])
            with open(registry, "w", encoding="utf-8") as f:
                f.write(p1 + "\n")
            data = cli.overview({"CADENCE_PROJECTS_FILE": registry})
            p = data["projects"][0]
            self.assertEqual(p["health"], "ok")
            self.assertIsNone(p["stages"]["spec"])          # paused entry ignored
            self.assertEqual(p["stages"]["triage"]["result"], "ok")

    def test_roadmap_activity_is_reported_and_scheduled(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            p1 = self._project(
                tmp, "app", scheduled=True, state=os.path.join(tmp, "s"),
                roadmap_schedule="24h@20",
                ledger=[{"stage": "roadmap", "proposed": 2, "errors": 0,
                         "ts": "2026-07-02T09:00:00Z"}])
            with open(registry, "w", encoding="utf-8") as f:
                f.write(p1 + "\n")

            data = cli.overview({"CADENCE_PROJECTS_FILE": registry})
            project = data["projects"][0]

            self.assertEqual(project["health"], "ok")
            self.assertEqual(project["stages"]["roadmap"]["result"], "ok")
            self.assertIsNotNone(project["schedule"]["roadmap"])
            self.assertIn("roadmap=ok", cli.render_human(data))

    def test_empty_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            data = cli.overview({"CADENCE_PROJECTS_FILE": registry})
            self.assertEqual(data["projects"], [])
            self.assertIn("Cadence overview", cli.render_human(data))

    def test_linear_workspace_legacy_value_is_not_used_as_board_url(self):
        board_url = cli._linear_board_url({
            "TASK_BACKEND": "linear",
            "LINEAR_WORKSPACE": "https://linear.app/acme/",
        })
        self.assertIsNone(board_url)

    def test_project_local_config_uses_root_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "cadence-home")
            global_state = os.path.join(tmp, "global-state")
            local_state = os.path.join(tmp, "local-state")
            project = self._project(
                tmp, "app", scheduled=True, state=local_state,
                ledger=[{"stage": "triage", "errors": 0, "ts": "2026-07-02T08:00:00Z"}])
            config = os.path.join(project, "cadence", ".env")
            registry = os.path.join(global_state, "projects.txt")
            os.makedirs(home)
            os.makedirs(global_state)
            with open(os.path.join(home, ".env"), "w", encoding="utf-8") as f:
                f.write(f"CADENCE_STATE_DIR={global_state}\n")
            with open(registry, "w", encoding="utf-8") as f:
                f.write(project + "\n")

            data = cli.overview({
                "CADENCE_HOME": home,
                "CADENCE_CONFIG": config,
                "CADENCE_STATE_DIR": local_state,
            })

            self.assertEqual(data["registry"], registry)
            self.assertEqual(data["projects"][0]["project"], project)


if __name__ == "__main__":
    unittest.main()
