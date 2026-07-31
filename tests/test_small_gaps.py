"""Focused unit tests for otherwise-uncovered branches across the pure modules
(catalog frontmatter edges, config resolution, search regex-error swallow,
routing validation/degrade branches, migrate skip/rollback, registry, claude_env,
and the cli serve/add-skill/env/main paths). All hermetic: temp dirs + explicit
env, never a real ~/.claude or ~/.config/warden.
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tests.fixtures.fake_claude_home import build_fake_claude_home
from warden import catalog, config, migrate, registry, routing, search
from warden.claude_env import ClaudeEnv


class CatalogFrontmatterEdgeTests(unittest.TestCase):
    def test_no_frontmatter_marker_returns_empty(self):
        self.assertEqual(catalog._parse_frontmatter("# Just a heading\nbody"), {})

    def test_unterminated_frontmatter_returns_empty(self):
        self.assertEqual(catalog._parse_frontmatter("---\nname: x\nno closing fence"), {})


class ConfigResolutionEdgeTests(unittest.TestCase):
    def test_resolve_uses_home_config_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            (home / "config.json").write_text("{}")
            env = {"WARDEN_HOME": str(home)}  # no WARDEN_CONFIG
            self.assertEqual(config.resolve_config_path(env=env), home / "config.json")

    def test_writable_honors_explicit_path(self):
        p = config.writable_config_path(path="/somewhere/x.json", env={})
        self.assertEqual(p, pathlib.Path("/somewhere/x.json"))

    def test_config_dir_is_parent_of_resolved(self):
        env = {"WARDEN_CONFIG": "/a/b/config.json"}
        self.assertEqual(config.config_dir(env=env), pathlib.Path("/a/b"))


class SearchRegexErrorTests(unittest.TestCase):
    def test_invalid_regex_query_is_swallowed_and_scores_by_keyword(self):
        entry = {"name": "grep_tool", "description": "search text"}
        # "[" is an invalid regex -> re.error swallowed; token "grep" still scores.
        self.assertEqual(search.score(entry, "["), 0)
        self.assertGreater(search.score(entry, "grep"), 0)


class RoutingBranchTests(unittest.TestCase):
    def test_normalize_ext_passes_through_non_string(self):
        self.assertEqual(routing._normalize_ext(123), 123)

    def test_rules_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            routing._validate_routing({"rules": "nope"})

    def test_rule_when_not_object_raises(self):
        with self.assertRaises(ValueError):
            routing._validate_routing({"rules": [{"when": 5}]})

    def test_rule_path_glob_not_string_raises(self):
        with self.assertRaises(ValueError):
            routing._validate_routing({"rules": [{"when": {"path_glob": 7}}]})

    def test_rule_prefer_not_string_list_raises(self):
        with self.assertRaises(ValueError):
            routing._validate_routing({"rules": [{"when": {}, "prefer": [1, 2]}]})

    def test_context_without_extension_or_path_yields_no_extension_match(self):
        # Active extension rule but context has neither extension nor file_path:
        # _context_extension returns None, so the rule does not match.
        rout = {"mode": "auto", "priority_order": [], "exclude": [],
                "rules": [{"when": {"extension": ["tsx"]}, "prefer": ["a"]}]}
        cat = [{"type": "tool", "name": "a", "description": "alpha"}]
        result = routing.plan_route(cat, "alpha", {}, rout, None)
        self.assertEqual(result["chosen"]["name"], "a")
        self.assertNotIn("rule prefer (+2)", result["chosen"]["reasons"])

    def test_rule_with_nonmatching_extension_returns_false(self):
        rule = {"when": {"extension": ["tsx"]}}
        self.assertFalse(routing._rule_matches(rule, {"extension": "py"}))


class MigrateBranchTests(unittest.TestCase):
    def test_disabled_plugin_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = build_fake_claude_home(pathlib.Path(tmp) / "h")
            # Disable beta so plan_migration hits the `not enabled -> continue` skip.
            settings = home / ".claude" / "settings.json"
            data = json.loads(settings.read_text())
            data["enabledPlugins"]["beta@other-market"] = False
            settings.write_text(json.dumps(data))
            env = ClaudeEnv(home)
            reg = registry.Registry(path=pathlib.Path(tmp) / "cfg" / "config.json")
            plan = migrate.plan_migration(env, reg, {"mcp": [], "plugins": "all",
                                                     "personal_skills": []})
            self.assertNotIn("beta@other-market", plan.disable_plugins)

    def test_rollback_reraises_when_not_best_effort(self):
        class BoomEnv:
            def enable_plugin(self, key, prev):
                raise RuntimeError("boom")

        actions = [{"type": "disable_plugin", "key": "k", "prev": True}]
        with self.assertRaises(RuntimeError):
            migrate._rollback(BoomEnv(), actions, best_effort=False)

    def test_rollback_swallows_when_best_effort(self):
        class BoomEnv:
            def enable_plugin(self, key, prev):
                raise RuntimeError("boom")

        actions = [{"type": "disable_plugin", "key": "k", "prev": True}]
        migrate._rollback(BoomEnv(), actions, best_effort=True)  # no raise


class RegistryEdgeTests(unittest.TestCase):
    def test_remove_unknown_kind_raises(self):
        reg = registry.Registry()
        with self.assertRaises(ValueError):
            registry.remove(reg, "widget", "x")


class ClaudeEnvEdgeTests(unittest.TestCase):
    def test_discover_plugin_skills_empty_when_cache_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = ClaudeEnv(pathlib.Path(tmp))  # no plugins cache exists
            self.assertEqual(env.discover_plugin_skills(), [])


class CliEdgeTests(unittest.TestCase):
    def _env(self, tmp):
        cfg = pathlib.Path(tmp) / "cfg" / "config.json"
        return {"WARDEN_CONFIG": str(cfg), "WARDEN_HOME": str(pathlib.Path(tmp) / "cfg")}

    def test_serve_runs_mcp(self):
        from warden.cli import run
        import warden.server as server
        with mock.patch.object(server.mcp, "run", lambda: None):
            self.assertEqual(run(["serve"]), 0)

    def test_add_mcp_with_env_pair(self):
        from warden.cli import run
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            rc = run(["add-mcp", "gh", "--command", "npx", "--env", "TOKEN=abc"], env=env)
            self.assertEqual(rc, 0)
            stored = json.loads((pathlib.Path(tmp) / "cfg" / "config.json").read_text())
            self.assertEqual(stored["mcp_servers"]["gh"]["env"], {"TOKEN": "abc"})

    def test_add_skill(self):
        from warden.cli import run
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = run(["add-skill", "/some/skills"], env=env)
            self.assertEqual(rc, 0)
            self.assertIn("registered skill dir", out.getvalue())

    def test_main_dispatches_and_exits(self):
        from warden import cli
        with tempfile.TemporaryDirectory() as tmp:
            envmap = {"WARDEN_CONFIG": str(pathlib.Path(tmp) / "config.json"),
                      "WARDEN_HOME": str(tmp)}
            with mock.patch.dict(os.environ, envmap), \
                    mock.patch.object(sys, "argv", ["warden", "list"]):
                out = io.StringIO()
                with redirect_stdout(out):
                    with self.assertRaises(SystemExit) as ctx:
                        cli.main()
                self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
