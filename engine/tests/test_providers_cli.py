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
        return self._run_with_env({}, *args)

    def _run_with_env(self, extra_env, *args):
        env = os.environ.copy()
        # Hermetic: drop any real config pointer and run from the temp dir so
        # the <cwd>/cadence/.env fallback cannot find the repo's live config.
        env.pop("CADENCE_CONFIG", None)
        env.update({"HOME": str(self.home), "CADENCE_HOME": str(self.cadence_home)})
        env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(self.script), *args],
            cwd=self.tmp.name,
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

    def test_set_writes_to_cadence_config_when_set(self):
        config = pathlib.Path(self.tmp.name) / "app" / "cadence" / ".env"
        config.parent.mkdir(parents=True)
        config.write_text("BUILD_IMPLEMENTER=claude\n", encoding="utf-8")

        result = self._run_with_env({"CADENCE_CONFIG": str(config)}, "set", "--implementer", "codex")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BUILD_IMPLEMENTER=codex\n", config.read_text(encoding="utf-8"))
        self.assertFalse(self.env_path.exists())

    def test_set_rejects_unknown_provider(self):
        result = self._run("set", "--build", "unknown:model")

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown provider", result.stderr)

    def test_help_prints_provider_manual(self):
        result = self._run("help")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Provider Roles", result.stdout)
        self.assertIn("MODEL_* values are model names only", result.stdout)
        self.assertIn("BUILD_IMPLEMENTER is provider-only", result.stdout)
        self.assertIn("cadence providers set --build codex:gpt-5.4 --implementer codex", result.stdout)

    def test_man_alias_prints_provider_manual(self):
        result = self._run("man")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Provider Roles", result.stdout)

    def _write_registry(self, content: str) -> pathlib.Path:
        path = pathlib.Path(self.tmp.name) / "agents.json"
        path.write_text(content, encoding="utf-8")
        return path

    def test_registry_lists_agents_with_models_and_support(self):
        registry = self._write_registry(
            '{"registry_version": 1, "agents": {'
            '"claude": {"command": "claude", "models": ['
            '{"id": "opus-4.6"}, {"id": "sonnet-4.6"}]},'
            '"gemini": {"command": "gemini", "models": [{"id": "gemini-3-pro-preview"}]}'
            "}}"
        )
        result = self._run_with_env({"AGENT_REGISTRY_FILE": str(registry)}, "registry")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude", result.stdout)
        self.assertIn("opus-4.6, sonnet-4.6", result.stdout)
        self.assertIn("gemini", result.stdout)
        # gemini exists on the machine but Cadence's runtime cannot drive it
        gemini_row = next(l for l in result.stdout.splitlines() if l.startswith("gemini"))
        self.assertIn("no", gemini_row)

    def test_registry_reports_missing_file(self):
        missing = pathlib.Path(self.tmp.name) / "absent.json"
        result = self._run_with_env({"AGENT_REGISTRY_FILE": str(missing)}, "registry")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No shared agent registry", result.stdout)

    def test_set_rejects_provider_absent_from_registry(self):
        registry = self._write_registry(
            '{"registry_version": 1, "agents": {"claude": {"command": "claude"}}}'
        )
        result = self._run_with_env(
            {"AGENT_REGISTRY_FILE": str(registry)}, "set", "--build", "codex:gpt-5.4"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown provider: codex", result.stderr)

    def test_malformed_registry_falls_back_to_builtin_providers(self):
        registry = self._write_registry("not json at all")
        result = self._run_with_env(
            {"AGENT_REGISTRY_FILE": str(registry)}, "set", "--build", "codex:gpt-5.4"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ORCHESTRATOR_BUILD=codex:gpt-5.4", result.stdout)

    def test_wrong_registry_version_falls_back(self):
        registry = self._write_registry(
            '{"registry_version": 2, "agents": {"claude": {"command": "claude"}}}'
        )
        result = self._run_with_env(
            {"AGENT_REGISTRY_FILE": str(registry)}, "set", "--build", "codex:gpt-5.4"
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
