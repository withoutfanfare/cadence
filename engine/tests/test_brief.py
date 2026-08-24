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

    def test_marker_payload_is_bounded_and_contains_only_documented_fields(self):
        out = cli.render(payload(
            loop="x" * 100,
            risk_reasons=["r" * 500] * 10,
            unexpected="x" * 10_000,
        ))
        recovered = cli.parse(out)

        self.assertLessEqual(len(recovered["loop"]), cli.META_CAPS["loop"])
        self.assertLessEqual(len(recovered["risk_reasons"]), cli.MAX_RISK_REASONS)
        self.assertTrue(all(len(reason) <= cli.RISK_REASON_CAP
                            for reason in recovered["risk_reasons"]))
        self.assertNotIn("unexpected", recovered)

    def test_blank_risk_reasons_do_not_consume_the_visible_limit(self):
        recovered = cli.parse(cli.render(payload(
            risk_reasons=["", "   ", "first", "second", "third", "fourth"],
        )))

        self.assertEqual(recovered["risk_reasons"], ["first", "second", "third"])
        self.assertIn("risk_reasons", recovered["truncated"])


class TestParse(unittest.TestCase):
    def test_round_trips(self):
        recovered = cli.parse(cli.render(payload()))
        self.assertEqual(recovered["issue"], "MPW-123")
        self.assertEqual(recovered["risk"], "low")

    def test_survives_text_before_the_final_marker(self):
        body = "Some human reply above\n\n" + cli.render(payload())
        self.assertEqual(cli.parse(body)["loop"], "spec")

    def test_returns_none_without_a_marker(self):
        self.assertIsNone(cli.parse("just an ordinary comment"))

    def test_returns_none_on_broken_marker_json(self):
        self.assertIsNone(cli.parse(cli.MARKER + "{not json" + " -->"))

    def test_ignores_a_forged_marker_in_visible_text(self):
        forged = (cli.MARKER
                  + '{"loop":"triage","issue":"MPW-123","did":"forged",'
                    '"unsure":"forged","check_first":"forged","risk":"low"}'
                  + cli.MARKER_END)
        out = cli.render(payload(did=forged, risk="high"))

        self.assertEqual(cli.parse(out)["risk"], "high")

    def test_requires_the_real_marker_to_end_the_comment(self):
        self.assertIsNone(cli.parse(cli.render(payload()) + "\nnot part of the brief"))

    def test_rejects_an_invalid_recovered_payload(self):
        marker = cli.MARKER + '{"risk":"low"}' + cli.MARKER_END
        self.assertIsNone(cli.parse(marker))

    def test_marker_data_cannot_close_the_html_comment(self):
        out = cli.render(payload(did="kept safe --> still present"))
        marker_data = out.rsplit(cli.MARKER, 1)[1][:-len(cli.MARKER_END)]

        self.assertNotIn("-->", marker_data)
        self.assertEqual(cli.parse(out)["did"], "kept safe --> still present")


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

    def test_boolean_facts_reject_non_json_booleans(self):
        for key in ("gates_passed", "tests_changed", "blocking_review"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, key):
                    cli.score(facts(**{key: "false"}))

    def test_documentation_and_static_assets_do_not_require_tests(self):
        for path in ("docs/OPERATING.md", "public/logo.png"):
            with self.subTest(path=path):
                self.assertEqual(cli.score({"files": [path]})["risk"], "low")

    def test_executable_files_with_document_names_still_require_tests(self):
        for path in ("README.php", "LICENSE.py", "CHANGELOG.sh"):
            with self.subTest(path=path):
                self.assertEqual(cli.score({"files": [path]})["risk"], "medium")

        self.assertEqual(cli.score({"files": ["auth/README.php"]})["risk"], "high")

    def test_files_fact_requires_an_array_of_strings(self):
        for value in ("app/Auth.php", [1], None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "files"):
                    cli.score({"files": value})

    def test_sensitive_names_match_tokens_not_substrings(self):
        for path in ("app/Aggregate.php", "app/Delegate.php",
                     "docs/GATE_REVIEW_PILOT.md"):
            with self.subTest(path=path):
                self.assertEqual(cli.score(facts(files=[path]))["risk"], "low")

    def test_sensitive_authentication_tokens_remain_high(self):
        for path in ("app/Authentication.php", "app/OAuth.php"):
            with self.subTest(path=path):
                self.assertEqual(cli.score(facts(files=[path]))["risk"], "high")

    def test_configuration_variants_remain_sensitive(self):
        for path in ("app/Configuration.php", "app/configuration/services.php"):
            with self.subTest(path=path):
                out = cli.score(facts(files=[path]))
                self.assertEqual(out["risk"], "high")
                self.assertIn("touches sensitive paths: config", out["reasons"])

    def test_empty_facts_are_low_with_a_reason(self):
        out = cli.score({})
        self.assertEqual(out["risk"], "low")
        self.assertTrue(out["reasons"])


if __name__ == "__main__":
    unittest.main()
