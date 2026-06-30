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
        self._write_exe("claude", "#!/bin/sh\nstdin=$(cat)\nprintf 'claude:%s:%s\\n' \"$3\" \"$stdin\"")

        result = self._run("claude", "sonnet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run-orchestrator: claude triage", result.stderr)
        self.assertIn("claude:sonnet:hello provider", result.stdout)

    def test_kimi_invocation_uses_short_file_instruction(self):
        self._write_exe("kimi", "#!/bin/sh\nprintf 'kimi:%s:%s\\n' \"$2\" \"$4\"")

        result = self._run("kimi", "k2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("kimi:k2:Read and follow the brief in this file:", result.stdout)
        self.assertIn(str(self.prompt), result.stdout)

    def test_opencode_invocation_attaches_prompt_file(self):
        self._write_exe(
            "opencode",
            "#!/bin/sh\nprintf 'opencode:%s:%s:%s:%s\\n' \"$3\" \"$7\" \"$8\" \"$9\"",
        )

        result = self._run("opencode", "provider/model")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            f"opencode:provider/model:-f:{self.prompt}:Follow the attached brief exactly.",
            result.stdout,
        )

    def test_codex_invocation_sets_workdir_and_model(self):
        self._write_exe("codex", "#!/bin/sh\nstdin=$(cat)\nprintf 'codex:%s:%s:%s\\n' \"$(pwd)\" \"$3\" \"$stdin\"")

        result = self._run("codex", "gpt-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"codex:{self.workdir.resolve()}:gpt-test:hello provider", result.stdout)

    def test_large_prompt_is_streamed_without_putting_the_whole_text_on_argv(self):
        huge = "prompt-" + ("x" * 5000)
        self.prompt.write_text(huge, encoding="utf-8")
        self._write_exe(
            "codex",
            """#!/bin/sh
last=""
for arg in "$@"; do
  last="$arg"
done
if [ "${#last}" -gt 10 ]; then
  echo "argv prompt too large: ${#last}" >&2
  exit 99
fi
stdin=$(cat)
printf 'codex:%s:%s\\n' "${#stdin}" "$last"
""",
        )

        result = self._run("codex", "gpt-test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"codex:{len(huge)}:-", result.stdout)

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
