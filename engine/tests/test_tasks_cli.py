import os
import subprocess
import sys
import tempfile
import unittest
import json


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TASKS_CLI = os.path.join(ROOT, "engine", "tasks", "cli.py")


TASKS_MD = """# Cadence Tasks

## TASK-1: First task
status: open
labels: agent:triaged, Bug

Acceptance criteria here.

## TASK-2: Second task
status: blocked
labels: agent:hold

Needs a human.
"""


class TestTasksCli(unittest.TestCase):
    def _run(self, args, tasks_text=TASKS_MD):
        with tempfile.TemporaryDirectory() as tmp:
            task_file = os.path.join(tmp, "cadence", "tasks.md")
            os.makedirs(os.path.dirname(task_file))
            with open(task_file, "w", encoding="utf-8") as f:
                f.write(tasks_text)
            env = os.environ.copy()
            env["TASK_FILE"] = task_file
            result = subprocess.run(
                [sys.executable, TASKS_CLI, *args],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
            with open(task_file, encoding="utf-8") as f:
                updated = f.read()
        return result, updated

    def test_list_reads_markdown_tasks_and_filters_by_label(self):
        result, _updated = self._run(["list", "--label", "agent:triaged"])

        self.assertEqual(result.returncode, 0, result.stderr)
        tasks = json.loads(result.stdout)
        self.assertEqual([task["identifier"] for task in tasks], ["TASK-1"])
        self.assertEqual(tasks[0]["title"], "First task")
        self.assertEqual(tasks[0]["status"], "open")
        self.assertEqual(tasks[0]["labels"], ["agent:triaged", "Bug"])
        self.assertIn("Acceptance criteria here.", tasks[0]["description"])

    def test_update_adds_and_removes_labels_without_losing_body(self):
        result, updated = self._run([
            "update", "TASK-1",
            "--add-label", "agent:spec",
            "--remove-label", "agent:triaged",
            "--status", "ready",
        ])

        self.assertEqual(result.returncode, 0, result.stderr)
        task = json.loads(result.stdout)
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["labels"], ["Bug", "agent:spec"])
        self.assertIn("Acceptance criteria here.", updated)
        self.assertIn("labels: Bug, agent:spec", updated)

    def test_update_can_replace_body_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_file = os.path.join(tmp, "cadence", "tasks.md")
            body_file = os.path.join(tmp, "body.md")
            os.makedirs(os.path.dirname(task_file))
            with open(task_file, "w", encoding="utf-8") as f:
                f.write(TASKS_MD)
            with open(body_file, "w", encoding="utf-8") as f:
                f.write("New spec body.\n")
            env = os.environ.copy()
            env["TASK_FILE"] = task_file

            result = subprocess.run(
                [sys.executable, TASKS_CLI, "update", "TASK-1", "--body-file", body_file],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=10,
            )
            with open(task_file, encoding="utf-8") as f:
                updated = f.read()

        self.assertEqual(result.returncode, 0, result.stderr)
        task = json.loads(result.stdout)
        self.assertEqual(task["description"], "New spec body.")
        self.assertIn("New spec body.", updated)
        self.assertNotIn("Acceptance criteria here.", updated)

    def test_body_lines_starting_with_status_or_labels_survive_round_trip(self):
        # A spec body can legitimately contain lines like "status: 200"; these
        # must stay in the body, not be swallowed into the task's metadata.
        with tempfile.TemporaryDirectory() as tmp:
            task_file = os.path.join(tmp, "cadence", "tasks.md")
            body_file = os.path.join(tmp, "body.md")
            os.makedirs(os.path.dirname(task_file))
            with open(task_file, "w", encoding="utf-8") as f:
                f.write(TASKS_MD)
            with open(body_file, "w", encoding="utf-8") as f:
                f.write("The endpoint returns:\nstatus: 200 for success\n"
                        "status: 404 when missing\n\nlabels: none required\n")
            env = os.environ.copy()
            env["TASK_FILE"] = task_file

            up = subprocess.run(
                [sys.executable, TASKS_CLI, "update", "TASK-1", "--body-file", body_file],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(up.returncode, 0, up.stderr)
            # Re-read from disk to force a fresh parse of what save() rendered.
            got = subprocess.run(
                [sys.executable, TASKS_CLI, "get", "TASK-1"],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(got.returncode, 0, got.stderr)
            task = json.loads(got.stdout)

        # Metadata untouched; every body line preserved.
        self.assertEqual(task["status"], "open")
        self.assertEqual(task["labels"], ["agent:triaged", "Bug"])
        self.assertIn("status: 200 for success", task["description"])
        self.assertIn("status: 404 when missing", task["description"])
        self.assertIn("labels: none required", task["description"])
    def test_validate_passes_a_well_formed_file(self):
        result, _updated = self._run(["validate"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_validate_flags_a_malformed_header(self):
        text = "# Cadence Tasks\n\n## TASK-1 no colon\nstatus: open\nlabels: Bug\n\nBody.\n"
        result, _updated = self._run(["validate"], tasks_text=text)
        self.assertEqual(result.returncode, 1)
        self.assertIn("malformed task header", result.stderr)

    def test_validate_flags_metadata_stranded_in_the_body(self):
        # A blank line before `status:` pushes it into the body, where the parser
        # ignores it — the task silently loses its status.
        text = "# Cadence Tasks\n\n## TASK-1: Title\n\nstatus: open\nlabels: Bug\n"
        result, _updated = self._run(["validate"], tasks_text=text)
        self.assertEqual(result.returncode, 1)
        self.assertIn("body of task 'TASK-1'", result.stderr)

    def test_validate_flags_duplicate_ids(self):
        text = ("# Cadence Tasks\n\n## TASK-1: One\nstatus: open\nlabels:\n\nA.\n\n"
                "## TASK-1: Two\nstatus: open\nlabels:\n\nB.\n")
        result, _updated = self._run(["validate"], tasks_text=text)
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate task id 'TASK-1'", result.stderr)

    def test_validate_allows_status_lines_deeper_in_the_body(self):
        # `status: 200` as ordinary spec prose (not the first body line) is fine.
        text = ("# Cadence Tasks\n\n## TASK-1: Title\nstatus: open\nlabels: Bug\n\n"
                "The endpoint returns:\nstatus: 200 for success\n")
        result, _updated = self._run(["validate"], tasks_text=text)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
