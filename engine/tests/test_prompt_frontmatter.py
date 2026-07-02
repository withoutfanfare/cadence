import contextlib
import importlib.util
import io
import os
import unittest


def _load(name, *relpath):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(os.path.dirname(__file__), *relpath))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


render = _load("cadence_prompt_render", "..", "prompts", "render.py")


class TestFrontmatterTolerance(unittest.TestCase):
    def test_crlf_frontmatter_is_stripped(self):
        text = "---\r\nname: x\r\ndescription: hello\r\n---\r\nBody line\r\n"
        self.assertEqual(render.strip_frontmatter(text), "Body line\n")
        self.assertEqual(render.extract_frontmatter_description(text), "hello")

    def test_trailing_space_on_delimiter_is_tolerated(self):
        text = "--- \nname: x\ndescription: hi\n--- \nBody\n"
        self.assertEqual(render.strip_frontmatter(text), "Body\n")
        self.assertEqual(render.extract_frontmatter_description(text), "hi")

    def test_missing_closing_delimiter_warns_and_keeps_body(self):
        text = "---\nname: x\ndescription: hi\nBody with no close\n"
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            out = render.strip_frontmatter(text)
        self.assertEqual(out, text)  # whole file preserved, not silently mangled
        self.assertIn("no closing frontmatter", buf.getvalue())

    def test_no_frontmatter_returns_text_unchanged(self):
        text = "Just a body\n"
        self.assertEqual(render.strip_frontmatter(text), text)
        self.assertIsNone(render.extract_frontmatter_description(text))


if __name__ == "__main__":
    unittest.main()
