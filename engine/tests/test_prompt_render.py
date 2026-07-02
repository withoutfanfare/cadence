import pathlib
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestPromptRender(unittest.TestCase):
    def test_render_strips_frontmatter_and_includes_runtime_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "prompt.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "engine" / "prompts" / "render.py"),
                    "build",
                    "--implementer=codex",
                    "--output",
                    str(out),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = out.read_text(encoding="utf-8")

        self.assertNotIn("allowed-tools:", text)
        self.assertNotIn("model: opus", text)
        self.assertIn("# Cadence loop: build", text)
        self.assertIn("Runtime arguments: --implementer=codex", text)
        self.assertIn("Build loop for the configured Linear project", text)

    def test_file_backend_prompt_uses_tasks_adapter_not_linear(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "prompt.md"
            env = os.environ.copy()
            env["TASK_BACKEND"] = "file"
            env["TASK_FILE"] = "/tmp/tasks.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "engine" / "prompts" / "render.py"),
                    "triage",
                    "--mode=enrich",
                    "--output",
                    str(out),
                ],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            text = out.read_text(encoding="utf-8")

        self.assertIn("TASK_BACKEND=file", text)
        self.assertIn("cadence tasks list", text)
        self.assertIn("/tmp/tasks.md", text)
        self.assertNotIn("cadence linear", text)
        self.assertNotIn("Linear project", text)
        # File triage must stub acceptance criteria, else the conductor's
        # criteria filter rejects every task and autonomous mode never advances.
        self.assertIn("Acceptance Criteria", text)

    def test_unknown_stage_fails_before_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "prompt.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "engine" / "prompts" / "render.py"),
                    "unknown",
                    "--output",
                    str(out),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown stage: unknown", result.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
