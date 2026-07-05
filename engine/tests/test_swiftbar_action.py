import importlib.util, os, unittest
from unittest import mock


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(__file__), *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


plugin = _load("cadence_swiftbar", "..", "..", "assets", "swiftbar", "cadence.2m.py")


class SwiftBarActionTest(unittest.TestCase):
    # SwiftBar drops params with an empty value, shifting later positional args.
    # action() must therefore never emit an empty value — empties go out as "-".
    def test_no_empty_param_values(self):
        for add, remove, config, done in [
            ([], ["agent:pr-open"], "", "completed"),   # Set as merged
            ([], ["agent:hold"], "/p/.env", ""),        # Release hold
            (["agent:hold"], [], "", ""),               # Hold, default project
        ]:
            line = plugin.action("", "t", add, remove, config, "TASK-1", "file", done)
            self.assertNotIn('=""', line, line)

    def test_set_merged_keeps_remove_and_close_aligned(self):
        line = plugin.action("", "Set as merged", [], ["agent:pr-open"],
                             "", "TASK-1", "file", done="completed")
        self.assertIn('param4="-"', line)                # add -> placeholder
        self.assertIn('param5="agent:pr-open"', line)    # remove stays put
        self.assertIn('param6="completed"', line)        # close stays put

    def test_task_with_unmerged_worktree_does_not_get_cleanup_action(self):
        plugin.OUT.clear()
        task = {"identifier": "TASK-1", "title": "Task", "stage": {"name": "pr-open"}}
        with mock.patch.object(plugin, "worktree_merged", return_value=False):
            plugin.render_task("--", task, "/p/.env", "file", "/p/cadence/tasks.md")
        self.assertTrue(any("Set as merged" in line for line in plugin.OUT), plugin.OUT)
        self.assertFalse(any("Clean up worktree" in line for line in plugin.OUT), plugin.OUT)

    def test_merged_task_gets_cleanup_action(self):
        plugin.OUT.clear()
        task = {"identifier": "TASK-1", "title": "Task", "stage": {"name": "revised"}}
        with mock.patch.object(plugin, "worktree_merged", return_value=True):
            plugin.render_task("--", task, "/p/.env", "file", "/p/cadence/tasks.md")
        self.assertTrue(any("Set as merged" in line for line in plugin.OUT), plugin.OUT)
        self.assertTrue(any("Clean up worktree" in line and "worktree" in line
                            and "remove" in line and "task-1" in line
                            for line in plugin.OUT), plugin.OUT)

    def test_task_with_pr_url_gets_open_pr_link(self):
        plugin.OUT.clear()
        task = {
            "identifier": "TASK-1",
            "title": "Task",
            "description": "Draft PR: https://github.com/o/r/pull/42 opened.",
            "stage": {"name": "pr-open"},
        }
        with mock.patch.object(plugin, "worktree_merged", return_value=False):
            plugin.render_task("--", task, "/p/.env", "file", "/p/cadence/tasks.md")

        self.assertTrue(any("Open PR | href=https://github.com/o/r/pull/42" in line
                            for line in plugin.OUT), plugin.OUT)


if __name__ == "__main__":
    unittest.main()
