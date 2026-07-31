# tests/test_migrate.py
import pathlib, sys, tempfile, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests.fixtures.fake_claude_home import build_fake_claude_home
from smart_router.claude_env import ClaudeEnv
from smart_router.registry import Registry, add_mcp_server
from smart_router.migrate import plan_migration

class PlanTests(unittest.TestCase):
    def _env_reg(self, tmp):
        return ClaudeEnv(build_fake_claude_home(pathlib.Path(tmp)/"h")), Registry(path=pathlib.Path(tmp)/"config.json")

    def test_plan_all_selects_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, reg = self._env_reg(tmp)
            plan = plan_migration(env, reg, {"mcp": "all", "plugins": "all", "personal_skills": "all"})
            self.assertIn("github", plan.register_mcp)
            self.assertIn("alpha@example-market", plan.disable_plugins)
            self.assertTrue(any(m["name"] == "myskill" for m in plan.move_personal_skills))

    def test_plan_excludes_already_registered_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, reg = self._env_reg(tmp)
            add_mcp_server(reg, "github", "npx")
            plan = plan_migration(env, reg, {"mcp": "all", "plugins": [], "personal_skills": []})
            self.assertNotIn("github", plan.register_mcp)

    def test_plan_respects_explicit_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            env, reg = self._env_reg(tmp)
            plan = plan_migration(env, reg, {"mcp": ["local"], "plugins": [], "personal_skills": []})
            self.assertEqual(list(plan.register_mcp), ["local"])


from smart_router.migrate import apply_migration, restore
from smart_router.registry import save_registry, load_registry

class ApplyRestoreTests(unittest.TestCase):
    def test_apply_then_restore_is_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            import json
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(home)
            reg = Registry(path=pathlib.Path(tmp) / "cfg" / "config.json")
            before_settings = json.loads((home / ".claude" / "settings.json").read_text())
            before_claude = json.loads((home / ".claude.json").read_text())
            plan = plan_migration(env, reg, {"mcp": "all", "plugins": "all", "personal_skills": "all"})
            manifest = apply_migration(env, reg, plan, run_id="r1", timestamp="2026-07-30T00:00:00Z")
            # applied: plugin disabled, mcp gone, skill moved, registry populated
            self.assertFalse(env.enabled_plugins()["alpha@example-market"])
            self.assertNotIn("github", env.discover_mcp_servers())
            self.assertTrue(reg.mcp_servers)
            # restore reverts everything (compare parsed JSON, not bytes — formatting/key order is not load-bearing)
            self.assertTrue(restore(env, reg, "r1"))
            self.assertEqual(json.loads((home / ".claude" / "settings.json").read_text()), before_settings)
            self.assertEqual(json.loads((home / ".claude.json").read_text()), before_claude)
            self.assertEqual([s["name"] for s in env.discover_personal_skills()], ["myskill"])
            self.assertEqual(reg.mcp_servers, {})
            self.assertEqual(reg.migrations, [])

    def test_restore_unknown_id_is_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(pathlib.Path(tmp)/"h"))
            reg = Registry(path=pathlib.Path(tmp)/"config.json")
            self.assertFalse(restore(env, reg, "nope"))


