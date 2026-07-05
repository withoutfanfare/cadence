import importlib.util
import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone

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


class TestNextRun(unittest.TestCase):
    def _at(self, h, m):
        return datetime(2026, 7, 2, h, m, tzinfo=timezone.utc)

    def test_hourly_next_this_hour(self):
        # 14:00 with ':05' -> 14:05 same hour
        self.assertEqual(cli.next_run(":05", self._at(14, 0)), self._at(14, 5))

    def test_hourly_rolls_to_next_hour_when_past(self):
        # 14:10 with ':05' -> 15:05
        self.assertEqual(cli.next_run(":05", self._at(14, 10)), self._at(15, 5))

    def test_every_n_hours_lands_on_multiple(self):
        # 14:00 with '4h@30' -> next 4h-boundary hour at :30 is 16:30
        self.assertEqual(cli.next_run("4h@30", self._at(14, 0)), self._at(16, 30))

    def test_off_or_invalid_returns_none(self):
        self.assertIsNone(cli.next_run("off", self._at(14, 0)))
        self.assertIsNone(cli.next_run("garbage", self._at(14, 0)))

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
        self.assertEqual(cli.describe("off"), "off")

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

    def test_render_scheduler_plist_calls_schedule_tick(self):
        out = cli.render_scheduler_plist("/home", "/state", 300)
        self.assertIn("<string>com.cadence.scheduler</string>", out)
        self.assertIn("/home/bin/cadence", out)
        self.assertIn("<string>schedule</string>", out)
        self.assertIn("<string>tick</string>", out)
        self.assertIn("<key>StartInterval</key><integer>300</integer>", out)
        self.assertIn("/state/logs/scheduler.launchd.log", out)

    def test_spec_for_env_override_and_default(self):
        self.assertEqual(cli.spec_for("build", {"SCHED_BUILD": "4h@30"}), "4h@30")
        self.assertEqual(cli.spec_for("build", {}), ":30")


