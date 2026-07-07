import os, shutil, stat, subprocess, tempfile, unittest

# Hermetic tests for engine/scripts/run-implementer.sh's isolation guard: the
# implementer runs with vendor auto-approve flags, so the script must refuse to
# run it anywhere but the root of a LINKED git worktree — never the main
# checkout (PROJECT_DIR), a plain directory inside a checkout, or a non-repo
# path. A fake `claude` CLI in a throwaway $HOME/.local/bin records where (and
# whether) it ran.

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO, "engine", "scripts", "run-implementer.sh")


class TestRunImplementerIsolation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

        # Project repo with one commit, plus a linked worktree off it.
        self.proj = os.path.join(self.tmp, "proj")
        self._git("init", "-q", "-b", "develop", self.proj, cwd=self.tmp)
        self._git("-c", "user.email=t@t", "-c", "user.name=t",
                  "-C", self.proj, "commit", "--allow-empty", "-qm", "init")
        self.wt = os.path.join(self.tmp, "wts", "stu-1")
        os.makedirs(os.path.dirname(self.wt))
        self._git("-C", self.proj, "worktree", "add", self.wt, "-b", "stu-1")

        self.brief = os.path.join(self.tmp, "IMPLEMENT.md")
        with open(self.brief, "w", encoding="utf-8") as f:
            f.write("do the thing\n")

        # Fake HOME so the script's self-built PATH resolves our fake claude.
        self.home = os.path.join(self.tmp, "home")
        bindir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bindir)
        self.marker = os.path.join(self.tmp, "ran.txt")
        fake = os.path.join(bindir, "claude")
        with open(fake, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\npwd -P > "$MARKER_FILE"\n')
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IXUSR)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, *args, cwd=None):
        subprocess.run(["git", *args], cwd=cwd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _run(self, workdir):
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": self.home,
            "PROJECT_DIR": self.proj,
            "MARKER_FILE": self.marker,
        }
        r = subprocess.run(["bash", SCRIPT, "claude", workdir, self.brief],
                           env=env, capture_output=True, text=True)
        return r.returncode, r.stderr

    def test_runs_in_a_linked_worktree(self):
        rc, err = self._run(self.wt)
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.exists(self.marker), "implementer should have run")
        with open(self.marker, encoding="utf-8") as f:
            ran_in = f.read().strip()
        self.assertEqual(ran_in, os.path.realpath(self.wt))

    def test_refuses_the_main_checkout(self):
        rc, err = self._run(self.proj)
        self.assertEqual(rc, 3)
        self.assertIn("main checkout", err)
        self.assertFalse(os.path.exists(self.marker),
                         "implementer must never run in the main checkout")

    def test_refuses_a_plain_directory_inside_a_checkout(self):
        sub = os.path.join(self.proj, "src")
        os.makedirs(sub)
        rc, err = self._run(sub)
        self.assertEqual(rc, 3)
        self.assertIn("not a worktree root", err)
        self.assertFalse(os.path.exists(self.marker))

    def test_refuses_a_non_git_directory(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain)
        rc, err = self._run(plain)
        self.assertEqual(rc, 3)
        self.assertIn("not a git worktree", err)
        self.assertFalse(os.path.exists(self.marker))


if __name__ == "__main__":
    unittest.main()
