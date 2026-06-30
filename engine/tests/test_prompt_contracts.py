import os
import re
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SKILLS = os.path.join(ROOT, "skills")


class TestLoopPromptContracts(unittest.TestCase):
    def test_loop_prompts_do_not_hardcode_develop_as_runtime_base_branch(self):
        patterns = [
            re.compile(r"origin/develop"),
            re.compile(r"--base\s+develop"),
            re.compile(r"worktree add [^\n`]* develop"),
            re.compile(r"against `develop`"),
            re.compile(r"off develop"),
        ]
        offenders = []
        for name in os.listdir(SKILLS):
            if not name.startswith("cadence-loop-"):
                continue
            path = os.path.join(SKILLS, name, "SKILL.md")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for pattern in patterns:
                for match in pattern.finditer(text):
                    offenders.append("%s: %s" % (path, match.group(0)))

        self.assertEqual(offenders, [])

    def test_build_prompt_is_provider_neutral_for_the_orchestrator_role(self):
        path = os.path.join(SKILLS, "cadence-loop-build", "SKILL.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()

        self.assertNotIn("You (Opus) orchestrate", text)
        self.assertNotIn("headless `claude -p`", text)


if __name__ == "__main__":
    unittest.main()
