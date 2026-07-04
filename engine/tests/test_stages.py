import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from stages import resolve_labels, stage_of  # noqa: E402


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


class TestResolveLabels(unittest.TestCase):
    def test_adding_position_label_drops_the_others(self):
        # the leak that stranded clio/clipboard: build adds pr-open, specced stays
        out = resolve_labels(["agent:triaged", "agent:specced"], add=["agent:pr-open"])
        self.assertEqual(out, ["agent:triaged", "agent:pr-open"])

    def test_revise_drops_pr_open(self):
        out = resolve_labels(["agent:triaged", "agent:pr-open"], add=["agent:revised"])
        self.assertEqual(out, ["agent:triaged", "agent:revised"])

    def test_accept_moves_revised_back_to_pr_open(self):
        # explicit backwards move: added pr-open wins even though revised ranks higher
        out = resolve_labels(["agent:triaged", "agent:revised"],
                             add=["agent:pr-open"], remove=["agent:revised"])
        self.assertEqual(out, ["agent:triaged", "agent:pr-open"])

    def test_self_heals_residue_on_unrelated_write(self):
        # two position labels already present; a write that touches neither still
        # normalises to the furthest (pr-open), healing the corruption
        out = resolve_labels(["agent:triaged", "agent:specced", "agent:pr-open"],
                             add=["Bug"])
        self.assertEqual(out, ["agent:triaged", "agent:pr-open", "Bug"])

    def test_triaged_is_sticky_and_coexists(self):
        out = resolve_labels(["agent:triaged"], add=["agent:specced"])
        self.assertEqual(out, ["agent:triaged", "agent:specced"])

    def test_single_position_untouched(self):
        out = resolve_labels(["agent:triaged", "agent:specced"], add=["agent:build"])
        self.assertEqual(out, ["agent:triaged", "agent:specced", "agent:build"])

    def test_remove_still_applies_and_no_duplicates(self):
        out = resolve_labels(["agent:triaged", "agent:pr-open", "agent:hold"],
                             add=["agent:pr-open"], remove=["agent:hold"])
        self.assertEqual(out, ["agent:triaged", "agent:pr-open"])


if __name__ == "__main__":
    unittest.main()
