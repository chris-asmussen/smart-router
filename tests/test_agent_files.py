# tests/test_agent_files.py
import pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from warden import agent_files as A


class AgentFilesTests(unittest.TestCase):
    def test_block_has_markers_and_route_first(self):
        block = A.capability_block()
        self.assertIn(A.BEGIN, block)
        self.assertIn(A.END, block)
        # route is the primary path; search is the fallback.
        self.assertLess(block.index("`route`"), block.index("`search`"))

    def test_insert_into_empty_is_detectable(self):
        out = A.insert_block("")
        self.assertTrue(A.has_block(out))
        self.assertTrue(out.endswith("\n"))

    def test_insert_preserves_existing_content_with_blank_line(self):
        out = A.insert_block("# My rules\n")
        self.assertIn("# My rules", out)
        self.assertIn(A.BEGIN, out)
        self.assertIn("\n\n" + A.BEGIN, out)  # one blank line before the block

    def test_insert_when_text_lacks_trailing_newline(self):
        out = A.insert_block("# rules")  # no trailing newline
        self.assertIn("# rules", out)
        self.assertTrue(A.has_block(out))
        self.assertIn("\n\n" + A.BEGIN, out)

    def test_insert_is_idempotent(self):
        once = A.insert_block("# rules\n")
        twice = A.insert_block(once)
        self.assertEqual(once, twice)
        self.assertEqual(once.count(A.BEGIN), 1)

    def test_insert_replaces_stale_block_in_place(self):
        stale = f"# rules\n\n{A.BEGIN}\nOLD TEXT\n{A.END}\n"
        out = A.insert_block(stale)
        self.assertNotIn("OLD TEXT", out)
        self.assertEqual(out.count(A.BEGIN), 1)
        self.assertIn("`route`", out)

    def test_remove_restores_original_byte_for_byte(self):
        original = "# rules\n"
        out = A.remove_block(A.insert_block(original))
        self.assertEqual(out, original)

    def test_remove_leaves_unrelated_blank_runs_untouched(self):
        # A deliberate 4-newline gap elsewhere must survive a round trip. The old
        # global collapse would have flattened it to a single blank line.
        original = "# rules\n\n\n\nother section\n"
        out = A.remove_block(A.insert_block(original))
        self.assertEqual(out, original)

    def test_remove_is_noop_without_block(self):
        self.assertEqual(A.remove_block("# rules\n"), "# rules\n")

    def test_candidate_path_user_scope_uses_home(self):
        home = pathlib.Path("/h")
        cwd = pathlib.Path("/w")
        self.assertEqual(A.candidate_path("CLAUDE.md", "user", home, cwd), home / ".claude" / "CLAUDE.md")
        self.assertEqual(A.candidate_path("AGENTS.md", "user", home, cwd), home / ".codex" / "AGENTS.md")

    def test_candidate_path_project_and_local_use_cwd(self):
        home = pathlib.Path("/h")
        cwd = pathlib.Path("/w")
        self.assertEqual(A.candidate_path("CLAUDE.md", "project", home, cwd), cwd / "CLAUDE.md")
        self.assertEqual(A.candidate_path("CLAUDE.md", "local", home, cwd), cwd / "CLAUDE.local.md")

    def test_discover_flags_existing_and_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp) / "home"
            cwd = pathlib.Path(tmp) / "proj"
            (home / ".claude").mkdir(parents=True)
            (cwd).mkdir(parents=True)
            (home / ".claude" / "CLAUDE.md").write_text("# global\n", encoding="utf-8")
            (cwd / "CLAUDE.md").write_text(A.insert_block("# proj\n"), encoding="utf-8")
            found = {(d["scope"], d["name"]): d for d in A.discover(home, cwd)}
            self.assertTrue(found[("user", "CLAUDE.md")]["exists"])
            self.assertFalse(found[("user", "CLAUDE.md")]["has_block"])
            self.assertTrue(found[("project", "CLAUDE.md")]["exists"])
            self.assertTrue(found[("project", "CLAUDE.md")]["has_block"])
            self.assertFalse(found[("local", "CLAUDE.md")]["exists"])

    def test_apply_to_file_creates_then_removes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "nested" / "CLAUDE.md"
            self.assertTrue(A.apply_to_file(path))          # creates dir + file
            self.assertTrue(A.has_block(path.read_text(encoding="utf-8")))
            self.assertFalse(A.apply_to_file(path))         # idempotent: no change
            self.assertTrue(A.apply_to_file(path, remove=True))
            self.assertFalse(A.has_block(path.read_text(encoding="utf-8")))

    def test_apply_remove_on_missing_file_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "CLAUDE.md"
            self.assertFalse(A.apply_to_file(path, remove=True))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
