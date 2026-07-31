"""Builds the searchable catalog: downstream MCP tools + local Skills.

Downstream MCP servers are queried once at startup (list_tools) so their
definitions exist server-side for search, without ever being placed in the
calling agent's context window.
"""
import pathlib
import sys
from typing import Any


def _server_params(conf: dict[str, Any]):
    from mcp import StdioServerParameters
    return StdioServerParameters(
        command=conf["command"],
        args=conf.get("args", []),
        env=conf.get("env"),
    )


async def build_tool_catalog(mcp_servers: dict[str, Any]) -> list[dict[str, Any]]:
    # Imported lazily so pure catalog/skill parsing (and its tests) don't
    # require the `mcp` package to be installed.
    from mcp import Client
    from mcp.client.stdio import stdio_client

    entries: list[dict[str, Any]] = []
    for server_name, conf in mcp_servers.items():
        try:
            async with Client(stdio_client(_server_params(conf))) as client:
                result = await client.list_tools()
                for tool in result.tools:
                    entries.append({
                        "type": "tool",
                        "server": server_name,
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.input_schema,
                    })
        except Exception as exc:  # one unreachable downstream server shouldn't kill the router
            print(f"warden: failed to catalog '{server_name}': {exc}", file=sys.stderr)
    return entries


def _parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    meta: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip('"')
    return meta


def load_skills(skill_dirs: list[str]) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for skill_dir in skill_dirs:
        for path in pathlib.Path(skill_dir).glob("**/SKILL.md"):
            text = path.read_text(encoding="utf-8")
            meta = _parse_frontmatter(text)
            skills.append({
                "type": "skill",
                "name": meta.get("name", path.parent.name),
                "description": meta.get("description", ""),
                "path": str(path),
                "content": text,
            })
    return skills
