"""Dependency-free tests for config loading (no `mcp` required).

Run: python3 -m unittest tests.test_config
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from smart_router.config import load_config
from smart_router.config import config_home, resolve_config_path, writable_config_path


class ResolutionTests(unittest.TestCase):
    def test_config_home_uses_env_override(self):
        self.assertEqual(config_home(env={"SMART_ROUTER_HOME": "/x/y"}), pathlib.Path("/x/y"))

    def test_config_home_defaults_to_xdg(self):
        self.assertEqual(config_home(env={}), pathlib.Path("~/.config/smart-router").expanduser())

    def test_resolve_prefers_explicit_then_env(self):
        self.assertEqual(resolve_config_path("/a.json", env={"SMART_ROUTER_CONFIG": "/b.json"}), pathlib.Path("/a.json"))
        self.assertEqual(resolve_config_path(None, env={"SMART_ROUTER_CONFIG": "/b.json"}), pathlib.Path("/b.json"))

    def test_resolve_read_falls_back_to_cwd_default(self):
        self.assertEqual(resolve_config_path(None, env={}), pathlib.Path("smart-router.config.json"))

    def test_writable_never_falls_back_to_cwd(self):
        # writes always go to config_home, never CWD, so the registry persists across sessions
        self.assertEqual(writable_config_path(None, env={"SMART_ROUTER_HOME": "/x"}), pathlib.Path("/x/config.json"))
        self.assertEqual(writable_config_path(None, env={}), pathlib.Path("~/.config/smart-router/config.json").expanduser())


class LoadConfigTests(unittest.TestCase):
    def test_missing_config_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = pathlib.Path(tmp) / "nope.json"
            with self.assertRaises(FileNotFoundError):
                load_config(missing)

    def test_explicit_path_is_loaded_and_defaults_filled(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "smart-router.config.json"
            cfg.write_text(json.dumps({"mcp_servers": {"gh": {"command": "true"}}}))
            data = load_config(cfg)
            self.assertIn("gh", data["mcp_servers"])
            self.assertEqual(data["skill_dirs"], [])  # default filled

    def test_env_var_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "elsewhere.json"
            cfg.write_text(json.dumps({"skill_dirs": ["./s"]}))
            old = os.environ.get("SMART_ROUTER_CONFIG")
            os.environ["SMART_ROUTER_CONFIG"] = str(cfg)
            try:
                data = load_config()
            finally:
                if old is None:
                    del os.environ["SMART_ROUTER_CONFIG"]
                else:
                    os.environ["SMART_ROUTER_CONFIG"] = old
            self.assertEqual(data["skill_dirs"], ["./s"])
            self.assertEqual(data["mcp_servers"], {})  # default filled

    def test_non_object_config_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "smart-router.config.json"
            cfg.write_text("[1, 2, 3]")
            with self.assertRaises(ValueError):
                load_config(cfg)


if __name__ == "__main__":
    unittest.main()
