import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "advance_cli", os.path.join(os.path.dirname(__file__), "..", "advance", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

DOC = """# Spec — STU-1: thing

## Problem
It is broken.

## Acceptance criteria
- [ ] The list endpoint returns 200
- [ ] A test guards the fix (fails before it)
- Pagination is preserved

## Risks
None.
"""


class TestParseCriteria(unittest.TestCase):
    def test_extracts_items_until_next_heading(self):
        items = cli.parse_criteria(DOC)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0], "The list endpoint returns 200")
        self.assertIn("Pagination is preserved", items)
        self.assertNotIn("None.", items)  # stopped at ## Risks

    def test_case_insensitive_heading(self):
        self.assertEqual(
            cli.parse_criteria("**Acceptance Criteria**\n- one\n"), ["one"])

    def test_numbered_items(self):
        self.assertEqual(
            cli.parse_criteria("## Acceptance criteria\n1. first\n2. second\n"),
            ["first", "second"])

    def test_no_section_returns_empty(self):
        self.assertEqual(cli.parse_criteria("## Problem\n- not criteria\n"), [])

    def test_empty_section_returns_empty(self):
        self.assertEqual(cli.parse_criteria("## Acceptance criteria\n\n## Risks\n"), [])

    def test_bold_next_heading_ends_section(self):
        items = cli.parse_criteria("**Acceptance Criteria**\n- one\n**Risks**\n- two\n")
        self.assertEqual(items, ["one"])  # stopped at the bold Risks heading


if __name__ == "__main__":
    unittest.main()
