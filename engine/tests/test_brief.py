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


if __name__ == "__main__":
    unittest.main()
