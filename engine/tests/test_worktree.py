import os, shutil, subprocess, tempfile, unittest

# Hermetic test for engine/scripts/worktree.sh (git backend). Builds a throwaway
# CADENCE_HOME (copied lib-env.sh + worktree.sh + a temp .env) so it never reads the
# developer's real .env. The grove backend needs the grove command and is not covered.

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class TestWorktreeGit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Throwaway CADENCE_HOME with just the pieces worktree.sh needs.
        os.makedirs(os.path.join(self.tmp, "engine", "lib"))
        os.makedirs(os.path.join(self.tmp, "engine", "scripts"))
        shutil.copy(os.path.join(REPO, "engine", "lib", "lib-env.sh"),
                    os.path.join(self.tmp, "engine", "lib", "lib-env.sh"))
        self.script = os.path.join(self.tmp, "engine", "scripts", "worktree.sh")
        shutil.copy(os.path.join(REPO, "engine", "scripts", "worktree.sh"), self.script)

        # A real git repo to act as PROJECT_DIR, with a `develop` branch + one commit.
        self.proj = os.path.join(self.tmp, "proj")
        self._git("init", "-q", "-b", "develop", self.proj, cwd=self.tmp)
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "-C", self.proj, "commit", "--allow-empty", "-qm", "init")

        self.wtbase = os.path.join(self.tmp, "wts")
        with open(os.path.join(self.tmp, ".env"), "w", encoding="utf-8") as f:
            f.write(f"PROJECT_DIR={self.proj}\n"
                    f"WORKTREE_BASE={self.wtbase}\n"
                    f"BASE_BRANCH=develop\n"
                    f"WORKTREE_TOOL=git\n"
                    f"CADENCE_STATE_DIR={os.path.join(self.tmp, 'state')}\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _wt(self, *args):
        r = subprocess.run(["bash", self.script, *args],
                           capture_output=True, text=True)
        return r.returncode, r.stdout.strip(), r.stderr

    def _branch_exists(self, name):
        return subprocess.run(
            ["git", "-C", self.proj, "show-ref", "--verify", "--quiet",
             f"refs/heads/{name}"]).returncode == 0

    def _set_worktree_tool(self, tool):
        with open(os.path.join(self.tmp, ".env"), "a", encoding="utf-8") as f:
            f.write(f"WORKTREE_TOOL={tool}\n")

    def _set_worktree_base(self, path):
        with open(os.path.join(self.tmp, ".env"), "a", encoding="utf-8") as f:
            f.write(f"WORKTREE_BASE={path}\n")

    def _remote_develop(self):
        bare = os.path.join(self.tmp, "remote.git")
        self._git("init", "-q", "--bare", bare)
        self._git("-C", self.proj, "remote", "add", "origin", bare)
        self._git("-C", self.proj, "push", "-q", "-u", "origin", "develop")
        return bare

    def test_add_creates_worktree_and_branch(self):
        rc, path, err = self._wt("add", "stu-1", "develop")
        self.assertEqual(rc, 0, err)
        self.assertEqual(path, os.path.join(self.wtbase, "stu-1"))
        self.assertTrue(os.path.isdir(path), "worktree dir should exist")
        self.assertTrue(self._branch_exists("stu-1"), "branch should be created")

    def test_add_is_idempotent(self):
        _, p1, _ = self._wt("add", "stu-1", "develop")
        rc, p2, err = self._wt("add", "stu-1", "develop")
        self.assertEqual(rc, 0, err)
        self.assertEqual(p1, p2, "re-add should return the same path, not fail")

    def test_path_has_no_side_effects(self):
        rc, path, err = self._wt("path", "stu-1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(path, os.path.join(self.wtbase, "stu-1"))
        self.assertFalse(os.path.exists(path), "path verb must not create anything")
        self.assertFalse(self._branch_exists("stu-1"))

    def test_path_rejects_unknown_worktree_tool(self):
        self._set_worktree_tool("unknown")

        rc, path, err = self._wt("path", "stu-1")

        self.assertEqual(rc, 2)
        self.assertEqual(path, "")
        self.assertIn("unknown WORKTREE_TOOL", err)

    def test_add_rejects_existing_non_worktree_directory(self):
        stale = os.path.join(self.wtbase, "stu-1")
        os.makedirs(stale)

        rc, path, err = self._wt("add", "stu-1", "develop")

        self.assertNotEqual(rc, 0)
        self.assertEqual(path, "")
        self.assertIn("not a git worktree", err)

    def test_add_rejects_worktree_base_inside_project_dir(self):
        # WORKTREE_BASE inside the main checkout means every "isolated" worktree
        # lives in the main tree (its half-finished files leak into the project's
        # own test runs). A plain stale dir there also passes a naive
        # `rev-parse --is-inside-work-tree`, handing the caller a directory of
        # the MAIN checkout to edit — the exact isolation break this guards.
        self._set_worktree_base(os.path.join(self.proj, "worktrees"))

        rc, path, err = self._wt("add", "stu-1", "develop")

        self.assertNotEqual(rc, 0)
        self.assertEqual(path, "")
        self.assertIn("inside PROJECT_DIR", err)

    def test_add_refuses_stale_plain_dir_inside_another_checkout(self):
        # A stale plain directory whose path sits inside SOME git checkout is
        # inside-a-work-tree but not a worktree root; it must be rejected, not
        # handed back for the build to edit.
        other = os.path.join(self.tmp, "other")
        self._git("init", "-q", "-b", "main", other, cwd=self.tmp)
        self._set_worktree_base(os.path.join(other, "wts"))
        os.makedirs(os.path.join(other, "wts", "stu-1"))

        rc, path, err = self._wt("add", "stu-1", "develop")

        self.assertNotEqual(rc, 0)
        self.assertEqual(path, "")
        self.assertIn("not a worktree root", err)

    def test_add_refuses_path_resolving_to_project_dir(self):
        # WORKTREE_BASE = parent of the project + branch = project basename makes
        # $WORKTREE_BASE/$branch resolve to $PROJECT_DIR itself. `add` must
        # refuse, never print the main checkout as "the isolated worktree".
        self._set_worktree_base(self.tmp)

        rc, path, err = self._wt("add", "proj", "develop")

        self.assertNotEqual(rc, 0)
        self.assertEqual(path, "")
        self.assertIn("main checkout", err)

    def test_add_refuses_reuse_on_wrong_branch(self):
        # Re-use (revise re-runs) must hand back a worktree checked out on the
        # requested branch — not silently let a build land on whatever branch a
        # leftover worktree happens to have checked out.
        _, path, _ = self._wt("add", "stu-1", "develop")
        self._git("-C", path, "checkout", "-q", "-b", "something-else")

        rc, out, err = self._wt("add", "stu-1", "develop")

        self.assertNotEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertIn("expected 'stu-1'", err)

    def test_add_refuses_standalone_clone_at_worktree_path(self):
        # A full clone parked at the worktree path is a MAIN checkout, not a
        # linked worktree of the project repo — commits there diverge from the
        # repo the loops manage, so it must be refused.
        clone = os.path.join(self.wtbase, "stu-3")
        self._git("clone", "-q", self.proj, clone, cwd=self.tmp)
        self._git("-C", clone, "checkout", "-q", "-b", "stu-3")

        rc, path, err = self._wt("add", "stu-3", "develop")

        self.assertNotEqual(rc, 0)
        self.assertEqual(path, "")
        self.assertIn("standalone checkout", err)

    def test_branch_names_cannot_escape_worktree_base(self):
        for bad in ("../escape", "a/../../b", ".."):
            rc, path, err = self._wt("add", bad, "develop")
            self.assertNotEqual(rc, 0, f"branch {bad!r} must be rejected")
            self.assertEqual(path, "")
        rc, path, _ = self._wt("path", "../escape")
        self.assertNotEqual(rc, 0, "path verb must reject escaping branches too")
        self.assertEqual(path, "")

    def test_remove_clears_worktree_and_branch(self):
        _, path, _ = self._wt("add", "stu-1", "develop")
        rc, _, err = self._wt("remove", "stu-1")
        self.assertEqual(rc, 0, err)
        self.assertFalse(os.path.isdir(path), "worktree dir should be gone")
        self.assertFalse(self._branch_exists("stu-1"), "branch should be deleted")

    def test_cleanup_removes_clean_worktree_merged_into_origin_base(self):
        self._remote_develop()
        _, path, _ = self._wt("add", "stu-1", "develop")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "-C", path, "commit", "--allow-empty", "-qm", "work")
        self._git("-C", self.proj, "merge", "-q", "--no-ff", "stu-1")
        self._git("-C", self.proj, "push", "-q", "origin", "develop")

        rc, out, err = self._wt("cleanup")

        self.assertEqual(rc, 0, err)
        self.assertIn("stu-1", out)
        self.assertFalse(os.path.isdir(path), "merged worktree should be gone")
        self.assertFalse(self._branch_exists("stu-1"), "merged branch should be deleted")

    def test_merged_reports_unmerged_worktree_as_false(self):
        self._remote_develop()
        self._wt("add", "stu-1", "develop")

        rc, out, err = self._wt("merged", "stu-1")

        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertEqual(err, "")

    def test_merged_reports_branch_merged_into_origin_base(self):
        self._remote_develop()
        _, path, _ = self._wt("add", "stu-1", "develop")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "-C", path, "commit", "--allow-empty", "-qm", "work")
        self._git("-C", self.proj, "merge", "-q", "--no-ff", "stu-1")
        self._git("-C", self.proj, "push", "-q", "origin", "develop")

        rc, out, err = self._wt("merged", "stu-1")

        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")

    def test_add_recovers_branch_from_origin(self):
        # Revise after a cleaned-up worktree: no local branch, but the PR branch is on
        # origin. The helper must base the worktree on origin/<branch>, NOT develop,
        # or the PR's commits are silently lost.
        self._remote_develop()
        self._git("-C", self.proj, "checkout", "-q", "-b", "stu-2")
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "-C", self.proj, "commit", "--allow-empty", "-qm", "pr work")
        sha = subprocess.run(["git", "-C", self.proj, "rev-parse", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        self._git("-C", self.proj, "push", "-q", "origin", "stu-2")
        self._git("-C", self.proj, "checkout", "-q", "develop")
        self._git("-C", self.proj, "branch", "-D", "stu-2")  # local branch gone

        rc, path, err = self._wt("add", "stu-2", "develop")
        self.assertEqual(rc, 0, err)
        head = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, sha, "worktree should be recovered from origin/stu-2")

    def test_stdout_is_only_the_path(self):
        # Callers do WT="$(cadence worktree add ...)"; tool chatter must go to stderr.
        rc, path, _ = self._wt("add", "stu-1", "develop")
        self.assertEqual(rc, 0)
        self.assertEqual(path.count("\n"), 0, "stdout must be exactly one line (the path)")
        self.assertTrue(path.endswith("/stu-1"))


if __name__ == "__main__":
    unittest.main()
