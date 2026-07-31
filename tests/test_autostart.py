# tests/test_autostart.py
import pathlib, sys, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from warden import autostart as A

SKILLS = [
    {"name": "ponytail", "content": "---\nname: ponytail\n---\nBe lazy. Write less."},
    {"name": "greeter", "content": "Say hi."},
]


class AutostartTests(unittest.TestCase):
    def test_collect_preserves_order_and_reports_missing(self):
        chosen, missing = A.collect_auto_start(SKILLS, ["greeter", "nope", "ponytail"])
        self.assertEqual([s["name"] for s in chosen], ["greeter", "ponytail"])
        self.assertEqual(missing, ["nope"])

    def test_build_appends_full_content(self):
        chosen, _ = A.collect_auto_start(SKILLS, ["ponytail"])
        text, warnings = A.build_instructions("BASE", chosen)
        self.assertTrue(text.startswith("BASE"))
        self.assertIn("Be lazy. Write less.", text)
        self.assertIn("--- Skill: ponytail ---", text)
        self.assertEqual(warnings, [])

    def test_no_skills_returns_base_unchanged(self):
        text, warnings = A.build_instructions("BASE", [])
        self.assertEqual(text, "BASE")
        self.assertEqual(warnings, [])

    def test_missing_only_returns_base_unchanged(self):
        chosen, missing = A.collect_auto_start(SKILLS, ["nope"])
        text, _ = A.build_instructions("BASE", chosen)
        self.assertEqual(text, "BASE")
        self.assertEqual(missing, ["nope"])

    def test_oversize_is_truncated_and_warned(self):
        big = [{"name": "big", "content": "x" * 50000}]
        text, warnings = A.build_instructions("BASE", big, max_chars=1000)
        self.assertLess(len(text), 2000)
        self.assertIn("truncated", text)
        self.assertTrue(warnings)
        self.assertIn("auto_start", warnings[0])


if __name__ == "__main__":
    unittest.main()
