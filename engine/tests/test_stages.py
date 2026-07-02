import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from stages import stage_of  # noqa: E402


class TestStageOf(unittest.TestCase):
    def test_no_labels_is_backlog_and_advances_to_spec(self):
        s = stage_of([])
        self.assertEqual(s["name"], "backlog")
        self.assertIsNone(s["gate"])
        self.assertFalse(s["hold"])
        self.assertIsNone(s["exception"])
        self.assertEqual(s["advance"], "agent:spec")

    def test_triaged_advances_to_spec(self):
        s = stage_of(["agent:triaged", "Bug"])
        self.assertEqual(s["name"], "triaged")
        self.assertEqual(s["advance"], "agent:spec")

    def test_furthest_breadcrumb_wins(self):
        s = stage_of(["agent:triaged", "agent:specced", "agent:pr-open"])
        self.assertEqual(s["name"], "pr-open")
        self.assertEqual(s["advance"], "agent:revise")

    def test_pending_gate_blocks_advance(self):
        s = stage_of(["agent:specced", "agent:build"])
        self.assertEqual(s["name"], "specced")
        self.assertEqual(s["gate"], "build")
        self.assertIsNone(s["advance"])

    def test_hold_is_orthogonal(self):
        s = stage_of(["agent:pr-open", "agent:hold"])
        self.assertTrue(s["hold"])
        self.assertEqual(s["name"], "pr-open")
        self.assertEqual(s["advance"], "agent:revise")

    def test_exception_blocks_advance(self):
        s = stage_of(["agent:triaged", "agent:needs-attention"])
        self.assertEqual(s["exception"], "needs-attention")
        self.assertIsNone(s["advance"])

    def test_revised_re_reviews_via_revise(self):
        self.assertEqual(stage_of(["agent:revised"])["advance"], "agent:revise")


if __name__ == "__main__":
    unittest.main()
