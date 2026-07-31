"""Durable warden registry (mcp_servers + skill_dirs + migrations)."""
import json, pathlib
from dataclasses import dataclass, field
from typing import Any
from .config import writable_config_path

@dataclass
class Registry:
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    skill_dirs: list[str] = field(default_factory=list)
    migrations: list[dict] = field(default_factory=list)
    path: pathlib.Path = field(default_factory=lambda: writable_config_path())
    routing: dict = field(default_factory=dict)
    # Names of Skills that load at every session start (opt-in), instead of only
    # on demand through `search`. See warden/autostart.py.
    auto_start: list[str] = field(default_factory=list)

def load_registry(path=None) -> Registry:
    p = writable_config_path() if path is None else pathlib.Path(path)
    if not p.exists():
        return Registry(path=p)
    d = json.loads(p.read_text(encoding="utf-8"))
    return Registry(d.get("mcp_servers", {}), d.get("skill_dirs", []),
                    d.get("migrations", []), p, d.get("routing", {}),
                    d.get("auto_start", []))

def save_registry(reg: Registry) -> None:
    reg.path.parent.mkdir(parents=True, exist_ok=True)
    reg.path.write_text(json.dumps(
        {"mcp_servers": reg.mcp_servers, "skill_dirs": reg.skill_dirs,
         "migrations": reg.migrations, "routing": reg.routing,
         "auto_start": reg.auto_start},
        indent=2), encoding="utf-8")

def add_mcp_server(reg, name, command, args=None, env=None) -> bool:
    if name in reg.mcp_servers:
        return False
    reg.mcp_servers[name] = {"command": command, "args": args or [], "env": env or {}}
    return True

def add_skill_dir(reg, path) -> bool:
    ap = str(pathlib.Path(path).resolve())
    existing = {str(pathlib.Path(p).resolve()) for p in reg.skill_dirs}
    if ap in existing:
        return False
    reg.skill_dirs.append(ap)
    return True

def remove(reg, kind, name) -> bool:
    if kind == "mcp":
        return reg.mcp_servers.pop(name, None) is not None
    if kind == "skill":
        target = str(pathlib.Path(name).resolve())
        before = len(reg.skill_dirs)
        reg.skill_dirs = [p for p in reg.skill_dirs if str(pathlib.Path(p).resolve()) != target]
        return len(reg.skill_dirs) != before
    raise ValueError(f"unknown kind: {kind}")

def set_auto_start(reg, name, enabled=True) -> bool:
    """Add or remove a skill name from auto_start. Returns True if it changed.

    The list preserves order and holds no duplicates. It stores the skill name
    (the same name that `use_skill` and `search` report), not a path.
    """
    present = name in reg.auto_start
    if enabled and not present:
        reg.auto_start.append(name)
        return True
    if not enabled and present:
        reg.auto_start = [n for n in reg.auto_start if n != name]
        return True
    return False

def summary(reg) -> dict[str, Any]:
    return {"mcp_servers": sorted(reg.mcp_servers), "skill_dirs": list(reg.skill_dirs),
            "migrations": [m.get("id") for m in reg.migrations],
            "auto_start": list(reg.auto_start)}