class AtomicApplyTests(unittest.TestCase):
    def test_precheck_collision_leaves_everything_unmutated(self):
        # Fix 1: a pre-existing managed-skill dest must fail fast with NOTHING mutated.
        with tempfile.TemporaryDirectory() as tmp:
            import json
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(home)
            cfg = pathlib.Path(tmp) / "cfg" / "config.json"
            reg = Registry(path=cfg)
            before_settings = json.loads((home / ".claude" / "settings.json").read_text())
            before_claude = json.loads((home / ".claude.json").read_text())
            plan = plan_migration(env, reg, {"mcp": "all", "plugins": "all", "personal_skills": "all"})
            # pre-create the managed destination so the personal-skill move would collide
            (cfg.parent / "skills" / "myskill").mkdir(parents=True)
            with self.assertRaises(FileExistsError):
                apply_migration(env, reg, plan, run_id="rX", timestamp="t")
            # Claude side byte-for-byte (semantic JSON) unchanged
            self.assertEqual(json.loads((home / ".claude" / "settings.json").read_text()), before_settings)
            self.assertEqual(json.loads((home / ".claude.json").read_text()), before_claude)
            self.assertIn("github", env.discover_mcp_servers())
            self.assertIs(env.enabled_plugins()["alpha@example-market"], True)
            # registry untouched; config.json never written
            self.assertEqual(reg.migrations, [])
            self.assertFalse(cfg.exists())

    def test_late_failure_rolls_back_disk_mutations(self):
        # Fix 1: a failure AFTER plugin-disable + mcp-removal hit disk must be rolled back.
        with tempfile.TemporaryDirectory() as tmp:
            import json
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(home)
            reg = Registry(path=pathlib.Path(tmp) / "cfg" / "config.json")
            before_settings = json.loads((home / ".claude" / "settings.json").read_text())
            before_claude = json.loads((home / ".claude.json").read_text())
            plan = plan_migration(env, reg, {"mcp": "all", "plugins": "all", "personal_skills": "all"})
            def boom(*a, **k):
                raise RuntimeError("boom")
            env.move_personal_skill = boom  # fail once plugins/mcp are already mutated
            with self.assertRaises(RuntimeError):
                apply_migration(env, reg, plan, run_id="rY", timestamp="t")
            self.assertEqual(json.loads((home / ".claude" / "settings.json").read_text()), before_settings)
            self.assertEqual(json.loads((home / ".claude.json").read_text()), before_claude)
            self.assertEqual([s["name"] for s in env.discover_personal_skills()], ["myskill"])
            self.assertEqual(reg.migrations, [])

    def test_restore_second_keeps_shared_managed_dir(self):
        # Fix 3: restoring a later migration must not de-register a managed dir the
        # first migration still relies on.
        with tempfile.TemporaryDirectory() as tmp:
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            sk2 = home / ".claude" / "skills" / "otherskill"
            sk2.mkdir(parents=True)
            (sk2 / "SKILL.md").write_text("---\nname: otherskill\ndescription: d\n---\nBody")
            env = ClaudeEnv(home)
            cfg = pathlib.Path(tmp) / "cfg" / "config.json"
            reg = Registry(path=cfg)
            managed = str((cfg.parent / "skills").resolve())
            p1 = plan_migration(env, reg, {"mcp": [], "plugins": [], "personal_skills": ["myskill"]})
            apply_migration(env, reg, p1, run_id="m1", timestamp="t1")
            p2 = plan_migration(env, reg, {"mcp": [], "plugins": [], "personal_skills": ["otherskill"]})
            m2 = apply_migration(env, reg, p2, run_id="m2", timestamp="t2")
            # second migration did NOT re-register the shared managed dir (dedup -> False)
            self.assertEqual(m2["registered"]["skill_dirs"], [])
            resolved = [str(pathlib.Path(p).resolve()) for p in reg.skill_dirs]
            self.assertIn(managed, resolved)
            # restoring m2 leaves the managed dir registered for m1
            self.assertTrue(restore(env, reg, "m2"))
            self.assertIn(managed, [str(pathlib.Path(p).resolve()) for p in reg.skill_dirs])
            self.assertIn("m1", [m["id"] for m in reg.migrations])


class ClaudeEnvGuardTests(unittest.TestCase):
    def test_move_back_refuses_existing_dest(self):
        # Fix 2: move_back must not nest into an existing destination.
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(build_fake_claude_home(pathlib.Path(tmp) / "h"))
            frm = pathlib.Path(tmp) / "src"; frm.mkdir()
            (frm / "f.txt").write_text("x")
            to = pathlib.Path(tmp) / "dst"; to.mkdir()
            with self.assertRaises(FileExistsError):
                env.move_back(str(frm), str(to))
            self.assertTrue(frm.exists())
            self.assertFalse((to / "f.txt").exists())
            self.assertFalse((to / "src").exists())

    def test_backup_preserves_pristine_across_repeated_writes(self):
        # Fix 4: two same-file mutations in one run keep a single PRISTINE backup.
        with tempfile.TemporaryDirectory() as tmp:
            import json
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = ClaudeEnv(home)
            backup_dir = pathlib.Path(tmp) / "backups"
            env.disable_plugin("alpha@example-market", backup_dir, "run1")
            env.disable_plugin("beta@other-market", backup_dir, "run1")
            baks = list(backup_dir.glob("settings.json.bak-run1"))
            self.assertEqual(len(baks), 1)
            pristine = json.loads(baks[0].read_text())
            self.assertIs(pristine["enabledPlugins"]["alpha@example-market"], True)
            self.assertIs(pristine["enabledPlugins"]["beta@other-market"], True)
