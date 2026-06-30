import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "schedule_cli", os.path.join(os.path.dirname(__file__), "..", "schedule", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class TestParseSpec(unittest.TestCase):
    def test_hourly_at_minute(self):
        self.assertEqual(cli.parse_spec(":15"), ("minute", 15))
        self.assertEqual(cli.parse_spec(":0"), ("minute", 0))
        self.assertEqual(cli.parse_spec(":05"), ("minute", 5))

    def test_every_n_hours_default_minute_zero(self):
        self.assertEqual(cli.parse_spec("4h"), ("hours", (4, 0)))
        self.assertEqual(cli.parse_spec("3h"), ("hours", (3, 0)))

    def test_every_n_hours_with_minute(self):
        self.assertEqual(cli.parse_spec("4h@30"), ("hours", (4, 30)))
        self.assertEqual(cli.parse_spec("24h@5"), ("hours", (24, 5)))

    def test_minute_out_of_range_rejected(self):
        for bad in (":60", "4h@60"):
            with self.assertRaises(ValueError):
                cli.parse_spec(bad)

    def test_hours_out_of_range_rejected(self):
        for bad in ("0h", "25h"):
            with self.assertRaises(ValueError):
                cli.parse_spec(bad)

    def test_garbage_rejected(self):
        for bad in ("", "15", "30m", "30m@5", "h", ":", "3 hours"):
            with self.assertRaises(ValueError):
                cli.parse_spec(bad)


class TestRender(unittest.TestCase):
    def test_describe(self):
        self.assertEqual(cli.describe(":00"), "hourly at :00")
        self.assertEqual(cli.describe("4h@30"), "every 4h at :30")
        self.assertEqual(cli.describe("3h"), "every 3h at :00")

    def test_hours_for(self):
        self.assertEqual(cli._hours_for(4), [0, 4, 8, 12, 16, 20])
        self.assertEqual(cli._hours_for(24), [0])

    def test_schedule_xml_minute_has_no_hour(self):
        xml = cli._schedule_xml(":30")
        self.assertIn("<key>Minute</key><integer>30</integer>", xml)
        self.assertNotIn("<key>Hour</key>", xml)
        self.assertNotIn("<array>", xml)

    def test_schedule_xml_every_4h_is_aligned_array(self):
        xml = cli._schedule_xml("4h@30")
        self.assertIn("<array>", xml)
        self.assertIn("<key>Hour</key><integer>0</integer>", xml)
        self.assertIn("<key>Hour</key><integer>20</integer>", xml)
        self.assertIn("<key>Minute</key><integer>30</integer>", xml)
        self.assertEqual(xml.count("<dict>"), 6)  # 0,4,8,12,16,20

    def test_schedule_xml_once_daily_is_single_dict(self):
        xml = cli._schedule_xml("24h@5")
        self.assertNotIn("<array>", xml)
        self.assertIn("<key>Hour</key><integer>0</integer>", xml)

    def test_render_plist_loop(self):
        out = cli.render_plist("build", "/home", "/state", "4h@30")
        self.assertIn("<string>com.cadence.loop-build</string>", out)
        self.assertIn("/home/engine/scripts/run-loop.sh", out)
        self.assertIn("<string>build</string>", out)
        self.assertIn("/state/logs/build.launchd.log", out)
        self.assertIn("<false/>", out)  # RunAtLoad

    def test_render_plist_conduct_calls_cadence(self):
        out = cli.render_plist("conduct", "/home", "/state", "4h@50")
        self.assertIn("/home/bin/cadence", out)
        self.assertIn("<string>conduct</string>", out)

    def test_spec_for_env_override_and_default(self):
        self.assertEqual(cli.spec_for("build", {"SCHED_BUILD": "4h@30"}), "4h@30")
        self.assertEqual(cli.spec_for("build", {}), ":30")


class TestScheduleApplyScript(unittest.TestCase):
    def test_apply_rejects_project_local_config_until_launchd_supports_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            app = os.path.join(tmp, "app")
            config_dir = os.path.join(app, "cadence")
            os.makedirs(os.path.join(home, "Library", "LaunchAgents"))
            os.makedirs(config_dir)
            config = os.path.join(config_dir, ".env")
            with open(config, "w", encoding="utf-8") as f:
                f.write("CADENCE_STATE_DIR=%s\n" % os.path.join(tmp, "state"))
            env = os.environ.copy()
            env.update({
                "HOME": home,
                "CADENCE_CONFIG": config,
            })

            result = subprocess.run(
                ["bash", os.path.join(os.path.dirname(__file__), "..", "scripts", "schedule.sh"), "apply"],
                cwd=app,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("launchd scheduling currently requires", result.stderr)

    def test_apply_leaves_existing_plist_intact_when_render_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            bin_dir = os.path.join(tmp, "bin")
            launch_agents = os.path.join(home, "Library", "LaunchAgents")
            os.makedirs(launch_agents)
            os.makedirs(bin_dir)
            plist = os.path.join(launch_agents, "com.cadence.loop-triage.plist")
            with open(plist, "w", encoding="utf-8") as f:
                f.write("original plist")

            self._write_exe(os.path.join(bin_dir, "python3"), f"""#!/bin/sh
if [ "$2" = "check" ]; then
  exit 0
fi
if [ "$2" = "render" ]; then
  printf '<partial plist'
  exit 1
fi
exec {sys.executable} "$@"
""")
            self._write_exe(os.path.join(bin_dir, "launchctl"), "#!/bin/sh\nexit 0\n")
            env = os.environ.copy()
            env.update({
                "HOME": home,
                "PATH": bin_dir + os.pathsep + env.get("PATH", ""),
                "CADENCE_STATE_DIR": os.path.join(tmp, "state"),
            })

            result = subprocess.run(
                ["bash", os.path.join(os.path.dirname(__file__), "..", "scripts", "schedule.sh"), "apply"],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )

            self.assertNotEqual(result.returncode, 0)
            with open(plist, encoding="utf-8") as f:
                self.assertEqual(f.read(), "original plist")

    def _write_exe(self, path, body):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
