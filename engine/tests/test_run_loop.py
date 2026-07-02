import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestRunLoopPreLaunchGuards(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.project = os.path.join(self.tmp.name, "project")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.root = os.path.join(self.tmp.name, "cadence")
        os.makedirs(os.path.join(self.root, "engine"))
        shutil.copytree(os.path.join(ROOT, "engine", "scripts"),
                        os.path.join(self.root, "engine", "scripts"))
        shutil.copytree(os.path.join(ROOT, "engine", "lib"),
                        os.path.join(self.root, "engine", "lib"))
        shutil.copytree(os.path.join(ROOT, "engine", "tasks"),
                        os.path.join(self.root, "engine", "tasks"))
        os.makedirs(os.path.join(self.state, "runs"))
        os.makedirs(self.project)
        os.makedirs(self.bin)
        self.script = os.path.join(self.root, "engine", "scripts", "run-loop.sh")
        self._write_exe("claude", "#!/bin/sh\necho claude should not run >&2\nexit 99\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_exe(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def _env(self, **overrides):
        env = os.environ.copy()
        env.update({
            "CADENCE_STATE_DIR": self.state,
            "PROJECT_DIR": self.project,
            "RUNNER_PATH_PREPEND": self.bin,
            "LINEAR_TEAM_ID": "team-1",
            "LINEAR_PROJECT_ID": "proj-1",
            "LINEAR_ASSIGNEE_ID": "user-1",
            "LINEAR_API_KEY": "token",
            "NOTIFY": "off",
        })
        env.update(overrides)
        return env

    def _run(self, stage="triage", **env_overrides):
        return subprocess.run(
            ["bash", self.script, stage],
            cwd=self.root,
            env=self._env(**env_overrides),
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_paused_run_records_digest_and_json_without_launching_claude(self):
        open(os.path.join(self.state, "runs", "PAUSED"), "w").close()

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["stage"], "triage")
        self.assertTrue(payload["paused"])
        self.assertEqual(payload["reason"], "manual")
        self.assertIn("triage paused", self._read_today_digest())
        self.assertEqual(json.loads(self._read_ledger().strip())["reason"], "manual")

    def test_wrong_workspace_records_pause_before_launching_claude(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ] && [ "$2" = "teams" ]; then
  printf '[{{"id":"other-team","name":"Other"}}]\\n'
  exit 0
fi
exec {real_python} "$@"
""")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason"], "wrong-workspace")
        self.assertIn("wrong-workspace", self._read_today_digest())
        self.assertEqual(json.loads(self._read_ledger().strip())["reason"], "wrong-workspace")

    def test_file_backend_launches_tasks_prompt_without_linear_credentials(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        prompt_copy = os.path.join(self.state, "file-prompt.md")
        os.makedirs(os.path.join(self.project, "cadence"))
        with open(os.path.join(self.project, "cadence", "tasks.md"), "w", encoding="utf-8") as f:
            f.write("# Tasks\n")
        os.makedirs(os.path.join(self.root, "skills", "cadence-loop-triage"))
        with open(os.path.join(self.root, "skills", "cadence-loop-triage", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: cadence-loop-triage\n---\nLoop body\n")
        shutil.copytree(os.path.join(ROOT, "engine", "prompts"),
                        os.path.join(self.root, "engine", "prompts"))
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ]; then
  echo linear should not run >&2
  exit 66
fi
exec {real_python} "$@"
""")
        self._write_exe("codex", f"""#!/bin/sh
cat > "{prompt_copy}"
printf '{{"stage":"triage","triaged":1,"errors":0}}\\n'
""")

        result = self._run(
            "triage",
            TASK_BACKEND="file",
            ORCHESTRATOR_TRIAGE="codex:gpt-test",
            LINEAR_TEAM_ID="",
            LINEAR_PROJECT_ID="",
            LINEAR_ASSIGNEE_ID="",
            LINEAR_API_KEY="",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("wrong-workspace", result.stdout)
        with open(prompt_copy, encoding="utf-8") as f:
            prompt = f.read()
        self.assertIn("TASK_BACKEND=file", prompt)
        self.assertIn("cadence tasks list", prompt)
        self.assertNotIn("cadence linear", prompt)

    def test_file_backend_missing_task_file_pauses_before_launch(self):
        result = self._run(
            "triage",
            TASK_BACKEND="file",
            LINEAR_TEAM_ID="",
            LINEAR_PROJECT_ID="",
            LINEAR_ASSIGNEE_ID="",
            LINEAR_API_KEY="",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason"], "missing-task-file")
        self.assertIn("cadence/tasks.md", payload["detail"])

    def test_failed_run_alerts_via_activity_feed_and_digest(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        # teams returns the configured team so the workspace guard passes; every
        # other python3 call (the summary heredoc) runs under real python3.
        os.makedirs(os.path.join(self.root, "skills", "cadence-loop-triage"))
        with open(os.path.join(self.root, "skills", "cadence-loop-triage", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: cadence-loop-triage\n---\nLoop body\n")
        shutil.copytree(os.path.join(ROOT, "engine", "prompts"),
                        os.path.join(self.root, "engine", "prompts"))
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ] && [ "$2" = "teams" ]; then
  printf '[{{"id":"team-1","name":"Team"}}]\\n'
  exit 0
fi
exec {real_python} "$@"
""")
        # claude crashes: non-zero exit, no JSON summary in the log.
        self._write_exe("claude", "#!/bin/sh\necho boom >&2\nexit 7\n")

        result = self._run()

        self.assertEqual(result.returncode, 7, result.stderr)
        with open(os.path.join(self.state, "runs", "activity.log"), encoding="utf-8") as f:
            feed = f.read()
        self.assertIn("FAILED — exit 7", feed)
        self.assertIn("FAILED", self._read_today_digest())

    def test_successful_run_uses_selected_orchestrator_provider(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        os.makedirs(os.path.join(self.root, "skills", "cadence-loop-triage"))
        with open(os.path.join(self.root, "skills", "cadence-loop-triage", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: cadence-loop-triage\n---\nLoop body\n")
        shutil.copytree(os.path.join(ROOT, "engine", "prompts"),
                        os.path.join(self.root, "engine", "prompts"))
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ] && [ "$2" = "teams" ]; then
  printf '[{{"id":"team-1","name":"Team"}}]\\n'
  exit 0
fi
exec {real_python} "$@"
""")
        self._write_exe("codex", "#!/bin/sh\nprintf '{\"stage\":\"triage\",\"triaged\":1,\"errors\":0}\\n'\n")

        result = self._run("triage", ORCHESTRATOR_TRIAGE="codex:gpt-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.state, "logs", "triage.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("starting cadence triage (codex:gpt-test)", log)
        self.assertIn("run-orchestrator: codex triage model=gpt-test", log)
        self.assertIn('"triaged":1', log)

    def test_marker_summary_is_parsed_even_when_surrounded_by_prose(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        os.makedirs(os.path.join(self.root, "skills", "cadence-loop-triage"))
        with open(os.path.join(self.root, "skills", "cadence-loop-triage", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: cadence-loop-triage\n---\nLoop body\n")
        shutil.copytree(os.path.join(ROOT, "engine", "prompts"),
                        os.path.join(self.root, "engine", "prompts"))
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ] && [ "$2" = "teams" ]; then
  printf '[{{"id":"team-1","name":"Team"}}]\\n'
  exit 0
fi
exec {real_python} "$@"
""")
        # The model wraps the summary in prose; only the marker line is authoritative.
        self._write_exe("codex", "#!/bin/sh\n"
                        "echo 'Here is what I did this run:'\n"
                        "printf 'CADENCE_SUMMARY {\"stage\":\"triage\",\"triaged\":5,\"errors\":0}\\n'\n"
                        "echo 'All done.'\n")

        result = self._run("triage", ORCHESTRATOR_TRIAGE="codex:gpt-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.state, "runs", "activity.log"), encoding="utf-8") as f:
            feed = f.read()
        self.assertIn("5 triaged", feed)

    def test_advance_no_auto_work_records_idle_without_pause_digest(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ] && [ "$2" = "teams" ]; then
  printf '[{{"id":"team-1","name":"Team"}}]\\n'
  exit 0
fi
if [ "$1" = "{linear_cli}" ] && [ "$2" = "issues-list" ]; then
  printf '[]\\n'
  exit 0
fi
exec {real_python} "$@"
""")

        result = self._run("advance", AUTONOMOUS="on")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["stage"], "advance")
        self.assertTrue(payload["idle"])
        self.assertFalse(payload.get("paused", False))
        self.assertFalse([x for x in os.listdir(os.path.join(self.state, "runs"))
                          if x.endswith(".md")])

    def test_file_backend_advance_launches_when_auto_task_exists(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        os.makedirs(os.path.join(self.project, "cadence"))
        with open(os.path.join(self.project, "cadence", "tasks.md"), "w", encoding="utf-8") as f:
            f.write("""# Tasks

## TASK-1: Auto task
status: ready
labels: agent:auto, agent:triaged

Body.
""")
        os.makedirs(os.path.join(self.root, "skills", "cadence-loop-advance"))
        with open(os.path.join(self.root, "skills", "cadence-loop-advance", "SKILL.md"), "w", encoding="utf-8") as f:
            f.write("---\nname: cadence-loop-advance\n---\nLoop body\n")
        shutil.copytree(os.path.join(ROOT, "engine", "prompts"),
                        os.path.join(self.root, "engine", "prompts"))
        self._write_exe("python3", f"""#!/bin/sh
if [ "$1" = "{linear_cli}" ]; then
  echo linear should not run >&2
  exit 66
fi
exec {real_python} "$@"
""")
        self._write_exe("codex", "#!/bin/sh\nprintf '{\"stage\":\"advance\",\"advanced\":1,\"errors\":0}\\n'\n")

        result = self._run(
            "advance",
            TASK_BACKEND="file",
            AUTONOMOUS="on",
            ORCHESTRATOR_ADVANCE="codex:gpt-test",
            LINEAR_TEAM_ID="",
            LINEAR_PROJECT_ID="",
            LINEAR_ASSIGNEE_ID="",
            LINEAR_API_KEY="",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('"idle":true', result.stdout)
        with open(os.path.join(self.state, "logs", "advance.log"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("starting cadence advance (codex:gpt-test)", log)

    def _read_today_digest(self):
        files = [x for x in os.listdir(os.path.join(self.state, "runs"))
                 if x.endswith(".md")]
        self.assertEqual(len(files), 1)
        with open(os.path.join(self.state, "runs", files[0]), encoding="utf-8") as f:
            return f.read()

    def _read_ledger(self):
        with open(os.path.join(self.state, "runs", "runs.jsonl"), encoding="utf-8") as f:
            return f.read()


if __name__ == "__main__":
    unittest.main()
