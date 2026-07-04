import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "queue"))
import cli  # noqa: E402


def _issue(ident, labels, **extra):
    return {"identifier": ident, "title": f"title {ident}",
            "url": f"https://x/{ident}", "labels": list(labels), **extra}


class TestBucket(unittest.TestCase):
    def test_single_label_goes_to_its_bucket(self):
        b = cli.bucket([_issue("P-1", ["agent:specced"])])
        self.assertEqual([i["identifier"] for i in b["specced"]], ["P-1"])

    def test_most_advanced_lifecycle_label_wins(self):
        # triaged + specced -> specced (the issue's true next gate)
        b = cli.bucket([_issue("P-2", ["agent:triaged", "agent:specced"])])
        self.assertEqual([i["identifier"] for i in b["specced"]], ["P-2"])
        self.assertEqual(b["triaged"], [])

    def test_parked_label_removes_from_play(self):
        # hold beats an actionable label -> parked only
        b = cli.bucket([_issue("P-3", ["agent:hold", "agent:pr-open"])])
        self.assertEqual([i["identifier"] for i in b["hold"]], ["P-3"])
        self.assertEqual(b["pr_open"], [])

    def test_failure_outranks_in_flight(self):
        b = cli.bucket([_issue("P-4", ["agent:claimed", "agent:needs-attention"])])
        self.assertEqual([i["identifier"] for i in b["needs_attention"]], ["P-4"])
        self.assertEqual(b["claimed"], [])

    def test_unrecognised_labels_are_ignored(self):
        b = cli.bucket([_issue("P-5", ["Bug", "frontend"])])
        self.assertTrue(all(v == [] for v in b.values()))


class TestRender(unittest.TestCase):
    def test_empty_board(self):
        out = cli.render(cli.bucket([]), team_name="Demo")
        self.assertIn("Cadence queue · Demo", out)
        self.assertIn("Nothing waiting on you.", out)

    def test_actionable_line_shows_label_count_and_keys(self):
        issues = [_issue("P-1", ["agent:specced"]), _issue("P-2", ["agent:specced"])]
        out = cli.render(cli.bucket(issues))
        self.assertIn("Grant build", out)
        self.assertIn("(agent:specced)", out)
        self.assertIn("  2   P-1, P-2", out)  # count column then keys
        self.assertIn("P-1, P-2", out)
        self.assertIn("YOUR MOVE", out)
        self.assertIn("IN FLIGHT", out)
        self.assertIn("PARKED", out)

    def test_dupe_candidate_gets_star_and_legend(self):
        issues = [_issue("P-9", ["agent:triaged", "agent:dupe-candidate"])]
        out = cli.render(cli.bucket(issues))
        self.assertIn("P-9*", out)
        self.assertIn("duplicate candidate", out)

    def test_parked_shows_counts_only(self):
        issues = [_issue("P-3", ["agent:hold"]), _issue("P-4", ["Stale"])]
        out = cli.render(cli.bucket(issues))
        self.assertIn("on hold 1", out)
        self.assertIn("stale 1", out)
        self.assertNotIn("P-3", out)  # parked issues are counts only, no keys
        self.assertNotIn("P-4", out)

    def test_long_bucket_truncates_keys_by_default(self):
        issues = [_issue("P-%d" % n, ["agent:triaged"]) for n in range(20)]
        out = cli.render(cli.bucket(issues))
        self.assertIn("…+5 more", out)          # 20 issues, cap 15 -> 5 hidden
        self.assertNotIn("P-19", out)            # 16th+ key not shown

    def test_verbose_shows_all_keys_no_truncation(self):
        issues = [_issue("P-%d" % n, ["agent:triaged"]) for n in range(20)]
        out = cli.render(cli.bucket(issues), verbose=True)
        self.assertNotIn("more", out)            # no truncation marker
        self.assertIn("P-19", out)               # every key present

    def test_verbose_expands_titles_and_urls(self):
        issues = [_issue("P-7", ["agent:pr-open"], priority=2, cycle=5)]
        out = cli.render(cli.bucket(issues), verbose=True)
        self.assertIn("title P-7", out)
        self.assertIn("https://x/P-7", out)
        self.assertIn("P2", out)
        self.assertIn("cycle 5", out)


