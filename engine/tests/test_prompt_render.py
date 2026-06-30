import pathlib
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
