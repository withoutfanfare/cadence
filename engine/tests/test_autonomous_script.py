import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestAutonomousScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.bin = os.path.join(self.tmp.name, "bin")
        self.root = os.path.join(self.tmp.name, "cadence")
        self.launch_agents = os.path.join(self.home, "Library", "LaunchAgents")
        os.makedirs(os.path.join(self.root, "engine"))
        os.makedirs(self.launch_agents)
        os.makedirs(self.bin)
        shutil.copytree(os.path.join(ROOT, "engine", "scripts"),
                        os.path.join(self.root, "engine", "scripts"))
        shutil.copytree(os.path.join(ROOT, "engine", "lib"),
                        os.path.join(self.root, "engine", "lib"))
        with open(os.path.join(self.root, ".env"), "w", encoding="utf-8") as f:
            f.write("AUTONOMOUS=0\nCADENCE_STATE_DIR=%s\n" %
                    os.path.join(self.tmp.name, "state"))
        self.script = os.path.join(self.root, "engine", "scripts", "autonomous.sh")

    def tearDown(self):
        self.tmp.cleanup()

    def test_on_leaves_existing_plist_intact_when_render_fails(self):
        advance_plist = os.path.join(self.launch_agents, "com.cadence.loop-advance.plist")
        with open(advance_plist, "w", encoding="utf-8") as f:
            f.write("original advance plist")
        real_python = sys.executable
        self._write_exe("python3", f"""#!/bin/sh
if [ "$2" = "check" ]; then
  exit 0
fi
if [ "$2" = "render" ]; then
  printf '<partial plist'
  exit 1
fi
exec {real_python} "$@"
""")
        self._write_exe("launchctl", "#!/bin/sh\nexit 0\n")

        result = subprocess.run(
            ["bash", self.script, "on"],
            cwd=self.root,
            env=self._env(),
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertNotEqual(result.returncode, 0)
        with open(advance_plist, encoding="utf-8") as f:
            self.assertEqual(f.read(), "original advance plist")

    def test_on_rejects_project_local_config_until_launchd_supports_it(self):
        app = os.path.join(self.tmp.name, "app")
        config_dir = os.path.join(app, "cadence")
        config = os.path.join(config_dir, ".env")
        os.makedirs(config_dir)
        with open(config, "w", encoding="utf-8") as f:
            f.write("AUTONOMOUS=0\nCADENCE_STATE_DIR=%s\n" % os.path.join(self.tmp.name, "state"))
        env = self._env()
        env["CADENCE_CONFIG"] = config

        result = subprocess.run(
            ["bash", self.script, "on"],
            cwd=app,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("launchd scheduling currently requires", result.stderr)
        self.assertIn("active config is", result.stderr)
        self.assertIn("project-local cadence/.env", result.stderr)
        with open(config, encoding="utf-8") as f:
            self.assertIn("AUTONOMOUS=0\n", f.read())

    def test_off_writes_to_cadence_config_when_set(self):
        app = os.path.join(self.tmp.name, "app")
        config_dir = os.path.join(app, "cadence")
        config = os.path.join(config_dir, ".env")
        os.makedirs(config_dir)
        with open(config, "w", encoding="utf-8") as f:
            f.write("AUTONOMOUS=on\nCADENCE_STATE_DIR=%s\n" % os.path.join(self.tmp.name, "state"))
        env = self._env()
        env["CADENCE_CONFIG"] = config

        result = subprocess.run(
            ["bash", self.script, "off"],
            cwd=app,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(config, encoding="utf-8") as f:
            self.assertIn("AUTONOMOUS=0\n", f.read())

    def _env(self):
        env = os.environ.copy()
        env.update({
            "HOME": self.home,
            "PATH": self.bin + os.pathsep + env.get("PATH", ""),
        })
        return env

    def _write_exe(self, name, body):
        path = os.path.join(self.bin, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