class TestConflicts(unittest.TestCase):
    def test_two_position_labels_are_flagged(self):
        # build crashed mid-swap: specced not cleared when pr-open was added
        conflicts = cli.conflicts([_issue("P-2", ["agent:specced", "agent:pr-open"])])
        self.assertEqual(conflicts, [("P-2", ["agent:specced", "agent:pr-open"])])

    def test_sticky_triaged_is_not_a_conflict(self):
        # agent:triaged is cleared only by a human, so it coexists with a position
        # label by design and must never be flagged (docs/LABELS.md).
        self.assertEqual(cli.conflicts([_issue("P-9", ["agent:triaged", "agent:specced"])]), [])

    def test_exception_flag_with_position_is_not_a_conflict(self):
        # a failed build keeps its position label + adds agent:needs-attention
        self.assertEqual(
            cli.conflicts([_issue("P-8", ["agent:triaged", "agent:specced", "agent:needs-attention"])]), [])

    def test_single_label_is_not_flagged(self):
        self.assertEqual(cli.conflicts([_issue("P-1", ["agent:specced"])]), [])

    def test_render_shows_conflict_warning_line(self):
        issues = [_issue("P-2", ["agent:specced", "agent:pr-open"])]
        out = cli.render(cli.bucket(issues), conflict_list=cli.conflicts(issues))
        self.assertIn("⚠ inconsistent labels: P-2 (agent:specced + agent:pr-open)", out)


class TestFailureClustering(unittest.TestCase):
    def test_classify_matches_known_signatures(self):
        self.assertEqual(cli.classify_failure(
            "cadence worktree add sr3-7 develop: could not find bare repo")[0], "Worktree setup")
        self.assertEqual(cli.classify_failure(
            "cannot verify criteria_present; no doc-get verb")[0], "Spec-doc verification")
        self.assertEqual(cli.classify_failure(
            "composer lint failed on pre-existing issues in unrelated files")[0],
            "Gate on pre-existing debt")
        self.assertEqual(cli.classify_failure("branch has an empty diff")[0], "Empty diff")
        self.assertEqual(cli.classify_failure("work is already present on develop")[0],
                         "Work already on base")

    def test_unknown_reason_is_other(self):
        self.assertEqual(cli.classify_failure("something weird happened")[0], "Other")

    def test_cluster_groups_shared_cause_largest_first(self):
        items = [
            ("A", "worktree add failed: bare repo missing"),
            ("B", "worktree add failed: bare repo missing"),
            ("C", "empty diff, nothing to ship"),
        ]
        clusters = cli.cluster_failures(items)
        self.assertEqual(clusters[0]["label"], "Worktree setup")
        self.assertEqual(clusters[0]["ids"], ["A", "B"])
        self.assertEqual(clusters[1]["label"], "Empty diff")

    def test_render_shows_cluster_count_hint_and_ids(self):
        out = cli.render_failures(cli.cluster_failures(
            [("SR3-7", "could not find bare repo"), ("SR3-8", "could not find bare repo")]), team_name="Demo")
        self.assertIn("Run failures · Demo", out)
        self.assertIn("Worktree setup", out)
        self.assertIn("SR3-7, SR3-8", out)
        self.assertIn("↳", out)

    def test_render_empty_is_calm(self):
        self.assertIn("nothing is in agent:needs-attention", cli.render_failures([]))

    def test_salient_line_picks_the_failure_paragraph(self):
        body = "## Problem\nSomething.\n\nBuild note: gate failed on pre-existing lint.\n\nOther text."
        self.assertIn("gate failed", cli._salient_line(body))


class TestFetchIssues(unittest.TestCase):
    def test_file_backend_reads_tasks_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tasks.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("""# Cadence Tasks

## TASK-1: Local work
status: open
labels: agent:specced

## Acceptance criteria
- works
""")
            old = os.environ.copy()
            try:
                os.environ.clear()
                os.environ.update({"TASK_BACKEND": "file", "TASK_FILE": path})
                issues = cli.fetch_issues()
            finally:
                os.environ.clear()
                os.environ.update(old)

        self.assertEqual([i["identifier"] for i in issues], ["TASK-1"])


if __name__ == "__main__":
    unittest.main()
