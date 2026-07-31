# tests/test_cli.py
import io, json, pathlib, sys, tempfile, unittest
from contextlib import redirect_stdout, redirect_stderr
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests.fixtures.fake_claude_home import build_fake_claude_home
from smart_router.cli import run

class CliTests(unittest.TestCase):
    def _env(self, tmp):
        cfg = pathlib.Path(tmp) / "cfg" / "config.json"
        return {"SMART_ROUTER_CONFIG": str(cfg), "SMART_ROUTER_HOME": str(pathlib.Path(tmp) / "cfg")}

    def test_add_mcp_then_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            self.assertEqual(run(["add-mcp", "gh", "--command", "npx", "--args", "-y", "srv"], env=env), 0)
            out = io.StringIO()
            with redirect_stdout(out):
                run(["list"], env=env)
            self.assertIn("gh", out.getvalue())

    def test_add_mcp_env_without_equals_is_friendly_error(self):
        # Fix 5: `--env KEY` (no '=') should exit nonzero with a clear message, not a traceback.
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            err = io.StringIO()
            with redirect_stderr(err):
                rc = run(["add-mcp", "gh", "--command", "npx", "--env", "KEY"], env=env)
            self.assertNotEqual(rc, 0)
            self.assertIn("invalid --env 'KEY'", err.getvalue())
            self.assertIn("KEY=VALUE", err.getvalue())

    def test_migrate_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = self._env(tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                run(["migrate", "--all"], env=env, home=home)
            self.assertIn("dry run", out.getvalue())
            # dry run must not disable anything on the Claude side
            settings = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertIs(settings["enabledPlugins"]["alpha@example-market"], True)

    def test_home_flag_targets_fake_home_and_restore_reverts(self):
        # The --home flag (not the function-param home) must scope migrate/restore to
        # the given Claude home, so users can test against a throwaway tree.
        with tempfile.TemporaryDirectory() as tmp:
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            env = self._env(tmp)
            before = json.loads((home / ".claude" / "settings.json").read_text())
            out = io.StringIO()
            with redirect_stdout(out):
                rc = run(["migrate", "--all", "--apply", "--home", str(home)], env=env)
            self.assertEqual(rc, 0)
            # applied against the fake home
            after = json.loads((home / ".claude" / "settings.json").read_text())
            self.assertFalse(after["enabledPlugins"]["alpha@example-market"])
            # recover the migration id from the CLI output and restore via --home
            mig_id = out.getvalue().split("id=", 1)[1].split(")", 1)[0].split(".", 1)[0].strip()
            rc = run(["restore", "--id", mig_id, "--home", str(home)], env=env)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads((home / ".claude" / "settings.json").read_text()), before)
