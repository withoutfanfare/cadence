import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "advance_cli", os.path.join(os.path.dirname(__file__), "..", "advance", "cli.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def st(**kw):
    base = {"auto": True, "hold": False, "resting": "triaged", "bar": {},
            "repairs": 0, "issues_done": 0, "max_issues": 1, "max_repairs": 3}
    base.update(kw)
    return base


class TestConfig(unittest.TestCase):
    def test_defaults_when_absent(self):
        c = cli.config({})
        self.assertFalse(c["autonomous"])
        self.assertEqual(c["max_issues"], 1)
        self.assertEqual(c["max_repairs"], 3)
        self.assertEqual(c["cost_ceiling"], 0)

    def test_reads_and_coerces(self):
        c = cli.config({"AUTONOMOUS": "on", "AUTO_MAX_ISSUES_PER_RUN": "2",
                        "AUTO_MAX_REPAIRS": "5", "AUTO_COST_CEILING": "100000"})
        self.assertTrue(c["autonomous"])
        self.assertEqual(c["max_issues"], 2)
        self.assertEqual(c["max_repairs"], 5)
        self.assertEqual(c["cost_ceiling"], 100000)

    def test_bad_int_falls_back(self):
        self.assertEqual(cli.config({"AUTO_MAX_REPAIRS": "abc"})["max_repairs"], 3)


class TestDecide(unittest.TestCase):
    def test_skip_when_not_auto(self):
        self.assertEqual(cli.decide(st(auto=False))["action"], "skip")

    def test_skip_when_on_hold(self):
        self.assertEqual(cli.decide(st(hold=True))["action"], "skip")

    def test_cap_stop_when_issue_cap_reached(self):
        self.assertEqual(cli.decide(st(issues_done=1, max_issues=1))["action"], "cap-stop")

    def test_grant_spec_when_triaged_clean_with_criteria(self):
        out = cli.decide(st(resting="triaged", bar={"triage_clean": True, "criteria_present": True}))
        self.assertEqual(out["action"], "grant-spec")

    def test_escalate_when_triaged_without_criteria(self):
        out = cli.decide(st(resting="triaged", bar={"triage_clean": True, "criteria_present": False}))
        self.assertEqual(out["action"], "escalate")

    def test_escalate_when_triaged_not_clean(self):
        out = cli.decide(st(resting="triaged", bar={"triage_clean": False, "criteria_present": True}))
        self.assertEqual(out["action"], "escalate")

    def test_grant_build_when_specced_with_criteria(self):
        out = cli.decide(st(resting="specced", bar={"criteria_present": True}))
        self.assertEqual(out["action"], "grant-build")

    def test_escalate_when_specced_without_criteria(self):
        out = cli.decide(st(resting="specced", bar={"criteria_present": False}))
        self.assertEqual(out["action"], "escalate")

    def test_accept_when_pr_open_full_bar(self):
        out = cli.decide(st(resting="pr-open",
                            bar={"gates": True, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "accept")
        self.assertTrue(out["reset_repairs"])
        self.assertFalse(out["bump_repairs"])  # accept and repair flags are exclusive

    def test_repair_when_pr_open_bar_fails_under_limit(self):
        out = cli.decide(st(resting="pr-open", repairs=1, max_repairs=3,
                            bar={"gates": False, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "repair")
        self.assertTrue(out["bump_repairs"])
        self.assertFalse(out["reset_repairs"])

    def test_escalate_when_pr_open_bar_fails_at_limit(self):
        out = cli.decide(st(resting="pr-open", repairs=3, max_repairs=3,
                            bar={"gates": False, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "escalate")

    def test_accept_when_revised_full_bar(self):
        out = cli.decide(st(resting="revised",
                            bar={"gates": True, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "accept")
        self.assertTrue(out["reset_repairs"])

    def test_skip_when_resting_unknown(self):
        self.assertEqual(cli.decide(st(resting="needs-human"))["action"], "skip")

    def test_missing_repairs_key_treated_as_zero_and_still_repairs(self):
        s = st(resting="pr-open", max_repairs=3,
               bar={"gates": False, "criteria_met": True, "review_clean": True})
        del s["repairs"]  # skill omitted the count — must not disable the cap
        out = cli.decide(s)
        self.assertEqual(out["action"], "repair")
        self.assertIn("0/3", out["reason"])

    def test_max_repairs_zero_escalates_immediately(self):
        out = cli.decide(st(resting="pr-open", repairs=0, max_repairs=0,
                            bar={"gates": False, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "escalate")

    def test_string_counts_are_coerced(self):
        out = cli.decide(st(resting="pr-open", repairs="1", max_repairs="3",
                            bar={"gates": False, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "repair")
        self.assertIn("1/3", out["reason"])

    def test_string_counts_at_limit_escalate(self):
        out = cli.decide(st(resting="pr-open", repairs="3", max_repairs="3",
                            bar={"gates": False, "criteria_met": True, "review_clean": True}))
        self.assertEqual(out["action"], "escalate")
        self.assertIn("3/3", out["reason"])


if __name__ == "__main__":
    unittest.main()
