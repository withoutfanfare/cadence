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

    def _env(self):
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
        return env

    def _run(self):
        return subprocess.run(
            ["bash", self.script, "triage"],
            cwd=self.root,
            env=self._env(),
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

    def test_failed_run_alerts_via_activity_feed_and_digest(self):
        real_python = sys.executable
        linear_cli = os.path.join(self.root, "engine", "linear", "cli.py")
        # teams returns the configured team so the workspace guard passes; every
        # other python3 call (the summary heredoc) runs under real python3.
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