class TestSchedulerTick(unittest.TestCase):
    def test_tick_runs_due_enabled_project_once_and_marks_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "app")
            config_dir = os.path.join(project, "cadence")
            state = os.path.join(tmp, "state")
            registry = os.path.join(tmp, "projects.txt")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n" % state)
            with open(registry, "w", encoding="utf-8") as f:
                f.write(project + "\n")
            calls = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                calls.append((cmd, cwd, env))
                return type("Proc", (), {"returncode": 0})()

            env = {
                "CADENCE_HOME": "/cadence",
                "CADENCE_PROJECTS_FILE": registry,
                "CADENCE_SCHEDULER_MAX_RUNS": "1",
            }
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.tick(env, now=now, run=fake_run), 0)
                self.assertEqual(cli.tick(env, now=now, run=fake_run), 0)

        self.assertEqual(len(calls), 1)
        cmd, cwd, run_env = calls[0]
        self.assertEqual(cmd, ["/cadence/bin/cadence", "--config",
                               os.path.join(config_dir, ".env"), "run", "triage"])
        self.assertEqual(cwd, project)
        self.assertEqual(run_env["CADENCE_CONFIG"], os.path.join(config_dir, ".env"))

    def test_tick_bounds_simultaneous_runs_to_the_concurrency_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            projects = []
            for name in ("a", "b", "c"):
                config_dir = os.path.join(tmp, name, "cadence")
                os.makedirs(config_dir)
                with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                    f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n"
                            % os.path.join(tmp, name, "state"))
                projects.append(os.path.join(tmp, name))
            with open(registry, "w", encoding="utf-8") as f:
                f.write("\n".join(projects) + "\n")

            lock = threading.Lock()
            seen = {"calls": 0, "inflight": 0, "high": 0}
            # The first two runs must be in flight at the same moment to pass the
            # barrier — deterministic proof of parallel dispatch. A serial
            # implementation deadlocks on it until the 5s safety deadline breaks
            # the barrier and fails the test.
            overlap = threading.Barrier(2)

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                with lock:
                    seen["calls"] += 1
                    me = seen["calls"]
                    seen["inflight"] += 1
                    seen["high"] = max(seen["high"], seen["inflight"])
                if me <= 2:
                    overlap.wait(timeout=5)
                with lock:
                    seen["inflight"] -= 1
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "3",
                   "CADENCE_SCHEDULER_CONCURRENCY": "2"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = cli.tick(env, now=now, run=fake_run)

            self.assertEqual(rc, 0)
            self.assertEqual(seen["calls"], 3)   # every pick ran
            self.assertEqual(seen["high"], 2)    # parallel, but never above the cap

    def test_tick_dispatch_admission_follows_least_recently_served_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")

            def make(name):
                config_dir = os.path.join(tmp, name, "cadence")
                state = os.path.join(tmp, name, "state")
                os.makedirs(config_dir)
                with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                    f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n" % state)
                return os.path.join(tmp, name), state

            a, sa = make("a")
            b, sb = make("b")
            c, _sc = make("c")  # never served — must lead the tick
            # Stale slot keys keep both projects due; utime pins served order.
            cli._mark_ran(sa, "triage", "triage:older-slot")
            os.utime(os.path.join(sa, "scheduler", "triage.last"), (100, 100))
            cli._mark_ran(sb, "triage", "triage:newer-slot")
            os.utime(os.path.join(sb, "scheduler", "triage.last"), (200, 200))
            with open(registry, "w", encoding="utf-8") as f:
                f.write("\n".join([a, b, c]) + "\n")

            served = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                served.append(cwd)
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "3",
                   # Width 1 serialises dispatch so call order == admission order.
                   "CADENCE_SCHEDULER_CONCURRENCY": "1"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                cli.tick(env, now=now, run=fake_run)

            # Never-served first, then oldest-served; registry order breaks ties only.
            self.assertEqual(served, [c, a, b])

    def test_tick_launches_at_most_one_run_per_project_per_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "app")
            config_dir = os.path.join(project, "cadence")
            registry = os.path.join(tmp, "projects.txt")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                # Two stages due in the same window, budget for three runs —
                # the project must still get exactly one.
                f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\nSCHED_SPEC=:00\n"
                        % os.path.join(tmp, "state"))
            with open(registry, "w", encoding="utf-8") as f:
                f.write(project + "\n")
            calls = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                calls.append(cmd)
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "3"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                cli.tick(env, now=now, run=fake_run)

            self.assertEqual(len(calls), 1)
            self.assertIn("triage", calls[0])  # the first due stage in JOBS order

    def test_tick_passes_run_timeout_through_the_run_seam(self):
        # (raw env value, timeout the run seam must receive)
        for raw, expected in (("120", 120), ("0", None), (None, 3600)):
            with tempfile.TemporaryDirectory() as tmp:
                project = os.path.join(tmp, "app")
                config_dir = os.path.join(project, "cadence")
                registry = os.path.join(tmp, "projects.txt")
                os.makedirs(config_dir)
                with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                    f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n"
                            % os.path.join(tmp, "state"))
                with open(registry, "w", encoding="utf-8") as f:
                    f.write(project + "\n")
                seen = []

                def fake_run(cmd, cwd=None, env=None, timeout=None):
                    seen.append(timeout)
                    return type("Proc", (), {"returncode": 0})()

                env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry}
                if raw is not None:
                    env["CADENCE_SCHEDULER_RUN_TIMEOUT"] = raw
                now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    cli.tick(env, now=now, run=fake_run)
                self.assertEqual(seen, [expected])

    def test_tick_serves_least_recently_served_project_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")

            def make(name):
                config_dir = os.path.join(tmp, name, "cadence")
                state = os.path.join(tmp, name, "state")
                os.makedirs(config_dir)
                with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                    f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n" % state)
                return os.path.join(tmp, name), state

            first, s1 = make("first")     # earlier in the registry, served recently
            second, _s2 = make("second")  # later in the registry, never served
            cli._mark_ran(s1, "triage", "triage:earlier-slot")
            with open(registry, "w", encoding="utf-8") as f:
                f.write(first + "\n" + second + "\n")

            served = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                served.append(cwd)
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "1"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                cli.tick(env, now=now, run=fake_run)

            # Both are due, but the one run this tick is the never-served project —
            # fairness overrides registry order so it can't be permanently starved.
            self.assertEqual(served, [second])

    def test_tick_skips_projects_not_opted_into_scheduling(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "app")
            config_dir = os.path.join(project, "cadence")
            registry = os.path.join(tmp, "projects.txt")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                f.write("CADENCE_SCHEDULED=0\n")
            with open(registry, "w", encoding="utf-8") as f:
                f.write(project + "\n")

            def fake_run(*_args, **_kwargs):
                raise AssertionError("disabled project should not run")

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.tick(env, now=now, run=fake_run), 0)

    def test_status_warns_only_when_projects_share_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")

            def make(name, state):
                config_dir = os.path.join(tmp, name, "cadence")
                os.makedirs(config_dir)
                with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                    f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n" % state)
                return os.path.join(tmp, name)

            shared = os.path.join(tmp, "shared")
            own = os.path.join(tmp, "own")
            p1 = make("app1", shared)
            p2 = make("app2", shared)
            p3 = make("app3", own)
            with open(registry, "w", encoding="utf-8") as f:
                f.write(p1 + "\n" + p2 + "\n" + p3 + "\n")

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cli.print_status({"CADENCE_PROJECTS_FILE": registry})
            out = buf.getvalue()

            self.assertIn("share CADENCE_STATE_DIR", out)
            self.assertIn(shared, out)
            self.assertIn(p1, out)
            self.assertIn(p2, out)
            # The isolated project's state dir is never flagged.
            self.assertNotIn(own, out)

    def test_tick_survives_non_numeric_scheduler_ints(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "app")
            config_dir = os.path.join(project, "cadence")
            state = os.path.join(tmp, "state")
            registry = os.path.join(tmp, "projects.txt")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n" % state)
            with open(registry, "w", encoding="utf-8") as f:
                f.write(project + "\n")

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                return type("Proc", (), {"returncode": 0})()

            env = {
                "CADENCE_HOME": "/cadence",
                "CADENCE_PROJECTS_FILE": registry,
                "CADENCE_SCHEDULER_MAX_RUNS": "banana",
                "CADENCE_SCHEDULER_WINDOW_MINUTES": "oops",
            }
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            # A typo in either int must not crash the whole tick (it degrades).
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = cli.tick(env, now=now, run=fake_run)
            self.assertEqual(rc, 0)

    def test_two_stages_due_same_window_both_run_across_ticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = os.path.join(tmp, "app")
            config_dir = os.path.join(project, "cadence")
            state = os.path.join(tmp, "state")
            registry = os.path.join(tmp, "projects.txt")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                # spec shares triage's :00 slot — both are due in the same window.
                f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\nSCHED_SPEC=:00\n" % state)
            with open(registry, "w", encoding="utf-8") as f:
                f.write(project + "\n")

            calls = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                calls.append(cmd)
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "10"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            with contextlib.redirect_stdout(io.StringIO()):
                cli.tick(env, now=now, run=fake_run)
                cli.tick(env, now=now, run=fake_run)

        # Both due stages run (one per tick); neither starves the other.
        self.assertEqual(sorted(c[-1] for c in calls), ["spec", "triage"])

    def test_read_env_file_ignores_spaced_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, ".env")
            with open(cfg, "w", encoding="utf-8") as f:
                f.write("GOOD=ok\nCADENCE_STATE_DIR = /custom/path\nexport EXPORTED=yes\n")
            values = cli.read_env_file(cfg)
        self.assertEqual(values.get("GOOD"), "ok")
        self.assertEqual(values.get("EXPORTED"), "yes")
        # `KEY = value` is not a bash assignment, so the scheduler must skip it too.
        self.assertNotIn("CADENCE_STATE_DIR", values)

    def _two_project_registry(self, tmp, names):
        registry = os.path.join(tmp, "projects.txt")
        paths = []
        for name in names:
            config_dir = os.path.join(tmp, name, "cadence")
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, ".env"), "w", encoding="utf-8") as f:
                f.write("CADENCE_SCHEDULED=1\nCADENCE_STATE_DIR=%s\n"
                        % os.path.join(tmp, name, "state"))
            paths.append(os.path.join(tmp, name))
        with open(registry, "w", encoding="utf-8") as f:
            f.write("\n".join(paths) + "\n")
        return registry, paths

    def test_tick_isolates_a_crashing_run_and_reports_it_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry, paths = self._two_project_registry(tmp, ("boom", "fine"))
            served = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                served.append(cwd)
                if "boom" in cwd:
                    raise RuntimeError("model runner fell over")
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "2"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = cli.tick(env, now=now, run=fake_run)

            self.assertEqual(rc, 1)                          # the crash is a failure...
            self.assertEqual(sorted(served), sorted(paths))  # ...but the other run still ran
            self.assertIn("failed (model runner fell over)", out.getvalue())
            self.assertIn("exit 0", out.getvalue())

    def test_tick_records_a_timed_out_run_as_failed_without_sinking_the_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry, paths = self._two_project_registry(tmp, ("slow", "fine"))
            served = []

            def fake_run(cmd, cwd=None, env=None, timeout=None):
                served.append(cwd)
                if "slow" in cwd:
                    raise subprocess.TimeoutExpired(cmd="cadence run triage",
                                                    timeout=timeout or 3600)
                return type("Proc", (), {"returncode": 0})()

            env = {"CADENCE_HOME": "/cadence", "CADENCE_PROJECTS_FILE": registry,
                   "CADENCE_SCHEDULER_MAX_RUNS": "2"}
            now = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = cli.tick(env, now=now, run=fake_run)

            self.assertEqual(rc, 1)
            self.assertEqual(sorted(served), sorted(paths))
            self.assertIn("timed out", out.getvalue())
            # The sibling's outcome line survives the timeout in full.
            self.assertIn(f"{paths[1]}: triage exit 0", out.getvalue())


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
        self.assertIn("active config is", result.stderr)
        self.assertIn("project-local cadence/.env", result.stderr)

    def test_apply_leaves_existing_scheduler_plist_intact_when_render_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            bin_dir = os.path.join(tmp, "bin")
            launch_agents = os.path.join(home, "Library", "LaunchAgents")
            os.makedirs(launch_agents)
            os.makedirs(bin_dir)
            plist = os.path.join(launch_agents, "com.cadence.scheduler.plist")
            with open(plist, "w", encoding="utf-8") as f:
                f.write("original scheduler plist")

            self._write_exe(os.path.join(bin_dir, "python3"), f"""#!/bin/sh
if [ "$2" = "check" ]; then
  exit 0
fi
if [ "$2" = "render-scheduler" ]; then
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
                self.assertEqual(f.read(), "original scheduler plist")

    def _write_exe(self, path, body):
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)


class TestRegister(unittest.TestCase):
    def test_registers_project_dir_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "state", "projects.txt")
            project = os.path.join(tmp, "app")
            os.makedirs(project)
            env = {"CADENCE_PROJECTS_FILE": registry}

            lines = []
            cli.register(env, [project], out=lines.append)
            with open(registry, encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), project)
            self.assertTrue(any("registered:" in x for x in lines))

            lines2 = []
            cli.register(env, [project], out=lines2.append)
            self.assertTrue(any("already registered" in x for x in lines2))
            with open(registry, encoding="utf-8") as f:
                self.assertEqual(f.read().count(project + "\n"), 1)  # not duplicated

    def test_env_path_maps_to_its_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "projects.txt")
            config = os.path.join(tmp, "app", "cadence", ".env")
            os.makedirs(os.path.dirname(config))
            open(config, "w").close()
            env = {"CADENCE_PROJECTS_FILE": registry}

            lines = []
            cli.register(env, [config], out=lines.append)
            # read_projects should see the same project dir the config lives under.
            projects = cli.read_projects(registry)
            self.assertEqual(projects[0]["project"], os.path.join(tmp, "app"))


class TestUpsertEnvVar(unittest.TestCase):
    def test_appends_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("LINEAR_TEAM_ID=abc\n")
            cli.upsert_env_var(path, "CADENCE_SCHEDULED", "1")
            with open(path, encoding="utf-8") as f:
                txt = f.read()
            self.assertIn("LINEAR_TEAM_ID=abc\n", txt)
            self.assertIn("CADENCE_SCHEDULED=1\n", txt)

    def test_replaces_existing_value_and_export_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w", encoding="utf-8") as f:
                f.write("# comment stays\nexport CADENCE_SCHEDULED=0\nOTHER=x\n")
            cli.upsert_env_var(path, "CADENCE_SCHEDULED", "1")
            with open(path, encoding="utf-8") as f:
                txt = f.read()
            self.assertIn("# comment stays\n", txt)
            self.assertIn("OTHER=x\n", txt)
            self.assertIn("CADENCE_SCHEDULED=1\n", txt)
            self.assertNotIn("CADENCE_SCHEDULED=0", txt)

    def test_creates_file_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            cli.upsert_env_var(path, "CADENCE_SCHEDULED", "1")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "CADENCE_SCHEDULED=1\n")


class TestUnregister(unittest.TestCase):
    def test_removes_project_preserving_other_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            keep = os.path.join(tmp, "keep")
            drop = os.path.join(tmp, "drop")
            os.makedirs(keep); os.makedirs(drop)
            reg = os.path.join(tmp, "projects.txt")
            with open(reg, "w", encoding="utf-8") as f:
                f.write(f"# my projects\n{keep}\n{drop}\n")
            lines = []
            self.assertEqual(cli.unregister(env, [drop], out=lines.append), 0)
            self.assertTrue(any("unregistered:" in x for x in lines))
            with open(reg, encoding="utf-8") as f:
                txt = f.read()
            self.assertEqual(txt, f"# my projects\n{keep}\n")

    def test_accepts_env_path_and_matches_dir_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            project = os.path.join(tmp, "app")
            os.makedirs(os.path.join(project, "cadence"))
            reg = os.path.join(tmp, "projects.txt")
            with open(reg, "w", encoding="utf-8") as f:
                f.write(project + "\n")
            config = os.path.join(project, "cadence", ".env")
            self.assertEqual(cli.unregister(env, [config], out=lambda *_: None), 0)
            with open(reg, encoding="utf-8") as f:
                self.assertEqual(f.read(), "")

    def test_idempotent_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            lines = []
            self.assertEqual(
                cli.unregister(env, [os.path.join(tmp, "ghost")], out=lines.append), 0)
            self.assertTrue(any("not registered" in x for x in lines))


class TestOnboard(unittest.TestCase):
    def _project(self, tmp, name="app", config_lines=""):
        project = os.path.join(tmp, name)
        os.makedirs(os.path.join(project, "cadence"))
        config = os.path.join(project, "cadence", ".env")
        with open(config, "w", encoding="utf-8") as f:
            f.write(config_lines)
        return project, config

    def test_requires_a_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            missing = os.path.join(tmp, "bare")
            os.makedirs(missing)
            lines = []
            self.assertEqual(cli.onboard(env, [missing], out=lines.append), 1)
            self.assertTrue(any("no config" in x for x in lines))

    def test_fills_state_dir_schedules_registers_and_pauses(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            project, config = self._project(tmp, config_lines="LINEAR_TEAM_ID=t\n")
            self.assertEqual(cli.onboard(env, [project], out=lambda *_: None), 0)
            values = cli.read_env_file(config)
            state = os.path.join(tmp, "projects", "app")
            self.assertEqual(values.get("CADENCE_STATE_DIR"), state)
            self.assertEqual(values.get("CADENCE_SCHEDULED"), "1")
            self.assertEqual(values.get("LINEAR_TEAM_ID"), "t")  # untouched
            self.assertTrue(os.path.isfile(os.path.join(state, "runs", "PAUSED")))
            projects = [i["project"] for i in cli.read_projects(cli.projects_file(env))]
            self.assertIn(project, projects)

    def test_respects_existing_state_dir_and_rerun_does_not_repause(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            own_state = os.path.join(tmp, "custom-state")
            project, config = self._project(
                tmp, config_lines=f"CADENCE_STATE_DIR={own_state}\n")
            self.assertEqual(cli.onboard(env, [project], out=lambda *_: None), 0)
            self.assertEqual(
                cli.read_env_file(config).get("CADENCE_STATE_DIR"), own_state)
            # a human resumes; re-running onboard must not re-pause
            os.remove(os.path.join(own_state, "runs", "PAUSED"))
            self.assertEqual(cli.onboard(env, [project], out=lambda *_: None), 0)
            self.assertFalse(
                os.path.exists(os.path.join(own_state, "runs", "PAUSED")))

    def test_refuses_to_autofill_a_taken_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            taken = os.path.join(tmp, "projects", "app")
            # an already-registered project (different dir, same basename)
            other, _ = self._project(
                tmp, name="elsewhere", config_lines=f"CADENCE_STATE_DIR={taken}\n")
            cli.register(env, [other], out=lambda *_: None)
            project, config = self._project(tmp, name="app", config_lines="")
            lines = []
            self.assertEqual(cli.onboard(env, [project], out=lines.append), 1)
            self.assertTrue(any("already belongs" in x for x in lines))
            self.assertNotIn("CADENCE_STATE_DIR",
                             cli.read_env_file(config))  # nothing written


class TestOffboard(unittest.TestCase):
    def _onboarded(self, tmp):
        env = {"CADENCE_STATE_DIR": tmp}
        project = os.path.join(tmp, "app")
        os.makedirs(os.path.join(project, "cadence"))
        config = os.path.join(project, "cadence", ".env")
        with open(config, "w", encoding="utf-8") as f:
            f.write("LINEAR_TEAM_ID=t\n")
        cli.onboard(env, [project], out=lambda *_: None)
        state = os.path.join(tmp, "projects", "app")
        return env, project, config, state

    def test_pauses_deschedules_and_unregisters(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            os.remove(os.path.join(state, "runs", "PAUSED"))  # human had resumed
            self.assertEqual(cli.offboard(env, [project], out=lambda *_: None), 0)
            self.assertTrue(os.path.isfile(os.path.join(state, "runs", "PAUSED")))
            values = cli.read_env_file(config)
            self.assertEqual(values.get("CADENCE_SCHEDULED"), "0")
            self.assertEqual(values.get("LINEAR_TEAM_ID"), "t")  # untouched
            self.assertEqual(cli.read_projects(cli.projects_file(env)), [])
            self.assertTrue(os.path.isdir(state))  # nothing deleted

    def test_purge_removes_own_state_dir_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lambda *_: None), 0)
            self.assertFalse(os.path.exists(state))
            self.assertTrue(os.path.exists(config))  # config always survives

    def test_purge_refused_when_state_dir_shared_with_another_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            # a second registered project pointed at the same state dir
            other = os.path.join(tmp, "other")
            os.makedirs(os.path.join(other, "cadence"))
            other_config = os.path.join(other, "cadence", ".env")
            with open(other_config, "w", encoding="utf-8") as f:
                f.write(f"CADENCE_STATE_DIR={state}\n")
            cli.register(env, [other], out=lambda *_: None)
            lines = []
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lines.append), 0)
            self.assertTrue(any("refused purge" in x for x in lines))
            self.assertTrue(os.path.isdir(state))  # shared dir survives

    def test_purge_refused_when_state_dir_contains_another_project_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            broad_state = os.path.join(tmp, "state-root")
            nested_state = os.path.join(broad_state, "other")
            cli.upsert_env_var(config, "CADENCE_STATE_DIR", broad_state)
            os.makedirs(os.path.join(broad_state, "runs"))

            other = os.path.join(tmp, "other")
            os.makedirs(os.path.join(other, "cadence"))
            other_config = os.path.join(other, "cadence", ".env")
            with open(other_config, "w", encoding="utf-8") as f:
                f.write(f"CADENCE_STATE_DIR={nested_state}\n")
            cli.register(env, [other], out=lambda *_: None)

            lines = []
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lines.append), 0)
            self.assertTrue(any("contains state for" in x for x in lines))
            self.assertTrue(os.path.isdir(broad_state))

    def test_purge_refused_when_state_dir_is_inside_another_project_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            broad_state = os.path.join(tmp, "state-root")
            nested_state = os.path.join(broad_state, "app")
            cli.upsert_env_var(config, "CADENCE_STATE_DIR", nested_state)
            os.makedirs(os.path.join(nested_state, "runs"))

            other = os.path.join(tmp, "other")
            os.makedirs(os.path.join(other, "cadence"))
            other_config = os.path.join(other, "cadence", ".env")
            with open(other_config, "w", encoding="utf-8") as f:
                f.write(f"CADENCE_STATE_DIR={broad_state}\n")
            cli.register(env, [other], out=lambda *_: None)

            lines = []
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lines.append), 0)
            self.assertTrue(any("overlaps state for" in x for x in lines))
            self.assertTrue(os.path.isdir(nested_state))

    def test_purge_allows_active_project_state_dir_loaded_in_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            active_env = {**env, "CADENCE_STATE_DIR": state}

            self.assertEqual(
                cli.offboard(active_env, [project, "--purge"], out=lambda *_: None), 0)

            self.assertFalse(os.path.exists(state))

    def test_purge_refused_when_state_dir_is_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            project = os.path.join(tmp, "app")
            os.makedirs(os.path.join(project, "cadence"))
            config = os.path.join(project, "cadence", ".env")
            with open(config, "w", encoding="utf-8") as f:
                f.write(f"CADENCE_STATE_DIR={project}\n")
            cli.register(env, [project], out=lambda *_: None)

            lines = []
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lines.append), 0)
            self.assertTrue(any("contains the project checkout" in x for x in lines))
            self.assertTrue(os.path.isdir(project))

    def test_purge_refused_for_plain_home_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            msg = cli._purge_unsafe(
                os.path.join(os.path.expanduser("~"), "Documents"),
                {"CADENCE_STATE_DIR": tmp})
            self.assertIn("does not look like a Cadence state dir", msg)

    def test_purge_refuses_instead_of_crashing_on_bad_sibling_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, project, config, state = self._onboarded(tmp)
            other = os.path.join(tmp, "other")
            bad_config = os.path.join(other, "cadence", ".env")
            os.makedirs(bad_config)
            cli.register(env, [other], out=lambda *_: None)

            lines = []
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lines.append), 0)
            self.assertTrue(any("cannot inspect" in x for x in lines))
            self.assertTrue(os.path.isdir(state))

    def test_skips_pause_and_purge_without_own_state_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CADENCE_STATE_DIR": tmp}
            project = os.path.join(tmp, "app")
            os.makedirs(os.path.join(project, "cadence"))
            config = os.path.join(project, "cadence", ".env")
            with open(config, "w", encoding="utf-8") as f:
                f.write("CADENCE_SCHEDULED=1\n")  # no CADENCE_STATE_DIR
            cli.register(env, [project], out=lambda *_: None)
            lines = []
            self.assertEqual(
                cli.offboard(env, [project, "--purge"], out=lines.append), 0)
            self.assertTrue(any("own CADENCE_STATE_DIR" in x for x in lines))
            self.assertEqual(cli.read_projects(cli.projects_file(env)), [])
            # the shared default state dir was neither paused nor deleted
            self.assertFalse(os.path.exists(
                os.path.join(tmp, "runs", "PAUSED")))


if __name__ == "__main__":
    unittest.main()
