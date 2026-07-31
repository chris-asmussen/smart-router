import json, pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests.fixtures.fake_claude_home import build_fake_claude_home
from warden.claude_env import ClaudeEnv

class ClaudeEnvReadTests(unittest.TestCase):
    def test_discovers_mcp_servers_across_scopes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(tmp))
            servers = env.discover_mcp_servers()
            self.assertIn("github", servers)
            self.assertIn("local", servers)

    def test_discovers_personal_and_plugin_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(tmp))
            self.assertEqual([s["name"] for s in env.discover_personal_skills()], ["myskill"])
            plugin = env.discover_plugin_skills()
            self.assertEqual(plugin[0]["plugin_key"], "alpha@example-market")

    def test_plugin_skills_dedup_prefers_recorded_active_hash(self):
        # alpha is cached under two hash dirs (abc123, def456); installed_plugins.json
        # records abc123 as active even though def456 sorts greater. Exactly one entry,
        # and it must be the recorded active hash (fails under pure max-hash dedup).
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(tmp))
            alpha = [s for s in env.discover_plugin_skills() if s["name"] == "alpha"]
            self.assertEqual(len(alpha), 1)
            self.assertIn("abc123", alpha[0]["skill_md"])
            self.assertIn("abc123", alpha[0]["skills_root"])
            self.assertNotIn("def456", alpha[0]["skill_md"])

    def test_plugin_skills_dedup_falls_back_to_max_hash(self):
        # beta is cached under 1.0.0 and 2.0.0 but is absent from
        # installed_plugins.json, so dedup falls back to the max hash dir.
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(tmp))
            sp = [s for s in env.discover_plugin_skills() if s["name"] == "beta"]
            self.assertEqual(len(sp), 1)
            self.assertIn("2.0.0", sp[0]["skill_md"])
            self.assertNotIn("1.0.0", sp[0]["skill_md"])

    def test_enabled_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(tmp))
            self.assertTrue(env.enabled_plugins()["alpha@example-market"])


class ClaudeEnvWriteTests(unittest.TestCase):
    def test_disable_plugin_records_prev_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(root)
            backup = pathlib.Path(tmp) / "b"; backup.mkdir()
            action = env.disable_plugin("alpha@example-market", backup, "r1")
            self.assertEqual(action["prev"], True)
            self.assertFalse(env.enabled_plugins()["alpha@example-market"])
            self.assertTrue(any(backup.iterdir()))
            env.enable_plugin("alpha@example-market")
            self.assertTrue(env.enabled_plugins()["alpha@example-market"])

    def test_enable_plugin_can_restore_recorded_prior_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(root)
            backup = pathlib.Path(tmp) / "b"; backup.mkdir()
            env.disable_plugin("alpha@example-market", backup, "r1")
            # restoring the recorded prior state (False) leaves it disabled
            env.enable_plugin("alpha@example-market", enabled=False)
            self.assertFalse(env.enabled_plugins()["alpha@example-market"])
            # default enables it
            env.enable_plugin("alpha@example-market")
            self.assertTrue(env.enabled_plugins()["alpha@example-market"])

    def test_disable_enable_handle_null_enabled_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_fake_claude_home(pathlib.Path(tmp) / "h")
            (root / ".claude" / "settings.json").write_text(
                json.dumps({"enabledPlugins": None}), encoding="utf-8")
            env = ClaudeEnv(root)
            backup = pathlib.Path(tmp) / "b"; backup.mkdir()
            action = env.disable_plugin("some@mkt", backup, "r1")
            self.assertEqual(action["prev"], True)
            self.assertFalse(env.enabled_plugins()["some@mkt"])
            env.enable_plugin("some@mkt")
            self.assertTrue(env.enabled_plugins()["some@mkt"])

    def test_move_personal_skill_raises_if_dest_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(root); backup = pathlib.Path(tmp) / "b"; backup.mkdir()
            dest = pathlib.Path(tmp) / "managed"; (dest / "myskill").mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                env.move_personal_skill("myskill", dest, backup, "r1")

    def test_remove_and_readd_mcp_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(root); backup = pathlib.Path(tmp) / "b"; backup.mkdir()
            action = env.remove_mcp_server("github", backup, "r1")
            self.assertNotIn("github", env.discover_mcp_servers())
            env.add_mcp_server_raw("github", action["value"], action["scope"])
            self.assertIn("github", env.discover_mcp_servers())

    def test_move_personal_skill_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(root); backup = pathlib.Path(tmp) / "b"; backup.mkdir()
            dest = pathlib.Path(tmp) / "managed"; dest.mkdir()
            action = env.move_personal_skill("myskill", dest, backup, "r1")
            self.assertTrue((dest / "myskill" / "SKILL.md").exists())
            self.assertEqual(env.discover_personal_skills(), [])
            env.move_back(action["to"], action["from"])
            self.assertEqual([s["name"] for s in env.discover_personal_skills()], ["myskill"])
