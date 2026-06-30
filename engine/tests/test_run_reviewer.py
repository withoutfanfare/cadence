import os
import pathlib
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestRunReviewer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workdir = pathlib.Path(self.tmp.name) / "work"
        self.bin = pathlib.Path(self.tmp.name) / "bin"
        self.brief = pathlib.Path(self.tmp.name) / "review.md"
        self.workdir.mkdir()
        self.bin.mkdir()
        self.brief.write_text("review this diff", encoding="utf-8")
        self.script = ROOT / "engine" / "scripts" / "run-reviewer.sh"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_exe(self, name, body):
        path = self.bin / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def test_reviewer_uses_same_provider_contract(self):
        self._write_exe("claude", "#!/bin/sh\nprintf 'review:%s:%s\\n' \"$2\" \"$4\"\n")
        env = os.environ.copy()
        env["PATH"] = str(self.bin) + os.pathsep + env.get("PATH", "")
        env["REVIEW_TIMEOUT"] = "5"

        result = subprocess.run(
            ["bash", str(self.script), "claude", "opus", str(self.workdir), str(self.brief)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("run-reviewer: claude model=opus", result.stderr)
        self.assertIn("review:review this diff:opus", result.stdout)


if __name__ == "__main__":
    unittest.main()
