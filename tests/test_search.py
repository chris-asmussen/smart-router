"""Dependency-free tests for search + skill-frontmatter parsing.

Run: python3 -m unittest tests.test_search
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from warden.catalog import _parse_frontmatter, load_skills
from warden.search import search_catalog


class SearchCatalogTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {
                "type": "tool", "server": "gh", "name": "create_issue",
                "description": "Create a GitHub issue",
                "input_schema": {"properties": {"title": {}, "body": {}}},
            },
            {
                "type": "tool", "server": "weather", "name": "get_weather",
                "description": "Get the current weather for a city",
                "input_schema": {},
            },
        ]

    def test_keyword_match_ranks_relevant_tool_first(self):
        results = search_catalog(self.entries, "weather in london", limit=5)
        self.assertEqual(results[0]["name"], "get_weather")

    def test_regex_query_matches(self):
        results = search_catalog(self.entries, "^create_", limit=5)
        self.assertEqual(results[0]["name"], "create_issue")

    def test_no_match_returns_empty(self):
        self.assertEqual(search_catalog(self.entries, "zzz-nonexistent-thing", limit=5), [])

    def test_limit_is_respected(self):
        many = self.entries * 5
        results = search_catalog(many, "weather", limit=2)
        self.assertLessEqual(len(results), 2)


class SkillFrontmatterTests(unittest.TestCase):
    def test_parse_frontmatter(self):
        text = "---\nname: pdf\ndescription: Handles PDF files\n---\nBody text"
        meta = _parse_frontmatter(text)
        self.assertEqual(meta["name"], "pdf")
        self.assertEqual(meta["description"], "Handles PDF files")

    def test_load_skills_from_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = pathlib.Path(tmp) / "myskill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: myskill\ndescription: does a thing\n---\nInstructions here"
            )
            skills = load_skills([tmp])
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0]["name"], "myskill")


if __name__ == "__main__":
    unittest.main()
