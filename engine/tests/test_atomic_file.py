import importlib.util
import os
import tempfile
import unittest
from unittest import mock


_spec = importlib.util.spec_from_file_location(
    "atomic_file", os.path.join(os.path.dirname(__file__), "..", "lib", "atomic_file.py"))
atomic_file = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(atomic_file)


class TestAtomicWrite(unittest.TestCase):
    def test_replace_failure_leaves_original_file_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old")

            with mock.patch.object(atomic_file.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    atomic_file.atomic_write(path, "new")

            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old")
            self.assertEqual(os.listdir(tmp), ["state.json"])


if __name__ == "__main__":
    unittest.main()
