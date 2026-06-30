import os
import pathlib
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestProvidersCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name) / "home"
        self.cadence_home = pathlib.Path(self.tmp.name) / "cadence"
        self.home.mkdir()
        self.cadence_home.mkdir()
        self.env_path = self.cadence_home / ".env"
        self.script = ROOT / "engine" / "providers" / "cli.py"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        env = os.environ.copy()
        env.update({"HOME": str(self.home), "CADENCE_HOME": str(self.cadence_home)})
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_roles_explains_each_provider_role_with_current_values(self):
        self.env_path.write_text(
            textwrap.dedent(
                """\
                ORCHESTRATOR_TRIAGE=claude:sonnet
                ORCHESTRATOR_SPEC=claude:opus
                ORCHESTRATOR_BUILD=codex:gpt-5.4
                ORCHESTRATOR_REVISE=kimi:k2
                ORCHESTRATOR_ADVANCE=claude:sonnet
                REVIEW_PROVIDER=opencode
                REVIEW_MODEL=zai-coding-plan/glm-5.2
                BUILD_IMPLEMENTER=codex
                """
            ),
            encoding="utf-8",
        )

        result = self._run("roles")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("build orchestrator", result.stdout)
        self.assertIn("ORCHESTRATOR_BUILD", result.stdout)
        self.assertIn("codex:gpt-5.4", result.stdout)
        self.assertIn("folded reviewer", result.stdout)
        self.assertIn("REVIEW_PROVIDER/REVIEW_MODEL", result.stdout)
        self.assertIn("opencode:zai-coding-plan/glm-5.2", result.stdout)
        self.assertIn("build implementer", result.stdout)
        self.assertIn("BUILD_IMPLEMENTER", result.stdout)

    def test_show_prints_raw_provider_configuration(self):
        self.env_path.write_text("ORCHESTRATOR_PROVIDER=kimi\n", encoding="utf-8")

        result = self._run("show")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ORCHESTRATOR_PROVIDER=kimi", result.stdout)
        self.assertIn("ORCHESTRATOR_BUILD=kimi:opus", result.stdout)

    def test_set_all_review_and_implementer_preserves_unrelated_env_lines(self):
        self.env_path.write_text(
            textwrap.dedent(
                """\
                # Cadence profile
                LINEAR_TEAM_ID=team-1
                ORCHESTRATOR_BUILD=claude:opus
                BUILD_IMPLEMENTER=claude
                """
            ),
            encoding="utf-8",
        )

        result = self._run("set", "--all", "codex:gpt-5.4", "--review", "claude:opus", "--implementer", "codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.env_path.read_text(encoding="utf-8")
        self.assertIn("# Cadence profile\n", text)
        self.assertIn("LINEAR_TEAM_ID=team-1\n", text)
        self.assertIn("ORCHESTRATOR_TRIAGE=codex:gpt-5.4\n", text)
        self.assertIn("ORCHESTRATOR_SPEC=codex:gpt-5.4\n", text)
        self.assertIn("ORCHESTRATOR_BUILD=codex:gpt-5.4\n", text)
        self.assertIn("ORCHESTRATOR_REVISE=codex:gpt-5.4\n", text)
        self.assertIn("ORCHESTRATOR_ADVANCE=codex:gpt-5.4\n", text)
        self.assertIn("REVIEW_PROVIDER=claude\n", text)
        self.assertIn("REVIEW_MODEL=opus\n", text)
        self.assertIn("BUILD_IMPLEMENTER=codex\n", text)

    def test_set_rejects_unknown_provider(self):
        result = self._run("set", "--build", "unknown:model")

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown provider", result.stderr)


if __name__ == "__main__":
    unittest.main()
