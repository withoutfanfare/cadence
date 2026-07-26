import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "brief_cli", os.path.join(os.path.dirname(__file__), "..", "brief", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def payload(**kw):
    base = {
        "loop": "spec",
        "issue": "MPW-123",
        "did": "Wrote the spec: three acceptance criteria covering the VAT split.",
        "unsure": "Whether the discount applies before or after VAT.",
        "check_first": "docs/pricing.md — confirm the VAT rule.",
        "risk": "low",
        "risk_reasons": ["no sensitive paths", "3 files"],
        "next_gate": "agent:build",
    }
    base.update(kw)
    return base


class TestValidate(unittest.TestCase):
    def test_clean_payload_has_no_problems(self):
        self.assertEqual(cli.validate(payload()), [])

    def test_missing_field_is_reported(self):
        problems = cli.validate(payload(unsure=""))
        self.assertEqual(len(problems), 1)
        self.assertIn("unsure", problems[0])

    def test_unknown_risk_is_reported(self):
        problems = cli.validate(payload(risk="catastrophic"))
        self.assertTrue(any("risk must be one of" in p for p in problems))


class TestRender(unittest.TestCase):
    def test_includes_every_section(self):
        out = cli.render(payload())
        self.assertIn("**Spec ready — your move**", out)
        self.assertIn("**What I did.** Wrote the spec", out)
        self.assertIn("**Least sure about.** Whether the discount", out)
        self.assertIn("**Check first.** docs/pricing.md", out)
        self.assertIn("**Risk: low** — no sensitive paths; 3 files", out)
        self.assertIn("add `agent:build`", out)

    def test_rejects_incomplete_payload(self):
        with self.assertRaises(ValueError):
            cli.render(payload(did=""))

    def test_collapses_newlines_to_one_line_per_field(self):
        out = cli.render(payload(unsure="line one\nline two"))
        self.assertIn("**Least sure about.** line one line two", out)

    def test_truncates_over_long_field_and_records_it(self):
        out = cli.render(payload(unsure="x" * 500))
        self.assertIn("…", out)
        self.assertEqual(cli.parse(out)["truncated"], ["unsure"])

    def test_omits_move_line_for_unknown_gate(self):
        out = cli.render(payload(next_gate=""))
        self.assertNotIn("**Your move:**", out)


class TestParse(unittest.TestCase):
    def test_round_trips(self):
        recovered = cli.parse(cli.render(payload()))
        self.assertEqual(recovered["issue"], "MPW-123")
        self.assertEqual(recovered["risk"], "low")

    def test_survives_surrounding_comment_text(self):
        body = "Some human reply above\n\n" + cli.render(payload()) + "\n\nand below"
        self.assertEqual(cli.parse(body)["loop"], "spec")

    def test_returns_none_without_a_marker(self):
        self.assertIsNone(cli.parse("just an ordinary comment"))

    def test_returns_none_on_broken_marker_json(self):
        self.assertIsNone(cli.parse(cli.MARKER + "{not json" + " -->"))


def facts(**kw):
    base = {"files": ["app/Models/Widget.php"], "insertions": 20, "deletions": 4,
            "tests_changed": True, "gates_passed": True}
    base.update(kw)
    return base


class TestRisk(unittest.TestCase):
    def test_small_tested_change_is_low(self):
        self.assertEqual(cli.score(facts())["risk"], "low")

    def test_sensitive_path_is_high(self):
        out = cli.score(facts(files=["app/Http/Middleware/Authenticate.php"]))
        self.assertEqual(out["risk"], "high")
        self.assertTrue(any("sensitive" in r for r in out["reasons"]))

    def test_migration_is_high(self):
        self.assertEqual(cli.score(facts(files=["database/migrations/2026_x.php"]))["risk"], "high")

    def test_failed_gates_are_high(self):
        out = cli.score(facts(gates_passed=False))
        self.assertEqual(out["risk"], "high")
        self.assertTrue(any("gates" in r for r in out["reasons"]))

    def test_very_large_diff_is_high(self):
        self.assertEqual(cli.score(facts(insertions=700, deletions=50))["risk"], "high")

    def test_untested_source_change_is_medium(self):
        out = cli.score(facts(tests_changed=False))
        self.assertEqual(out["risk"], "medium")
        self.assertTrue(any("no test" in r for r in out["reasons"]))

    def test_many_files_is_medium(self):
        out = cli.score(facts(files=[f"app/A{n}.php" for n in range(15)]))
        self.assertEqual(out["risk"], "medium")

    def test_moderate_diff_is_medium(self):
        self.assertEqual(cli.score(facts(insertions=250, deletions=10))["risk"], "medium")

    def test_test_only_change_is_low_without_tests_changed_flag(self):
        out = cli.score(facts(files=["tests/Feature/WidgetTest.php"], tests_changed=False))
        self.assertEqual(out["risk"], "low")

    def test_blocking_review_finding_forces_high(self):
        # A tiny, tested, non-sensitive change that a reviewer says blocks must
        # not be banded `low` — `low` is the band a reader skims past.
        out = cli.score(facts(blocking_review=True))
        self.assertEqual(out["risk"], "high")
        self.assertTrue(any("blocking finding" in r for r in out["reasons"]))

    def test_absent_blocking_review_does_not_raise_the_band(self):
        self.assertEqual(cli.score(facts())["risk"], "low")

    def test_blocking_review_false_is_treated_as_clean(self):
        self.assertEqual(cli.score(facts(blocking_review=False))["risk"], "low")

    def test_derives_tests_changed_from_files_when_not_stated(self):
        # A spec naming a service and its test must not score medium for
        # "no test changed" — that would escalate almost everything.
        out = cli.score({"files": ["app/Models/Widget.php", "tests/WidgetTest.php"]})
        self.assertEqual(out["risk"], "low")

    def test_derived_flag_is_false_when_no_test_file_is_named(self):
        out = cli.score({"files": ["app/Models/Widget.php"]})
        self.assertEqual(out["risk"], "medium")
        self.assertTrue(any("no test" in r for r in out["reasons"]))

    def test_explicit_false_still_wins_over_derivation(self):
        out = cli.score(facts(files=["app/Models/Widget.php", "tests/WidgetTest.php"],
                              tests_changed=False))
        self.assertEqual(out["risk"], "medium")

    def test_source_name_containing_test_is_not_a_test_file(self):
        # `Latest` and `Contest` contain the letters "test" but are ordinary
        # source names. Treating either as a test would under-report risk.
        for path in ("app/LatestWidget.php", "app/ContestEntry.php"):
            with self.subTest(path=path):
                out = cli.score({"files": [path]})
                self.assertEqual(out["risk"], "medium")
                self.assertTrue(any("no test" in r for r in out["reasons"]))

    def test_common_test_file_names_are_recognised(self):
        for path in ("tests/Widget.php", "test_widget.py", "TestWidget.php",
                     "WidgetTest.php",
                     "widget.test.ts", "widget.spec.ts", "__tests__/widget.ts"):
            with self.subTest(path=path):
                out = cli.score({"files": ["app/Widget.php", path]})
                self.assertEqual(out["risk"], "low")

    def test_empty_facts_are_low_with_a_reason(self):
        out = cli.score({})
        self.assertEqual(out["risk"], "low")
        self.assertTrue(out["reasons"])


if __name__ == "__main__":
    unittest.main()
