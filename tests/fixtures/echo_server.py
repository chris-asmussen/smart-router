"""A trivial downstream MCP server used by the integration test."""
from mcp.server import MCPServer

mcp = MCPServer("echo")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the provided text straight back to the caller."""
    return text


if __name__ == "__main__":
    mcp.run()
