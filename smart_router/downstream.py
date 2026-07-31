"""Proxies a single tool call to the downstream MCP server that owns it.

ponytail: opens a fresh stdio connection per call instead of pooling
persistent connections. Simpler and correct; add connection pooling only if
per-call subprocess-startup latency actually becomes a measured problem.
"""
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client


async def call_downstream_tool(conf: dict[str, Any], name: str, arguments: dict[str, Any]) -> Any:
    params = StdioServerParameters(
        command=conf["command"],
        args=conf.get("args", []),
        env=conf.get("env"),
    )
    async with Client(stdio_client(params)) as client:
        result = await client.call_tool(name, arguments)
        if result.structured_content is not None:
            return result.structured_content
        return str(result)
