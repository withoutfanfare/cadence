import os
import pathlib
import stat
import subprocess
import tempfile
import time
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
        self._write_exe("claude", "#!/bin/sh\nstdin=$(cat)\nprintf 'claude:%s:%s:%s\\n' \"$3\" \"$5\" \"$stdin\"")

        result = self._run("claude", "sonnet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run-orchestrator: claude triage", result.stderr)
        self.assertIn("claude:sonnet:Bash,Read,Grep,Glob,Task:hello provider", result.stdout)

    def test_claude_advance_invocation_keeps_read_only_allowed_tools(self):
        self._write_exe("claude", "#!/bin/sh\nprintf 'claude:%s\\n' \"$5\"")

        env = os.environ.copy()
        env["RUNNER_PATH_PREPEND"] = str(self.bin)
        env["ORCH_TIMEOUT"] = "5"
        result = subprocess.run(
            ["bash", str(self.script), "claude", "sonnet", str(self.workdir), str(self.prompt), "advance"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude:Bash,Read,Grep,Glob", result.stdout)
        self.assertNotIn("Edit", result.stdout)
        self.assertNotIn("Write", result.stdout)

    def test_kimi_invocation_uses_short_file_instruction(self):
        self._write_exe(
            "kimi",
            """#!/bin/sh
prompt="$6"
path="${prompt##*: }"
[ -r "$path" ] || exit 98
printf 'kimi:%s:%s:%s\\n' "$2" "$4" "$(cat "$path")"
""",
        )

        result = self._run("kimi", "k2")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"kimi:k2:{self.prompt.parent}:hello provider", result.stdout)

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

    def test_claude_effort_suffix_becomes_effort_flag(self):
        self._write_exe("claude", "#!/bin/sh\nstdin=$(cat)\nprintf 'claude:%s\\n' \"$*\"")

        result = self._run("claude", "sonnet:medium")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--model sonnet ", result.stdout)
        self.assertIn("--effort medium", result.stdout)
        self.assertNotIn("sonnet:medium", result.stdout)

    def test_claude_without_effort_suffix_omits_effort_flag(self):
        self._write_exe("claude", "#!/bin/sh\nstdin=$(cat)\nprintf 'claude:%s\\n' \"$*\"")

        result = self._run("claude", "sonnet")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--effort", result.stdout)

    def test_codex_effort_suffix_becomes_reasoning_effort_override(self):
        self._write_exe("codex", "#!/bin/sh\nstdin=$(cat)\nprintf 'codex:%s\\n' \"$*\"")

        result = self._run("codex", "gpt-test:high")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--model gpt-test ", result.stdout)
        self.assertIn('model_reasoning_effort="high"', result.stdout)

    def test_model_colon_is_kept_when_suffix_is_not_effort(self):
        self._write_exe("opencode", "#!/bin/sh\nprintf 'opencode:%s\\n' \"$*\"")

        result = self._run("opencode", "provider:model")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--model provider:model ", result.stdout)
        self.assertNotIn("effort=", result.stderr)

    def test_opencode_effort_suffix_is_stripped_with_warning(self):
        self._write_exe("opencode", "#!/bin/sh\nprintf 'opencode:%s\\n' \"$*\"")

        result = self._run("opencode", "provider/model:high")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--model provider/model ", result.stdout)
        self.assertNotIn("provider/model:high", result.stdout)
        self.assertIn("not supported for opencode", result.stderr)

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

    def test_timeout_kills_background_grandchildren(self):
        marker = pathlib.Path(self.tmp.name) / "grandchild-ran"
        # The provider spawns a background child that would touch the marker
        # after 3s, then blocks. On timeout the whole process group must die
        # before the child writes.
        self._write_exe(
            "claude",
            f"#!/bin/sh\n( sleep 3; : > '{marker}' ) &\nsleep 10\n",
        )

        result = self._run("claude", "sonnet", orch_timeout="1")

        self.assertEqual(result.returncode, 124, result.stderr)
        time.sleep(4)  # past the grandchild's 3s delay
        self.assertFalse(
            marker.exists(),
            "grandchild survived the timeout and kept mutating state")


if __name__ == "__main__":
    unittest.main()
