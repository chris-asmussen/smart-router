"""The only module that touches Claude Code's on-disk config. Parameterized by
`home` so tests use a fake tree and never the real ~/.claude."""
import json, pathlib, shutil
from typing import Any

class ClaudeEnv:
    def __init__(self, home: pathlib.Path = None):
        self.home = pathlib.Path(home) if home else pathlib.Path.home()
        self.claude_json = self.home / ".claude.json"
        self.settings = self.home / ".claude" / "settings.json"
        self.skills_dir = self.home / ".claude" / "skills"
        self.plugins_cache = self.home / ".claude" / "plugins" / "cache"
        self.installed_plugins = self.home / ".claude" / "plugins" / "installed_plugins.json"

    def _read_json(self, p: pathlib.Path) -> dict:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def discover_mcp_servers(self) -> dict[str, dict]:
        d = self._read_json(self.claude_json)
        out: dict[str, Any] = dict(d.get("mcpServers") or {})
        for proj in (d.get("projects") or {}).values():
            out.update(proj.get("mcpServers") or {})
        return out

    def discover_personal_skills(self) -> list[dict]:
        out = []
        if self.skills_dir.exists():
            for md in sorted(self.skills_dir.glob("*/SKILL.md")):
                out.append({"name": md.parent.name, "path": str(md.parent), "skill_md": str(md)})
        return out

    def _active_plugin_dirs(self) -> dict[str, set]:
        """Map plugin_key -> set of active hash-dir names, from installed_plugins.json.
        A plugin may be installed under multiple scopes, so the value is a list; we
        union across entries. Only the basename of installPath is used (it is absolute
        against the recorded home and never collides with a temp fixture); version is a
        usable secondary signal (sometimes literally "unknown", which is also the dir)."""
        d = self._read_json(self.installed_plugins)
        out: dict[str, set] = {}
        for key, entries in (d.get("plugins") or {}).items():
            dirs: set = set()
            for e in (entries or []):
                ip = e.get("installPath")
                if ip:
                    dirs.add(pathlib.Path(ip).name)
                v = e.get("version")
                if v:
                    dirs.add(v)
            if dirs:
                out[key] = dirs
        return out

    def discover_plugin_skills(self) -> list[dict]:
        if not self.plugins_cache.exists():
            return []
        active = self._active_plugin_dirs()
        # A plugin can have several cached <hash> version dirs, each with the same
        # SKILL.md path shape, so the glob yields duplicate (plugin_key, name) pairs.
        # Group them and keep one: prefer the hash recorded active in
        # installed_plugins.json (a stale max-sorting dir can hold an older commit
        # with different skills/descriptions); otherwise fall back to the max hash.
        groups: dict[tuple, list[dict]] = {}
        for md in sorted(self.plugins_cache.glob("*/*/*/skills/*/SKILL.md")):
            # cache/<marketplace>/<plugin>/<hash>/skills/<name>/SKILL.md
            marketplace = md.parents[4].name
            plugin = md.parents[3].name
            hash_dir = md.parents[2].name
            skills_root = md.parents[1]
            plugin_key = f"{plugin}@{marketplace}"
            name = md.parent.name
            groups.setdefault((plugin_key, name), []).append(
                {"name": name, "plugin_key": plugin_key, "skills_root": str(skills_root),
                 "skill_md": str(md), "_hash": hash_dir})
        out = []
        for (plugin_key, _name), cands in groups.items():
            active_dirs = active.get(plugin_key)
            chosen = None
            if active_dirs:
                active_cands = [c for c in cands if c["_hash"] in active_dirs]
                if active_cands:
                    chosen = max(active_cands, key=lambda c: c["_hash"])
            if chosen is None:
                chosen = max(cands, key=lambda c: c["_hash"])
            chosen = {k: v for k, v in chosen.items() if k != "_hash"}
            out.append(chosen)
        out.sort(key=lambda c: (c["plugin_key"], c["name"]))
        return out

    def enabled_plugins(self) -> dict[str, bool]:
        return dict(self._read_json(self.settings).get("enabledPlugins") or {})

    def backup_then_write(self, path, new_text, backup_dir, run_id) -> str:
        backup_dir = pathlib.Path(backup_dir); backup_dir.mkdir(parents=True, exist_ok=True)
        bpath = ""
        if pathlib.Path(path).exists():
            bpath = str(backup_dir / f"{pathlib.Path(path).name}.bak-{run_id}")
            # Back up each file at most once per run so the first (pristine) copy is
            # never overwritten by a later same-file mutation within the same run.
            if not pathlib.Path(bpath).exists():
                shutil.copy2(path, bpath)
        pathlib.Path(path).write_text(new_text, encoding="utf-8")
        return bpath

    def disable_plugin(self, key, backup_dir, run_id) -> dict:
        d = self._read_json(self.settings)
        ep = d.get("enabledPlugins") or {}; d["enabledPlugins"] = ep
        prev = ep.get(key, True); ep[key] = False
        b = self.backup_then_write(self.settings, json.dumps(d, indent=2), backup_dir, run_id)
        return {"type": "disable_plugin", "key": key, "prev": prev, "backup": b}

    def enable_plugin(self, key, enabled=True) -> None:
        d = self._read_json(self.settings)
        ep = d.get("enabledPlugins") or {}; d["enabledPlugins"] = ep
        ep[key] = enabled
        self.settings.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def remove_mcp_server(self, name, backup_dir, run_id) -> dict:
        d = self._read_json(self.claude_json)
        scope, value = None, None
        if name in (d.get("mcpServers") or {}):
            scope, value = "user", d["mcpServers"].pop(name)
        else:
            for proj_path, proj in (d.get("projects") or {}).items():
                if name in (proj.get("mcpServers") or {}):
                    scope, value = proj_path, proj["mcpServers"].pop(name); break
        b = self.backup_then_write(self.claude_json, json.dumps(d, indent=2), backup_dir, run_id)
        return {"type": "remove_mcp_server", "name": name, "scope": scope, "value": value, "backup": b}

    def add_mcp_server_raw(self, name, value, scope) -> None:
        d = self._read_json(self.claude_json)
        if scope == "user":
            d.setdefault("mcpServers", {})[name] = value
        else:
            d.setdefault("projects", {}).setdefault(scope, {}).setdefault("mcpServers", {})[name] = value
        self.claude_json.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def move_personal_skill(self, name, dest_dir, backup_dir, run_id) -> dict:
        src = self.skills_dir / name; dest = pathlib.Path(dest_dir) / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise FileExistsError(f"destination already exists: {dest}")
        shutil.move(str(src), str(dest))
        return {"type": "move_personal_skill", "name": name, "from": str(src), "to": str(dest)}

    def move_back(self, frm, to) -> None:
        to_p = pathlib.Path(to)
        to_p.parent.mkdir(parents=True, exist_ok=True)
        # Symmetric with move_personal_skill: refuse to clobber/nest into an existing dest.
        if to_p.exists():
            raise FileExistsError(f"destination already exists: {to_p}")
        shutil.move(str(frm), str(to))
