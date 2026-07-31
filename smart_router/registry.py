"""Durable smart-router registry (mcp_servers + skill_dirs + migrations)."""
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

def load_registry(path=None) -> Registry:
    p = writable_config_path() if path is None else pathlib.Path(path)
    if not p.exists():
        return Registry(path=p)
    d = json.loads(p.read_text(encoding="utf-8"))
    return Registry(d.get("mcp_servers", {}), d.get("skill_dirs", []),
                    d.get("migrations", []), p, d.get("routing", {}))

def save_registry(reg: Registry) -> None:
    reg.path.parent.mkdir(parents=True, exist_ok=True)
    reg.path.write_text(json.dumps(
        {"mcp_servers": reg.mcp_servers, "skill_dirs": reg.skill_dirs,
         "migrations": reg.migrations, "routing": reg.routing},
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

def summary(reg) -> dict[str, Any]:
    return {"mcp_servers": sorted(reg.mcp_servers), "skill_dirs": list(reg.skill_dirs),
            "migrations": [m.get("id") for m in reg.migrations]}
