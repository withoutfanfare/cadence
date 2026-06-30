import importlib.util
import os
import shutil
import tempfile
import unittest

_spec = importlib.util.spec_from_file_location(
    "advance_cli", os.path.join(os.path.dirname(__file__), "..", "advance", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class TestRepairs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "runs"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_unknown_is_zero(self):
        self.assertEqual(cli.get_repairs(self.dir, "STU-1"), 0)

    def test_bump_increments_and_persists(self):
        self.assertEqual(cli.bump_repairs(self.dir, "STU-1"), 1)
        self.assertEqual(cli.bump_repairs(self.dir, "STU-1"), 2)
        self.assertEqual(cli.get_repairs(self.dir, "STU-1"), 2)

    def test_reset_clears_only_that_issue(self):
        cli.bump_repairs(self.dir, "STU-1")
        cli.bump_repairs(self.dir, "STU-2")
        cli.reset_repairs(self.dir, "STU-1")
        self.assertEqual(cli.get_repairs(self.dir, "STU-1"), 0)
        self.assertEqual(cli.get_repairs(self.dir, "STU-2"), 1)

    def test_corrupt_file_reads_as_zero(self):
        with open(cli.repairs_path(self.dir), "w", encoding="utf-8") as f:
            f.write("not json")
        self.assertEqual(cli.get_repairs(self.dir, "STU-1"), 0)


if __name__ == "__main__":
    unittest.main()
