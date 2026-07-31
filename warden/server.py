"""warden MCP server.

Exposes a small, fixed set of tools to the calling agent — search, call_tool,
use_skill, admin, route — regardless of how many downstream MCP servers or
Skills are configured. The full catalog is built once at startup (in the server
lifespan) and kept server-side; nothing else enters the model's context window
until `search` surfaces it.
"""
import sys
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer

from . import __version__
from . import autostart as _autostart
from . import migrate as _M
from . import registry as _R
from . import routing as _routing
from .catalog import build_tool_catalog, load_skills
from .claude_env import ClaudeEnv as _ClaudeEnv
from .downstream import call_downstream_tool
from .search import search_catalog

# Populated by `lifespan` at server startup, before any tool call is served.
# Building the catalog here (rather than at import time) keeps `import
# warden.server` side-effect free — importing the module no longer spawns
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
        print("warden: registry is empty; use the `admin` tool or `warden "
              "migrate` to add downstream servers/skills.", file=sys.stderr)
    tools = await build_tool_catalog(CONFIG["mcp_servers"])
    SKILLS = load_skills(CONFIG["skill_dirs"])
    CATALOG = tools + SKILLS
    yield


BASE_INSTRUCTIONS = (
    "Call `search` before assuming a tool or skill is unavailable; "
    "downstream capabilities are hidden until searched. Use `admin` to "
    "register or migrate them. Use `route` to pick the best tool or skill "
    "for a described task; you may pass a light file `context` "
    "(e.g. {\"file_path\": \"src/App.tsx\"} or {\"extension\": \"tsx\"}) — "
    "references only, never file contents. `route` returns the pick and "
    "never executes it."
)


def _startup_instructions() -> str:
    """Assemble the server instructions, folding in any auto_start Skills.

    Built at import time, not in the lifespan, so the full string is ready when
    the client reads it at `initialize`. A change to the auto_start set therefore
    needs a server restart; this matches the MCP protocol, which sends the
    instructions one time at startup. Reads only local SKILL.md files (no
    subprocess), and it never lets a bad registry break the import.
    """
    try:
        reg = _R.load_registry()
        skills = load_skills(reg.skill_dirs)
        chosen, missing = _autostart.collect_auto_start(skills, reg.auto_start)
        for name in missing:
            print(f"warden: auto_start skill '{name}' is not in any registered "
                  "skill dir; skipped.", file=sys.stderr)
        text, warnings = _autostart.build_instructions(BASE_INSTRUCTIONS, chosen)
        for warning in warnings:
            print(f"warden: {warning}", file=sys.stderr)
        return text
    except Exception as exc:  # a bad registry must not stop the server from starting
        print(f"warden: could not build auto_start instructions ({exc}); "
              "using base instructions.", file=sys.stderr)
        return BASE_INSTRUCTIONS


mcp = MCPServer(
    "warden",
    version=__version__,
    lifespan=lifespan,
    instructions=BASE_INSTRUCTIONS,
)


def apply_startup_instructions() -> None:
    """Fold any auto_start Skills into the live server instructions.

    Called by the serve entry points just before `mcp.run()`, never at import,
    so `import warden.server` stays free of any registry read (hermetic tests,
    no import side effect). It must NOT move into the lifespan: the stdio
    transport builds the initialize options (create_initialization_options,
    which reads `instructions`) as an argument to `run()`, and `run()` enters the
    lifespan only after that snapshot. Setting it here, before `mcp.run()`, is
    read at run time and reaches the client.
    """
    mcp._lowlevel_server.instructions = _startup_instructions()


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


@mcp.tool()
def route(task: str, context: dict[str, Any] | None = None,
          mode: str | None = None) -> dict[str, Any]:
    """Pick the best tool or skill for `task`, ranked by server-side routing config.

    Returns the selection (`chosen` / `candidates`) and NEVER executes anything —
    invoke the pick yourself via `call_tool` or `use_skill`. `context` is optional
    light file metadata (`file_path` / `extension`, references only); `mode`
    overrides the configured auto/ask default for this call.
    """
    reg = _R.load_registry()
    routing = _routing.load_routing(reg)
    return _routing.plan_route(CATALOG, task, context, routing, mode)


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
    """Manage the warden registry. Actions: list, register_mcp, register_skill,
    unregister, migrate, restore, get_routing, set_routing, set_auto_start.
    `params` carries the action's arguments."""
    params = params or {}
    reg = _R.load_registry()
    if action == "list":
        return _R.summary(reg)
    if action == "get_routing":
        return _routing.load_routing(reg)
    if action == "set_routing":
        # Merge the provided keys onto the current block so partial updates work;
        # save_routing validates + persists. No catalog rebuild: routing config
        # does not change the tool/skill catalog itself.
        block = _routing.load_routing(reg)
        for key in ("mode", "priority_order", "exclude", "rules"):
            if key in params:
                block[key] = params[key]
        _routing.save_routing(reg, block)
        return _routing.load_routing(reg)
    if action == "register_mcp":
        _R.add_mcp_server(reg, params["name"], params["command"], params.get("args"), params.get("env"))
        _R.save_registry(reg); _sync_config_from(reg); await _rebuild_catalog()
        return {"registered": params["name"]}
    if action == "register_skill":
        _R.add_skill_dir(reg, params["path"])
        _R.save_registry(reg); _sync_config_from(reg); await _rebuild_catalog()
        return {"registered": params["path"]}
    if action == "set_auto_start":
        # auto_start changes the server `instructions`, which the client reads
        # once at startup, not the live catalog. So save it, but do not rebuild
        # the catalog, and tell the caller a restart is needed to load it.
        name = params["name"]
        enabled = params.get("enabled", True)
        changed = _R.set_auto_start(reg, name, enabled)
        _R.save_registry(reg)
        return {"auto_start": list(reg.auto_start), "changed": changed,
                "note": "Restart the MCP client so it reloads warden's instructions."}
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
    apply_startup_instructions()
    mcp.run()
