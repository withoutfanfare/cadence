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

    def test_remove_clears_worktree_and_branch(self):
        _, path, _ = self._wt("add", "stu-1", "develop")
        rc, _, err = self._wt("remove", "stu-1")
        self.assertEqual(rc, 0, err)
        self.assertFalse(os.path.isdir(path), "worktree dir should be gone")
        self.assertFalse(self._branch_exists("stu-1"), "branch should be deleted")

    def test_add_recovers_branch_from_origin(self):
        # Revise after a cleaned-up worktree: no local branch, but the PR branch is on
        # origin. The helper must base the worktree on origin/<branch>, NOT develop,
        # or the PR's commits are silently lost.
        bare = os.path.join(self.tmp, "remote.git")
        self._git("init", "-q", "--bare", bare)
        self._git("-C", self.proj, "remote", "add", "origin", bare)
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
