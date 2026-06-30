import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from cadence_env import load_env

class TestLoadEnv(unittest.TestCase):
    def _home_with(self, text):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, ".env"), "w", encoding="utf-8") as f:
            f.write(text)
        return d

    def test_parses_keys_and_strips_quotes(self):
        home = self._home_with('A=1\nB="two words"\n# comment\n\nC=\n')
        env = load_env(home)
        self.assertEqual(env["A"], "1")
        self.assertEqual(env["B"], "two words")
        self.assertEqual(env["C"], "")
        self.assertNotIn("#", env)

    def test_strips_inline_comment_from_unquoted_value(self):
        # Bash sources .env, so `K=v   # note` yields `v`; the Python loader
        # must match instead of keeping the comment as part of the value.
        home = self._home_with("K=lin_api_xxx          # personal API key\n")
        self.assertEqual(load_env(home)["K"], "lin_api_xxx")

    def test_quoted_value_keeps_spaces_and_drops_trailing_comment(self):
        home = self._home_with('K="Example Team"   # quote names with spaces\n')
        self.assertEqual(load_env(home)["K"], "Example Team")

    def test_blank_value_with_comment_is_empty(self):
        home = self._home_with("K=                   # only act on this user\n")
        self.assertEqual(load_env(home)["K"], "")

    def test_literal_hash_without_leading_space_is_kept(self):
        home = self._home_with("K=a#b\n")
        self.assertEqual(load_env(home)["K"], "a#b")

    def test_real_environ_overrides_file(self):
        home = self._home_with("A=fromfile\n")
        os.environ["A"] = "fromenv"
        try:
            self.assertEqual(load_env(home)["A"], "fromenv")
        finally:
            del os.environ["A"]

    def test_cadence_config_env_var_wins(self):
        home = self._home_with("A=home\n")
        config_dir = tempfile.mkdtemp()
        config_path = os.path.join(config_dir, "custom.env")
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("A=config\n")
        os.environ["CADENCE_CONFIG"] = config_path
        try:
            self.assertEqual(load_env(home)["A"], "config")
        finally:
            del os.environ["CADENCE_CONFIG"]

    def test_project_cadence_env_beats_home_env(self):
        home = self._home_with("A=home\n")
        project = tempfile.mkdtemp()
        os.makedirs(os.path.join(project, "cadence"))
        with open(os.path.join(project, "cadence", ".env"), "w", encoding="utf-8") as f:
            f.write("A=project\n")
        self.assertEqual(load_env(home, cwd=project)["A"], "project")

    def test_missing_env_file_is_empty_plus_environ(self):
        env = load_env(tempfile.mkdtemp())
        self.assertIsInstance(env, dict)

if __name__ == "__main__":
    unittest.main()
