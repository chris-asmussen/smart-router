"""smart-router MCP server.

Exposes exactly 3 tools to the calling agent — search, call_tool, use_skill —
regardless of how many downstream MCP servers or Skills are configured. The
full catalog is built once at startup (in the server lifespan) and kept
server-side; nothing else enters the model's context window until `search`
surfaces it.
"""
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer

from . import __version__
from . import migrate as _M
from . import registry as _R
from .catalog import build_tool_catalog, load_skills
from .claude_env import ClaudeEnv as _ClaudeEnv
from .downstream import call_downstream_tool
from .search import search_catalog

# Populated by `lifespan` at server startup, before any tool call is served.
# Building the catalog here (rather than at import time) keeps `import
# smart_router.server` side-effect free — importing the module no longer spawns
# every configured downstream subprocess — and runs the async catalog build on
# the server's own event loop.
CONFIG: dict[str, Any] = {}
SKILLS: list[dict[str, Any]] = []
CATALOG: list[dict[str, Any]] = []


@asynccontextmanager
async def lifespan(_server: MCPServer):
    global CONFIG, SKILLS, CATALOG
    # Build from the durable registry, not load_config: the server must start even
    # with no config file so an agent can bootstrap it via the `admin` tool. A
    # missing registry file yields an empty registry (no raise); malformed JSON
    # still raises via json.loads inside load_registry.
    reg = _R.load_registry()
    CONFIG = {"mcp_servers": reg.mcp_servers, "skill_dirs": reg.skill_dirs}
    if not reg.mcp_servers and not reg.skill_dirs:
        print("smart-router: registry is empty; use the `admin` tool or `smart-router "
              "migrate` to add downstream servers/skills.", file=sys.stderr)
    tools = await build_tool_catalog(CONFIG["mcp_servers"])
    SKILLS = load_skills(CONFIG["skill_dirs"])
    CATALOG = tools + SKILLS
    yield


mcp = MCPServer(
    "smart-router",
    version=__version__,
    lifespan=lifespan,
    instructions="Call `search` before assuming a tool or skill is unavailable; "
                 "downstream capabilities are hidden until searched. Use `admin` to "
                 "register or migrate them.",
)


@mcp.tool()
def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search available MCP tools and Skills by name, description, or regex.

    Returns up to `limit` matching entries (each with a "type" of "tool" or
    "skill"). Use `call_tool` on a "tool" match or `use_skill` on a "skill"
    match to actually invoke it.
    """
    return search_catalog(CATALOG, query, limit)


@mcp.tool()
async def call_tool(server: str, name: str, arguments: dict[str, Any] | None = None) -> Any:
    """Invoke a downstream MCP tool found via `search`.

    `server` and `name` come from a search result of type "tool".
    """
    if server not in CONFIG["mcp_servers"]:
        raise ValueError(f"Unknown server: {server}")
    return await call_downstream_tool(CONFIG["mcp_servers"][server], name, arguments or {})


@mcp.tool()
def use_skill(name: str) -> str:
    """Load the full instructions for a Skill found via `search`."""
    for skill in SKILLS:
        if skill["name"] == name:
            return skill["content"]
    raise ValueError(f"Unknown skill: {name}")


async def _rebuild_catalog() -> None:
    """Rebuild the live CATALOG/SKILLS from CONFIG so `search` reflects registry
    mutations without a server restart."""
    global CATALOG, SKILLS
    tools = await build_tool_catalog(CONFIG["mcp_servers"])
    SKILLS = load_skills(CONFIG["skill_dirs"])
    CATALOG = tools + SKILLS


def _sync_config_from(reg) -> None:
    # Mutate (not rebind) the lifespan-bound CONFIG dict so call_tool/search see it.
    CONFIG["mcp_servers"] = reg.mcp_servers
    CONFIG["skill_dirs"] = reg.skill_dirs


@mcp.tool()
async def admin(action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Manage the smart-router registry. Actions: list, register_mcp, register_skill,
    unregister, migrate, restore. `params` carries the action's arguments."""
    params = params or {}
    reg = _R.load_registry()
    if action == "list":
        return _R.summary(reg)
    if action == "register_mcp":
        _R.add_mcp_server(reg, params["name"], params["command"], params.get("args"), params.get("env"))
        _R.save_registry(reg); _sync_config_from(reg); await _rebuild_catalog()
        return {"registered": params["name"]}
    if action == "register_skill":
        _R.add_skill_dir(reg, params["path"])
        _R.save_registry(reg); _sync_config_from(reg); await _rebuild_catalog()
        return {"registered": params["path"]}
    if action == "unregister":
        _R.remove(reg, params["kind"], params["name"])
        _R.save_registry(reg); _sync_config_from(reg); await _rebuild_catalog()
        return {"unregistered": params["name"]}
    if action == "migrate":
        cenv = _ClaudeEnv()
        plan = _M.plan_migration(cenv, reg, params.get(
            "targets", {"mcp": [], "plugins": [], "personal_skills": []}))
        if not params.get("apply"):
            return {"dry_run": _M.render_plan(plan)}
        # server.py is an entry point; the determinism constraint applies to
        # registry/migrate internals, not here, so generate run_id/timestamp locally.
        import datetime
        import uuid
        run_id = uuid.uuid4().hex[:8]
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        man = _M.apply_migration(cenv, reg, plan, run_id, timestamp)
        _sync_config_from(reg); await _rebuild_catalog()
        return {"migrated": man["id"], "note": "Restart Claude Code to apply Claude-side changes."}
    if action == "restore":
        ok = _M.restore(_ClaudeEnv(), reg, params["id"])
        _sync_config_from(reg); await _rebuild_catalog()
        return {"restored": ok}
    raise ValueError(f"unknown admin action: {action}")


if __name__ == "__main__":
    mcp.run()
