import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestFrontDoor(unittest.TestCase):
    def test_help_lists_new_helper_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            os.makedirs(home)
            env = os.environ.copy()
            env["HOME"] = home
            result = subprocess.run(
                ["bash", os.path.join(ROOT, "bin", "cadence"), "help"],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("bakeoff", result.stdout)
        self.assertIn("labels init|list|ensure", result.stdout)
        self.assertIn("inspect", result.stdout)
        self.assertIn("provider CLIs", result.stdout)
        self.assertIn("providers roles|show|set|help", result.stdout)
        self.assertIn("prompt render", result.stdout)
        self.assertIn("tasks <args>", result.stdout)

    def test_inspect_runs_read_only_status_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            root = os.path.join(tmp, "cadence")
            bin_dir = os.path.join(tmp, "bin")
            state = os.path.join(tmp, "state")
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "engine", "scripts"))
            os.makedirs(os.path.join(root, "engine", "schedule"))
            os.makedirs(bin_dir)
            os.makedirs(state)
            shutil.copy(os.path.join(ROOT, "bin", "cadence"),
                        os.path.join(root, "bin", "cadence"))
            shutil.copytree(os.path.join(ROOT, "engine", "lib"),
                            os.path.join(root, "engine", "lib"))
            self._write_exe(os.path.join(root, "engine", "scripts", "doctor.sh"),
                            "#!/bin/sh\necho doctor-ok\n")
            self._write_exe(os.path.join(root, "engine", "scripts", "status.sh"),
                            "#!/bin/sh\necho status-ok\n")
            self._write_exe(os.path.join(root, "engine", "scripts", "autonomous.sh"),
                            "#!/bin/sh\necho autonomous-ok\n")
            self._write_exe(os.path.join(root, "engine", "scripts", "schedule.sh"),
                            "#!/bin/sh\necho schedule-ok\n")
            self._write_exe(os.path.join(root, "engine", "schedule", "cli.py"),
                            "#!/usr/bin/env python3\nprint('schedule-ok')\n")
            with open(os.path.join(root, ".env"), "w", encoding="utf-8") as f:
                f.write("CADENCE_STATE_DIR=%s\n" % state)
            env = os.environ.copy()
            env.update({"HOME": home, "PATH": bin_dir + os.pathsep + env.get("PATH", "")})

            result = subprocess.run(
                ["bash", os.path.join(root, "bin", "cadence"), "inspect"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("doctor-ok", result.stdout)
        self.assertIn("status-ok", result.stdout)
        self.assertIn("autonomous-ok", result.stdout)
        self.assertIn("schedule-ok", result.stdout)

    def test_config_option_selects_project_config_before_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            root = os.path.join(tmp, "cadence-engine")
            project = os.path.join(root, "app")
            state = os.path.join(tmp, "state")
            os.makedirs(home)
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "engine", "lib"))
            os.makedirs(os.path.join(root, "engine", "scripts"))
            os.makedirs(os.path.join(project, "cadence"))
            shutil.copy(os.path.join(ROOT, "bin", "cadence"), os.path.join(root, "bin", "cadence"))
            shutil.copytree(os.path.join(ROOT, "engine", "lib"), os.path.join(root, "engine", "lib"), dirs_exist_ok=True)
            self._write_exe(os.path.join(root, "engine", "scripts", "status.sh"), "#!/bin/sh\necho \"$CADENCE_STATE_DIR|$CADENCE_CONFIG\"\n")
            config_path = os.path.join(project, "cadence", ".env")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("CADENCE_STATE_DIR=%s\n" % state)
            env = os.environ.copy()
            env["HOME"] = home
            relative_config_path = os.path.join("app", "cadence", ".env")

            result = subprocess.run(
                ["bash", os.path.join(root, "bin", "cadence"), "--config", relative_config_path, "status"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("%s|%s" % (state, os.path.realpath(os.path.join(root, relative_config_path))), result.stdout)

    def test_profile_option_selects_named_config_before_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            root = os.path.join(tmp, "cadence-engine")
            project = os.path.join(root, "app")
            state = os.path.join(tmp, "state")
            os.makedirs(home)
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "engine", "lib"))
            os.makedirs(os.path.join(root, "engine", "scripts"))
            os.makedirs(os.path.join(root, "profiles"))
            os.makedirs(os.path.join(project, "cadence"))
            shutil.copy(os.path.join(ROOT, "bin", "cadence"), os.path.join(root, "bin", "cadence"))
            shutil.copytree(os.path.join(ROOT, "engine", "lib"), os.path.join(root, "engine", "lib"), dirs_exist_ok=True)
            self._write_exe(os.path.join(root, "engine", "scripts", "status.sh"), "#!/bin/sh\necho \"$CADENCE_STATE_DIR|$CADENCE_CONFIG\"\n")
            config_path = os.path.join(project, "cadence", ".env")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("CADENCE_STATE_DIR=%s\n" % state)
            with open(os.path.join(root, "profiles", "mpw"), "w", encoding="utf-8") as f:
                f.write("# profile alias\n%s\n" % config_path)
            env = os.environ.copy()
            env["HOME"] = home

            result = subprocess.run(
                ["bash", os.path.join(root, "bin", "cadence"), "--profile", "mpw", "status"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("%s|%s" % (state, os.path.abspath(config_path)), result.stdout)

    def test_profile_option_reports_missing_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            root = os.path.join(tmp, "cadence-engine")
            os.makedirs(home)
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "engine", "lib"))
            shutil.copy(os.path.join(ROOT, "bin", "cadence"), os.path.join(root, "bin", "cadence"))
            shutil.copytree(os.path.join(ROOT, "engine", "lib"), os.path.join(root, "engine", "lib"), dirs_exist_ok=True)
            env = os.environ.copy()
            env["HOME"] = home

            result = subprocess.run(
                ["bash", os.path.join(root, "bin", "cadence"), "--profile", "missing", "status"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown profile: missing", result.stderr)

    def test_selected_config_path_survives_values_inside_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            root = os.path.join(tmp, "cadence-engine")
            project = os.path.join(root, "app")
            state = os.path.join(tmp, "state")
            os.makedirs(home)
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "engine", "lib"))
            os.makedirs(os.path.join(root, "engine", "scripts"))
            os.makedirs(os.path.join(project, "cadence"))
            shutil.copy(os.path.join(ROOT, "bin", "cadence"), os.path.join(root, "bin", "cadence"))
            shutil.copytree(os.path.join(ROOT, "engine", "lib"), os.path.join(root, "engine", "lib"), dirs_exist_ok=True)
            self._write_exe(os.path.join(root, "engine", "scripts", "status.sh"),
                            "#!/bin/sh\necho \"$CADENCE_STATE_DIR|$CADENCE_CONFIG\"\n")
            config_path = os.path.join(project, "cadence", ".env")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("CADENCE_CONFIG=/tmp/wrong\nCADENCE_STATE_DIR=%s\n" % state)
            env = os.environ.copy()
            env["HOME"] = home
            env.pop("CADENCE_CONFIG", None)

            result = subprocess.run(
                ["bash", os.path.join(root, "bin", "cadence"), "--config", config_path, "status"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("%s|%s" % (state, os.path.abspath(config_path)), result.stdout)
        self.assertNotIn("/tmp/wrong", result.stdout)

    def test_project_cadence_env_is_auto_detected_from_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            root = os.path.join(tmp, "cadence-engine")
            project = os.path.join(tmp, "app")
            state = os.path.join(tmp, "state")
            os.makedirs(home)
            os.makedirs(os.path.join(root, "bin"))
            os.makedirs(os.path.join(root, "engine", "lib"))
            os.makedirs(os.path.join(root, "engine", "scripts"))
            os.makedirs(os.path.join(project, "cadence"))
            shutil.copy(os.path.join(ROOT, "bin", "cadence"), os.path.join(root, "bin", "cadence"))
            shutil.copytree(os.path.join(ROOT, "engine", "lib"), os.path.join(root, "engine", "lib"), dirs_exist_ok=True)
            self._write_exe(os.path.join(root, "engine", "scripts", "status.sh"), "#!/bin/sh\necho \"$CADENCE_STATE_DIR|$CADENCE_CONFIG\"\n")
            config_path = os.path.join(project, "cadence", ".env")
            with open(config_path, "w", encoding="utf-8") as f:
                f.write("CADENCE_STATE_DIR=%s\n" % state)
            env = os.environ.copy()
            env["HOME"] = home

            result = subprocess.run(
                ["bash", os.path.join(root, "bin", "cadence"), "status"],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("%s|%s" % (state, os.path.realpath(config_path)), result.stdout)

    def _write_exe(self, path, body):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | 0o100)


if __name__ == "__main__":
    unittest.main()
