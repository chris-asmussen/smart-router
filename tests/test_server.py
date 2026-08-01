"""In-process coverage for warden.server, warden.downstream, and the async
downstream path of warden.catalog.

The integration test drives these modules only through a subprocess, so the
parent coverage run never sees them. Here we import warden.server directly and
call its @mcp.tool()-decorated functions (the decorator returns the original
callable) plus drive the `lifespan` context manager, all against the fixture
echo server. Hermetic: WARDEN_CONFIG / WARDEN_HOME point at a fresh temp dir per
test, and the migrate/restore admin paths patch ClaudeEnv onto a fake home so
the real ~/.claude is never touched.
"""
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

from tests.fixtures.fake_claude_home import build_fake_claude_home

try:
    import mcp  # noqa: F401

    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


def _echo_conf():
    return {"command": sys.executable, "args": [str(FIXTURES / "echo_server.py")], "env": {}}


@unittest.skipUnless(HAVE_MCP, "requires the `mcp` package")
class ServerToolTests(unittest.TestCase):
    def setUp(self):
        import warden.server as server

        self.server = server
        # Fresh, isolated home + config for every test so no admin write can
        # ever land on a real ~/.config/warden.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pathlib.Path(self.tmp.name)
        self.cfg = self.home / "config.json"
        patcher = mock.patch.dict(os.environ, {
            "WARDEN_CONFIG": str(self.cfg),
            "WARDEN_HOME": str(self.home),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

        # server.py keeps CONFIG/SKILLS/CATALOG as module globals; snapshot and
        # restore their CONTENTS (CONFIG is mutated in place by _sync_config_from,
        # so rebinding the name is not enough).
        self._config_snapshot = dict(server.CONFIG)
        self._skills_snapshot = list(server.SKILLS)
        self._catalog_snapshot = list(server.CATALOG)
        # apply_startup_instructions() mutates the live server instructions;
        # snapshot so one test's auto_start does not bleed into later assertions.
        self._instructions_snapshot = server.mcp._lowlevel_server.instructions

        def _restore():
            server.CONFIG.clear()
            server.CONFIG.update(self._config_snapshot)
            server.SKILLS[:] = self._skills_snapshot
            server.CATALOG[:] = self._catalog_snapshot
            server.mcp._lowlevel_server.instructions = self._instructions_snapshot

        self.addCleanup(_restore)

    # -- lifespan ---------------------------------------------------------- #
    def test_lifespan_empty_registry_warns_and_builds_empty_catalog(self):
        server = self.server

        async def run():
            async with server.lifespan(server.mcp):
                self.assertEqual(server.CATALOG, [])
                self.assertEqual(server.CONFIG["mcp_servers"], {})

        asyncio.run(run())

    def test_lifespan_populated_registry_builds_catalog(self):
        server = self.server
        self.cfg.write_text(json.dumps({
            "mcp_servers": {"echo": _echo_conf()},
            "skill_dirs": [str(FIXTURES / "skills")],
        }))

        async def run():
            async with server.lifespan(server.mcp):
                names = {e["name"] for e in server.CATALOG}
                self.assertIn("echo", names)
                self.assertIn("greeter", names)

        asyncio.run(run())

    # -- search ------------------------------------------------------------ #
    def test_search_returns_catalog_hits(self):
        server = self.server
        server.CATALOG[:] = [{"type": "tool", "server": "echo", "name": "echo",
                              "description": "echo the text back"}]
        hits = server.search("echo")
        self.assertTrue(any(h["name"] == "echo" for h in hits))

    # -- use_skill --------------------------------------------------------- #
    def test_use_skill_found_and_missing(self):
        server = self.server
        server.SKILLS[:] = [{"type": "skill", "name": "greeter", "content": "Say hello"}]
        self.assertEqual(server.use_skill("greeter"), "Say hello")
        with self.assertRaises(ValueError):
            server.use_skill("nope")

    # -- call_tool --------------------------------------------------------- #
    def test_call_tool_unknown_server_raises(self):
        server = self.server
        server.CONFIG["mcp_servers"] = {}
        with self.assertRaises(ValueError):
            asyncio.run(server.call_tool("ghost", "echo", {"text": "x"}))

    def test_call_tool_proxies_real_downstream(self):
        server = self.server
        server.CONFIG["mcp_servers"] = {"echo": _echo_conf()}
        result = asyncio.run(server.call_tool("echo", "echo", {"text": "round-trip"}))
        self.assertEqual(result, {"result": "round-trip"})

    # -- route ------------------------------------------------------------- #
    def test_route_single_option_and_auto(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": [],
                                        "routing": {"mode": "auto"}}))
        server.CATALOG[:] = [
            {"type": "tool", "server": "echo", "name": "echo", "description": "echo text"},
            {"type": "skill", "name": "greeter", "description": "greet a user warmly"},
        ]
        single = server.route("echo")
        self.assertTrue(single["single_option"])
        self.assertEqual(single["chosen"]["name"], "echo")

        auto = server.route("greet echo")
        self.assertFalse(auto["single_option"])
        self.assertEqual(auto["chosen"]["name"], auto["candidates"][0]["name"])

    # -- admin: read + routing --------------------------------------------- #
    def test_admin_list_and_routing_roundtrip(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
        listing = asyncio.run(server.admin("list"))
        self.assertEqual(listing["mcp_servers"], [])

        block = {"mode": "ask", "priority_order": ["gh.x"], "exclude": ["w.y"], "rules": []}
        got = asyncio.run(server.admin("set_routing", block))
        self.assertEqual(got["mode"], "ask")
        got2 = asyncio.run(server.admin("get_routing"))
        self.assertEqual(got2["priority_order"], ["gh.x"])

    # -- admin: set_auto_start (persists, restart-gated, no live rebuild) --- #
    def test_admin_set_auto_start_persists_and_notes_restart(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
        got = asyncio.run(server.admin("set_auto_start", {"name": "ponytail"}))
        self.assertEqual(got["auto_start"], ["ponytail"])
        self.assertTrue(got["changed"])
        self.assertIn("Restart", got["note"])
        # Persisted to the temp config, and reversible.
        self.assertEqual(json.loads(self.cfg.read_text())["auto_start"], ["ponytail"])
        off = asyncio.run(server.admin("set_auto_start", {"name": "ponytail", "enabled": False}))
        self.assertEqual(off["auto_start"], [])

    # -- _startup_instructions folds auto_start skill text into instructions - #
    def test_startup_instructions_include_auto_start_skill(self):
        server = self.server
        self.cfg.write_text(json.dumps({
            "mcp_servers": {}, "skill_dirs": [str(FIXTURES / "skills")],
            "auto_start": ["greeter"]}))
        text = server._startup_instructions()
        self.assertTrue(text.startswith(server.BASE_INSTRUCTIONS))
        self.assertIn("--- Skill: greeter ---", text)

    def test_startup_instructions_base_only_when_no_auto_start(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
        self.assertEqual(server._startup_instructions(), server.BASE_INSTRUCTIONS)

    def test_apply_startup_instructions_updates_live_getter(self):
        # The check that matters: the object the client reads (mcp.instructions),
        # not just the builder, holds the folded auto_start text after apply.
        server = self.server
        self.cfg.write_text(json.dumps({
            "mcp_servers": {}, "skill_dirs": [str(FIXTURES / "skills")],
            "auto_start": ["greeter"]}))
        server.apply_startup_instructions()
        self.assertIn("--- Skill: greeter ---", server.mcp.instructions)

    def test_startup_instructions_warns_on_missing_auto_start_name(self):
        server = self.server
        self.cfg.write_text(json.dumps({
            "mcp_servers": {}, "skill_dirs": [str(FIXTURES / "skills")],
            "auto_start": ["ghost"]}))  # no such skill
        self.assertEqual(server._startup_instructions(), server.BASE_INSTRUCTIONS)

    def test_startup_instructions_survives_bad_registry(self):
        server = self.server
        self.cfg.write_text("{ not valid json")
        # A malformed registry must not stop the server from starting.
        self.assertEqual(server._startup_instructions(), server.BASE_INSTRUCTIONS)

    def test_admin_unknown_action_raises(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
        with self.assertRaises(ValueError):
            asyncio.run(server.admin("frobnicate"))

    # -- admin: register / unregister (rebuilds live catalog) -------------- #
    def test_admin_register_mcp_skill_and_unregister_are_live(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))

        reg = asyncio.run(server.admin("register_mcp", {
            "name": "echo", "command": sys.executable,
            "args": [str(FIXTURES / "echo_server.py")]}))
        self.assertEqual(reg["registered"], "echo")
        # The live catalog reflects the registration without a restart.
        self.assertTrue(any(e["name"] == "echo" for e in server.CATALOG))

        regsk = asyncio.run(server.admin("register_skill", {"path": str(FIXTURES / "skills")}))
        self.assertEqual(regsk["registered"], str(FIXTURES / "skills"))
        self.assertTrue(any(e["name"] == "greeter" for e in server.CATALOG))

        unreg = asyncio.run(server.admin("unregister", {"kind": "mcp", "name": "echo"}))
        self.assertEqual(unreg["unregistered"], "echo")
        self.assertFalse(any(e.get("server") == "echo" for e in server.CATALOG))

        # Isolation proof: everything persisted to the temp config, never ~/.
        self.assertTrue(self.cfg.exists())
        on_disk = json.loads(self.cfg.read_text())
        self.assertNotIn("echo", on_disk["mcp_servers"])
        self.assertIn(str(FIXTURES / "skills"), on_disk["skill_dirs"])

    # -- admin: migrate dry-run / apply + restore (patched fake home) ------ #
    def test_admin_migrate_dry_run(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
        fake = build_fake_claude_home(self.home / "claude")
        from warden.claude_env import ClaudeEnv
        with mock.patch.object(server, "_ClaudeEnv", lambda: ClaudeEnv(fake)):
            out = asyncio.run(server.admin("migrate", {"targets": {
                "mcp": [], "plugins": [], "personal_skills": []}}))
        self.assertIn("dry_run", out)

    def test_admin_migrate_apply_then_restore(self):
        server = self.server
        self.cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
        fake = build_fake_claude_home(self.home / "claude")
        from warden.claude_env import ClaudeEnv
        with mock.patch.object(server, "_ClaudeEnv", lambda: ClaudeEnv(fake)):
            applied = asyncio.run(server.admin("migrate", {"apply": True, "targets": {
                "mcp": "all", "plugins": [], "personal_skills": []}}))
            self.assertIn("migrated", applied)
            restored = asyncio.run(server.admin("restore", {"id": applied["migrated"]}))
            self.assertTrue(restored["restored"])


@unittest.skipUnless(HAVE_MCP, "requires the `mcp` package")
class DownstreamTests(unittest.TestCase):
    def test_call_downstream_tool_roundtrips(self):
        from warden.downstream import call_downstream_tool
        result = asyncio.run(call_downstream_tool(_echo_conf(), "echo", {"text": "hola"}))
        self.assertEqual(result, {"result": "hola"})


@unittest.skipUnless(HAVE_MCP, "requires the `mcp` package")
class CatalogBuildTests(unittest.TestCase):
    def test_build_tool_catalog_connects_downstream(self):
        from warden.catalog import build_tool_catalog
        entries = asyncio.run(build_tool_catalog({"echo": _echo_conf()}))
        self.assertEqual([e["name"] for e in entries], ["echo"])
        self.assertEqual(entries[0]["type"], "tool")
        self.assertEqual(entries[0]["server"], "echo")

    def test_build_tool_catalog_swallows_unreachable_server(self):
        from warden.catalog import build_tool_catalog
        entries = asyncio.run(build_tool_catalog(
            {"bad": {"command": "/nonexistent_warden_xyz", "args": [], "env": {}}}))
        self.assertEqual(entries, [])


if __name__ == "__main__":
    unittest.main()
