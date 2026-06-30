import importlib.util, os, tempfile, types, unittest


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(__file__), *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load by unique module name so discovery doesn't collide with the linear
# adapter's identically-named `cli` module (both shadow sys.modules["cli"]).
cli = _load("cadence_memory_cli", "..", "memory", "cli.py")

def env_with_dir():
    d = tempfile.mkdtemp()
    return {"MEMORY_DIR": d}, d

RULE = """---
name: money-in-pence
importance: 5
description: Money stored as integer pence
---
Order.total is pence. Never treat as pounds.
"""

class TestMemoryMarkdown(unittest.TestCase):
    def test_remember_then_recall(self):
        env, d = env_with_dir()
        cli.cmd_remember(types.SimpleNamespace(
            importance=5, title="Money in pence",
            body="Order.total is pence."), env)
        files = os.listdir(d)
        self.assertEqual(len(files), 1)
        out = cli.cmd_recall(types.SimpleNamespace(min_importance=4, limit=10), env)
        self.assertEqual(out[0]["importance"], 5)
        self.assertIn("pence", out[0]["body"])

    def test_recall_filters_and_sorts_by_importance(self):
        env, d = env_with_dir()
        with open(os.path.join(d, "a.md"), "w") as f:
            f.write(RULE)
        with open(os.path.join(d, "b.md"), "w") as f:
            f.write(RULE.replace("importance: 5", "importance: 2")
                        .replace("money-in-pence", "low-rule"))
        out = cli.cmd_recall(types.SimpleNamespace(min_importance=4, limit=10), env)
        self.assertEqual([r["name"] for r in out], ["money-in-pence"])

    def test_recall_respects_limit(self):
        env, d = env_with_dir()
        for i in range(3):
            with open(os.path.join(d, f"r{i}.md"), "w") as f:
                f.write(RULE.replace("money-in-pence", f"rule-{i}"))
        out = cli.cmd_recall(types.SimpleNamespace(min_importance=1, limit=2), env)
        self.assertEqual(len(out), 2)

if __name__ == "__main__":
    unittest.main()
