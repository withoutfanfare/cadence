import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]


class TestDoctorProviderChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "cadence"
        self.home = pathlib.Path(self.tmp.name) / "home"
        self.bin = pathlib.Path(self.tmp.name) / "bin"
        self.runner_bin = pathlib.Path(self.tmp.name) / "runner-bin"
        self.state = pathlib.Path(self.tmp.name) / "state"
        (self.root / "engine" / "scripts").mkdir(parents=True)
        (self.root / "engine" / "lib").mkdir(parents=True)
        (self.root / "engine" / "linear").mkdir(parents=True)
        (self.root / "engine" / "tasks").mkdir(parents=True)
        shutil.copy(ROOT / "engine" / "tasks" / "cli.py", self.root / "engine" / "tasks" / "cli.py")
        self.home.mkdir()
        self.bin.mkdir()
        self.runner_bin.mkdir()
        self.state.mkdir()
        (self.root / ".env").write_text("", encoding="utf-8")
        shutil.copy(ROOT / "engine" / "scripts" / "doctor.sh", self.root / "engine" / "scripts" / "doctor.sh")
        shutil.copytree(ROOT / "engine" / "lib", self.root / "engine" / "lib", dirs_exist_ok=True)
        self._write_linear_stub()
        for name in ("claude", "codex", "kimi", "opencode", "gh"):
            self._write_exe(self.bin, name, "#!/bin/sh\nexit 0\n")
            self._write_exe(self.runner_bin, name, "#!/bin/sh\nexit 0\n")

    def tearDown(self):
        self.tmp.cleanup()

    def _write_exe(self, directory, name, body):
        path = directory / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def _write_linear_stub(self):
        (self.root / "engine" / "linear" / "cli.py").write_text(
            """#!/usr/bin/env python3
import json
import sys

AGENT_LABELS = ["agent:spec", "agent:build"]

if sys.argv[1:] == ["teams"]:
    print(json.dumps([{"id": "team-1", "name": "Team"}]))
elif sys.argv[1:] == ["labels-list"]:
    print(json.dumps([{"name": "agent:spec"}, {"name": "agent:build"}]))
else:
    raise SystemExit(2)
""",
            encoding="utf-8",
        )

    def _run(self, extra_env):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": str(self.bin) + os.pathsep + env.get("PATH", ""),
                "RUNNER_PATH_PREPEND": str(self.runner_bin),
                "CADENCE_STATE_DIR": str(self.state),
                "LINEAR_API_KEY": "token",
                "LINEAR_TEAM_ID": "team-1",
                "LINEAR_TEAM_NAME": "Team",
                "LINEAR_PROJECT_ID": "project-1",
                "LINEAR_ASSIGNEE_ID": "user-1",
                "PROJECT_DIR": str(self.root),
                "WORKTREE_BASE": str(self.root / "worktrees"),
                "NOTIFY": "off",
            }
        )
        env.update(extra_env)
        return subprocess.run(
            ["bash", str(self.root / "engine" / "scripts" / "doctor.sh")],
            cwd=self.root,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

    def test_accepts_configured_orchestrator_and_reviewer_providers(self):
        result = self._run(
            {
                "ORCHESTRATOR_TRIAGE": "codex:gpt-test",
                "ORCHESTRATOR_SPEC": "kimi:k2",
                "ORCHESTRATOR_BUILD": "opencode:zai-coding-plan/glm-5.2",
                "ORCHESTRATOR_REVISE": "claude:sonnet",
                "ORCHESTRATOR_ADVANCE": "codex:gpt-test",
                "REVIEW_PROVIDER": "claude",
                "REVIEW_MODEL": "opus",
            }
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("triage orchestrator provider 'codex' found", result.stdout)
        self.assertIn("spec orchestrator provider 'kimi' found", result.stdout)
        self.assertIn("build orchestrator provider 'opencode' found", result.stdout)
        self.assertIn("advance orchestrator provider 'codex' found", result.stdout)
        self.assertIn("reviewer provider 'claude' found", result.stdout)

    def _write_kimi_config(self, *models):
        cfg = self.home / ".kimi-code" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(f'[models."{m}"]\nmax_context_size = 262144\n\n' for m in models)
        cfg.write_text(body, encoding="utf-8")

    def test_rejects_kimi_model_absent_from_config(self):
        # A provider CLI on PATH is not enough: kimi:k2 must fail when kimi has no
        # k2 model, mirroring the real run-time failure.
        self._write_kimi_config("kimi-code/kimi-for-coding")
        result = self._run({"ORCHESTRATOR_TRIAGE": "kimi:k2"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("triage orchestrator model 'k2' not configured in kimi", result.stdout)

    def test_accepts_kimi_model_present_in_config(self):
        self._write_kimi_config("kimi-code/kimi-for-coding")
        result = self._run({"ORCHESTRATOR_TRIAGE": "kimi:kimi-code/kimi-for-coding"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "triage orchestrator model 'kimi-code/kimi-for-coding' configured in kimi",
            result.stdout)

    def test_missing_kimi_config_warns_not_fails(self):
        # No ~/.kimi-code/config.toml (fresh machine): can't validate, must not fail.
        result = self._run({"ORCHESTRATOR_TRIAGE": "kimi:k2"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cannot validate", result.stdout)

    def test_rejects_orchestrator_provider_missing_from_runner_path(self):
        (self.runner_bin / "claude").unlink()

        result = self._run({"ORCHESTRATOR_TRIAGE": "claude:sonnet"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("triage orchestrator provider 'claude' not on PATH", result.stdout)

    def test_reports_active_cadence_config_path(self):
        config = pathlib.Path(self.tmp.name) / "app" / "cadence" / ".env"
        config.parent.mkdir(parents=True)
        config.write_text(f"CADENCE_STATE_DIR={self.state}\n", encoding="utf-8")

        result = self._run({"CADENCE_CONFIG": str(config)})

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"config file {config}", result.stdout)

    def test_file_backend_skips_linear_checks_and_reports_task_file(self):
        task_file = self.root / "cadence" / "tasks.md"
        task_file.parent.mkdir()
        task_file.write_text("# Tasks\n", encoding="utf-8")

        result = self._run(
            {
                "TASK_BACKEND": "file",
                "LINEAR_API_KEY": "",
                "LINEAR_TEAM_ID": "",
                "LINEAR_TEAM_NAME": "",
                "LINEAR_PROJECT_ID": "",
                "LINEAR_ASSIGNEE_ID": "",
            }
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"task backend file; task file {task_file}", result.stdout)
        self.assertNotIn("LINEAR_API_KEY not set", result.stdout)
        self.assertNotIn("LINEAR_PROJECT_ID not set", result.stdout)

    def test_file_backend_fails_on_a_malformed_task_file(self):
        task_file = self.root / "cadence" / "tasks.md"
        task_file.parent.mkdir()
        task_file.write_text("# Tasks\n\n## SR-1 no colon\nstatus: open\n", encoding="utf-8")

        result = self._run({"TASK_BACKEND": "file", "LINEAR_API_KEY": ""})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has format problems", result.stdout)
        self.assertIn("malformed task header", result.stdout)

    def test_file_backend_reports_validator_run_failure_distinctly(self):
        # If the validator itself cannot run (exit >= 2), doctor must say so
        # rather than blaming the task file's format.
        task_file = self.root / "cadence" / "tasks.md"
        task_file.parent.mkdir()
        task_file.write_text("# Tasks\n", encoding="utf-8")
        (self.root / "engine" / "tasks" / "cli.py").unlink()

        result = self._run({"TASK_BACKEND": "file", "LINEAR_API_KEY": ""})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not run task-file validator", result.stdout)
        self.assertNotIn("has format problems", result.stdout)

    def test_requires_default_claude_implementer_on_runner_path(self):
        (self.runner_bin / "claude").unlink()

        result = self._run(
            {
                "ORCHESTRATOR_TRIAGE": "codex:gpt-test",
                "ORCHESTRATOR_SPEC": "opencode:zai-coding-plan/glm-5.2",
                "ORCHESTRATOR_BUILD": "codex:gpt-test",
                "ORCHESTRATOR_REVISE": "opencode:zai-coding-plan/glm-5.2",
                "ORCHESTRATOR_ADVANCE": "codex:gpt-test",
                "REVIEW_PROVIDER": "codex",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("implementer 'claude' not on PATH", result.stdout)

    def test_rejects_unknown_orchestrator_provider(self):
        result = self._run({"ORCHESTRATOR_BUILD": "unknown:model"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("build orchestrator provider 'unknown' invalid", result.stdout)

    def test_stale_gate_with_missing_executable_is_caught(self):
        # A gate whose leading executable is absent (wrong toolchain for this repo)
        # must fail doctor now, not wait to abort a build days later.
        result = self._run({"GATE_TEST": "no-such-tool-xyz test:filter"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no-such-tool-xyz test:filter", result.stdout)
        self.assertIn("'no-such-tool-xyz' not on PATH", result.stdout)

    def test_blank_gate_skipped_and_resolvable_gate_shown(self):
        # Blank gate = skip (valid). A gate whose leading executable resolves is
        # shown (doctor can't verify the subcommand) and does not fail.
        self._write_exe(self.runner_bin, "mytool", "#!/bin/sh\nexit 0\n")

        result = self._run({"GATE_LINT": "mytool --all", "GATE_TEST": ""})

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GATE_LINT: mytool --all", result.stdout)
        self.assertIn("GATE_TEST: blank (skipped)", result.stdout)


if __name__ == "__main__":
    unittest.main()
