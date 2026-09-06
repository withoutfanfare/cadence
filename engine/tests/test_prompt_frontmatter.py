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

    def test_literal_description_preserves_internal_blank_lines(self):
        text = "---\ndescription: |-\n  first paragraph\n\n  second paragraph\n---\nBody\n"

        self.assertEqual(
            render.extract_frontmatter_description(text),
            "first paragraph\n\nsecond paragraph",
        )

    def test_literal_description_applies_chomping_indicator(self):
        expected = {
            "|-": "line",
            "|": "line\n",
            "|+": "line\n\n",
        }
        for indicator, description in expected.items():
            with self.subTest(indicator=indicator):
                text = f"---\ndescription: {indicator}\n  line\n\n---\nBody\n"
                self.assertEqual(render.extract_frontmatter_description(text), description)

    def test_folded_description_preserves_paragraph_boundaries(self):
        text = (
            "---\ndescription: >-\n"
            "  first line\n"
            "  continues\n"
            "\n"
            "  second paragraph\n"
            "  continues too\n"
            "---\nBody\n"
        )

        self.assertEqual(
            render.extract_frontmatter_description(text),
            "first line continues\nsecond paragraph continues too",
        )


if __name__ == "__main__":
    unittest.main()
