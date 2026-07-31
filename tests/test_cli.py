# tests/test_cli.py
import io, json, pathlib, sys, tempfile, unittest
from contextlib import redirect_stdout, redirect_stderr
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tests.fixtures.fake_claude_home import build_fake_claude_home
from warden.cli import run

class CliTests(unittest.TestCase):
    def _env(self, tmp):
        cfg = pathlib.Path(tmp) / "cfg" / "config.json"
        return {"WARDEN_CONFIG": str(cfg), "WARDEN_HOME": str(pathlib.Path(tmp) / "cfg")}

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

    def _show(self, env):
        out = io.StringIO()
        with redirect_stdout(out):
            run(["routing", "show"], env=env)
        return json.loads(out.getvalue())

    def test_routing_set_mode_then_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            self.assertEqual(run(["routing", "set-mode", "ask"], env=env), 0)
            self.assertEqual(self._show(env)["mode"], "ask")

    def test_routing_prefer_exclude_add_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            self.assertEqual(run(["routing", "prefer", "gh.create_issue", "weather.get"], env=env), 0)
            self.assertEqual(run(["routing", "exclude", "weather.get"], env=env), 0)
            self.assertEqual(
                run(["routing", "add-rule", "--ext", "tsx", "jsx", "--prefer", "gh.create_issue"], env=env), 0)
            block = self._show(env)
            self.assertEqual(block["priority_order"], ["gh.create_issue", "weather.get"])
            self.assertEqual(block["exclude"], ["weather.get"])
            self.assertEqual(len(block["rules"]), 1)
            self.assertEqual(block["rules"][0]["when"]["extension"], ["tsx", "jsx"])
            self.assertEqual(block["rules"][0]["prefer"], ["gh.create_issue"])

    def test_routing_prefer_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            run(["routing", "prefer", "a", "b"], env=env)
            run(["routing", "prefer", "a", "c"], env=env)
            self.assertEqual(self._show(env)["priority_order"], ["a", "b", "c"])

    def test_routing_add_rule_glob(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            self.assertEqual(
                run(["routing", "add-rule", "--glob", "src/*.tsx", "--exclude", "weather.get"], env=env), 0)
            rule = self._show(env)["rules"][0]
            self.assertEqual(rule["when"]["path_glob"], "src/*.tsx")
            self.assertEqual(rule["exclude"], ["weather.get"])

    def test_routing_add_rule_requires_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            err = io.StringIO()
            with redirect_stderr(err):
                rc = run(["routing", "add-rule", "--prefer", "x"], env=env)
            self.assertNotEqual(rc, 0)
            self.assertIn("--ext", err.getvalue())

    def test_routing_add_rule_empty_ext_flag_errors(self):
        # Fix 1: `--ext` present with no values must NOT be silently dropped, even
        # when another selector (--glob) is set. It is a hard error (exit 2).
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            err = io.StringIO()
            with redirect_stderr(err):
                rc = run(["routing", "add-rule", "--ext", "--glob", "src/*.tsx", "--prefer", "x"], env=env)
            self.assertEqual(rc, 2)
            self.assertIn("--ext", err.getvalue())
            # Nothing should have been stored.
            self.assertEqual(self._show(env)["rules"], [])

    def test_routing_add_rule_no_selector_errors(self):
        # Fix 1: neither --ext nor --glob provided -> exit 2.
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            err = io.StringIO()
            with redirect_stderr(err):
                rc = run(["routing", "add-rule"], env=env)
            self.assertEqual(rc, 2)
            self.assertEqual(self._show(env)["rules"], [])

    def test_routing_add_rule_ext_prefer_still_works(self):
        # Fix 1 regression guard: a normal add-rule with a real --ext still works.
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            self.assertEqual(
                run(["routing", "add-rule", "--ext", "tsx", "--prefer", "a"], env=env), 0)
            rule = self._show(env)["rules"][0]
            self.assertEqual(rule["when"]["extension"], ["tsx"])
            self.assertEqual(rule["prefer"], ["a"])

    def test_routing_add_rule_ext_normalized_on_store(self):
        # Fix 2: `.TSX JSX` round-trips to normalized ["tsx", "jsx"] in storage.
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            self.assertEqual(
                run(["routing", "add-rule", "--ext", ".TSX", "JSX", "--prefer", "a"], env=env), 0)
            rule = self._show(env)["rules"][0]
            self.assertEqual(rule["when"]["extension"], ["tsx", "jsx"])

    def test_routing_no_subcommand_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            err = io.StringIO()
            with redirect_stderr(err):
                rc = run(["routing"], env=env)
            self.assertNotEqual(rc, 0)

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
