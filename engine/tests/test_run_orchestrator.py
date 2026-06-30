import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestRunOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = pathlib.Path(self.tmp.name) / "work"
        self.bin = pathlib.Path(self.tmp.name) / "bin"
        self.prompt = pathlib.Path(self.tmp.name) / "prompt.md"
        self.workdir.mkdir()
        self.bin.mkdir()
        self.prompt.write_text("hello provider", encoding="utf-8")
        self.script = ROOT / "engine" / "scripts" / "run-orchestrator.sh"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_exe(self, name, body):
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def _run(self, provider, model="model-a", orch_timeout="5"):
        env = os.environ.copy()
        env["RUNNER_PATH_PREPEND"] = str(self.bin)
        env["ORCH_TIMEOUT"] = orch_timeout
        return subprocess.run(
            ["bash", str(self.script), provider, model, str(self.workdir), str(self.prompt), "triage"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_claude_invocation_uses_prompt_and_model(self):
        self._write_exe("claude", "#!/bin/sh\nprintf 'claude:%s:%s\\n' \"$2\" \"$4\"\\n")

        result = self._run("claude", "sonnet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run-orchestrator: claude triage", result.stderr)
        self.assertIn("claude:hello provider:sonnet", result.stdout)

    def test_codex_invocation_sets_workdir_and_model(self):
        self._write_exe("codex", "#!/bin/sh\nprintf 'codex:%s:%s:%s\\n' \"$2\" \"$3\" \"${10}\"\\n")

        result = self._run("codex", "gpt-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("codex:--model:gpt-test:hello provider", result.stdout)

    def test_unknown_provider_fails(self):
        result = self._run("unknown")

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown provider: unknown", result.stderr)

    def test_missing_prompt_fails(self):
        self.prompt.unlink()

        result = self._run("claude")

        self.assertEqual(result.returncode, 3)
        self.assertIn("prompt not found", result.stderr)

    def test_provider_nonzero_exit_code_propagates(self):
        self._write_exe("claude", "#!/bin/sh\nexit 42\n")

        result = self._run("claude", "sonnet")

        self.assertEqual(result.returncode, 42, result.stderr)

    def test_timeout_returns_exit_code_124(self):
        self._write_exe("claude", "#!/bin/sh\nsleep 2\n")

        result = self._run("claude", "sonnet", orch_timeout="1")

        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn("timed out after 1s", result.stderr)


if __name__ == "__main__":
    unittest.main()
