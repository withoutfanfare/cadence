import importlib.util, os, unittest


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
            ([], ["agent:pr-open"], "", "completed"),   # Mark merged
            ([], ["agent:hold"], "/p/.env", ""),        # Release hold
            (["agent:hold"], [], "", ""),               # Hold, default project
        ]:
            line = plugin.action("", "t", add, remove, config, "TASK-1", "file", done)
            self.assertNotIn('=""', line, line)

    def test_mark_merged_keeps_remove_and_close_aligned(self):
        line = plugin.action("", "✓ Mark merged", [], ["agent:pr-open"],
                             "", "TASK-1", "file", done="completed")
        self.assertIn('param4="-"', line)                # add -> placeholder
        self.assertIn('param5="agent:pr-open"', line)    # remove stays put
        self.assertIn('param6="completed"', line)        # close stays put


if __name__ == "__main__":
    unittest.main()
