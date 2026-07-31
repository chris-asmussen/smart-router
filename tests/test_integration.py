"""End-to-end integration test: drive smart-router over real stdio MCP.

Launches the smart-router server as a subprocess with a config pointing at a
fixture downstream server (tests/fixtures/echo_server.py) and a fixture skill,
then exercises all three exposed tools through an MCP client.

Requires the `mcp` package (and therefore skips when it is not installed);
`tests.test_search` / `tests.test_config` cover the pure logic without it.

Run: python3 -m unittest tests.test_integration
"""
import asyncio
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

try:
    import mcp  # noqa: F401

    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


@unittest.skipUnless(HAVE_MCP, "requires the `mcp` package")
class SmartRouterIntegrationTests(unittest.TestCase):
    def test_end_to_end(self):
        asyncio.run(self._run())

    async def _run(self):
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as tmp:
            config_path = pathlib.Path(tmp) / "smart-router.config.json"
            config_path.write_text(json.dumps({
                "mcp_servers": {
                    "echo": {
                        "command": sys.executable,
                        "args": [str(FIXTURES / "echo_server.py")],
                        "env": {},
                    }
                },
                "skill_dirs": [str(FIXTURES / "skills")],
            }))

            # Full env + overrides so the subprocess can import smart_router and
            # locate the config via SMART_ROUTER_CONFIG (CWD-independent).
            env = dict(os.environ)
            env["SMART_ROUTER_CONFIG"] = str(config_path)
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "smart_router"],
                env=env,
                cwd=tmp,  # deliberately not the repo root
            )

            async with Client(stdio_client(params)) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    sorted(t.name for t in tools.tools),
                    ["admin", "call_tool", "route", "search", "use_skill"],
                )

                # search surfaces the downstream tool
                hits = (await client.call_tool("search", {"query": "echo"})).structured_content["result"]
                self.assertTrue(any(h["type"] == "tool" and h["name"] == "echo" for h in hits))

                # search surfaces the skill
                hits = (await client.call_tool("search", {"query": "greet"})).structured_content["result"]
                self.assertTrue(any(h["type"] == "skill" and h["name"] == "greeter" for h in hits))

                # call_tool proxies a real downstream invocation (Any return ->
                # payload arrives as JSON text content, not structured output)
                res = await client.call_tool(
                    "call_tool",
                    {"server": "echo", "name": "echo", "arguments": {"text": "round-trip"}},
                )
                payload = json.loads(res.content[0].text)
                self.assertEqual(payload, {"result": "round-trip"})

                # use_skill returns the full SKILL.md body
                skill = (await client.call_tool("use_skill", {"name": "greeter"})).structured_content["result"]
                self.assertIn("Say hello", skill)

    def test_route_ranks_and_never_executes(self):
        asyncio.run(self._route())

    async def _route(self):
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "config.json"
            cfg.write_text(json.dumps({
                "mcp_servers": {"echo": {
                    "command": sys.executable,
                    "args": [str(FIXTURES / "echo_server.py")],
                    "env": {},
                }},
                "skill_dirs": [str(FIXTURES / "skills")],
                "routing": {"mode": "auto", "priority_order": [],
                            "exclude": [], "rules": []},
            }))
            env = dict(os.environ)
            env["SMART_ROUTER_CONFIG"] = str(cfg)
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "smart_router"], env=env, cwd=tmp)

            async with Client(stdio_client(params)) as client:
                tools = await client.list_tools()
                self.assertIn("route", [t.name for t in tools.tools])

                # Single-option: only the echo tool matches "echo".
                res = (await client.call_tool("route", {"task": "echo"})).structured_content
                self.assertTrue(res["single_option"])
                self.assertEqual(res["chosen"]["name"], "echo")
                self.assertEqual(len(res["candidates"]), 1)

                # Ranking: both tool and skill match "greet echo"; both survive
                # and auto mode names a chosen pick reflecting the ranking.
                res = (await client.call_tool("route", {"task": "greet echo"})).structured_content
                names = [c["name"] for c in res["candidates"]]
                self.assertIn("echo", names)
                self.assertIn("greeter", names)
                self.assertFalse(res["single_option"])
                self.assertEqual(res["chosen"]["name"], res["candidates"][0]["name"])

    def test_admin_register_mcp_is_live(self):
        asyncio.run(self._admin())

    async def _admin(self):
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "config.json"
            cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
            env = dict(os.environ)
            env["SMART_ROUTER_CONFIG"] = str(cfg)
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "smart_router"],
                env=env,
                cwd=tmp,
            )
            async with Client(stdio_client(params)) as client:
                await client.call_tool("admin", {"action": "register_mcp", "params": {
                    "name": "echo", "command": sys.executable,
                    "args": [str(FIXTURES / "echo_server.py")]}})
                hits = (await client.call_tool("search", {"query": "echo"})).structured_content["result"]
                self.assertTrue(any(h["name"] == "echo" for h in hits))
                listing = (await client.call_tool("admin", {"action": "list"})).structured_content
                self.assertIn("echo", listing["mcp_servers"])


    def test_admin_routing_roundtrips(self):
        asyncio.run(self._admin_routing())

    async def _admin_routing(self):
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / "config.json"
            cfg.write_text(json.dumps({"mcp_servers": {}, "skill_dirs": []}))
            env = dict(os.environ)
            env["SMART_ROUTER_CONFIG"] = str(cfg)
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "smart_router"], env=env, cwd=tmp)

            async with Client(stdio_client(params)) as client:
                block = {
                    "mode": "ask",
                    "priority_order": ["gh.create_issue"],
                    "exclude": ["weather.get"],
                    "rules": [{"when": {"extension": ["tsx"]}, "prefer": ["gh.create_issue"]}],
                }
                await client.call_tool("admin", {"action": "set_routing", "params": block})
                got = (await client.call_tool("admin", {"action": "get_routing"})).structured_content
                self.assertEqual(got["mode"], "ask")
                self.assertEqual(got["priority_order"], ["gh.create_issue"])
                self.assertEqual(got["exclude"], ["weather.get"])
                self.assertEqual(got["rules"][0]["when"]["extension"], ["tsx"])


if __name__ == "__main__":
    unittest.main()
