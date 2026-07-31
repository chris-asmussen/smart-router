"""Plan / apply / restore migrations of Claude MCPs + Skills into smart-router."""
import pathlib
from dataclasses import dataclass, field
from .claude_env import ClaudeEnv
from . import registry as R

@dataclass
class MigrationPlan:
    register_mcp: dict[str, dict] = field(default_factory=dict)
    register_skill_dirs: list[str] = field(default_factory=list)
    move_personal_skills: list[dict] = field(default_factory=list)
    disable_plugins: list[str] = field(default_factory=list)
    remove_mcp: list[str] = field(default_factory=list)

def _selected(target, available):
    if target == "all":
        return list(available)
    return [x for x in (target or []) if x in available]

def plan_migration(env: ClaudeEnv, reg: R.Registry, targets) -> MigrationPlan:
    plan = MigrationPlan()
    servers = env.discover_mcp_servers()
    for name in _selected(targets.get("mcp", []), servers):
        if name not in reg.mcp_servers:
            plan.register_mcp[name] = servers[name]
            plan.remove_mcp.append(name)
    plugin_skills = {p["plugin_key"]: p for p in env.discover_plugin_skills()}
    enabled = env.enabled_plugins()
    for key in _selected(targets.get("plugins", []), plugin_skills):
        if not enabled.get(key, False):
            continue
        plan.register_skill_dirs.append(plugin_skills[key]["skills_root"])
        plan.disable_plugins.append(key)
    personal = {s["name"]: s for s in env.discover_personal_skills()}
    managed = reg.path.parent / "skills"  # config dir, keeps tests hermetic
    for name in _selected(targets.get("personal_skills", []), personal):
        plan.move_personal_skills.append({"name": name, "from": personal[name]["path"],
                                          "to": str(managed / name)})
    if plan.move_personal_skills:
        plan.register_skill_dirs.append(str(managed))
    return plan

def render_plan(plan: MigrationPlan) -> str:
    lines = ["smart-router migration (dry run):"]
    for n in plan.register_mcp: lines.append(f"  + register mcp server: {n} (removed from Claude)")
    for k in plan.disable_plugins: lines.append(f"  + register plugin skills + DISABLE plugin: {k} (disables ALL its features)")
    for m in plan.move_personal_skills: lines.append(f"  + move personal skill: {m['name']} -> {m['to']}")
    if not (plan.register_mcp or plan.disable_plugins or plan.move_personal_skills):
        lines.append("  (nothing to migrate)")
    return "\n".join(lines)

def _rollback(env: ClaudeEnv, actions: list, best_effort: bool = False) -> None:
    """Reverse already-applied Claude-side actions in reverse order.

    best_effort=True (apply's failure path): keep reversing the remaining actions even
    if one reversal raises, so a single failure can't leave the rest un-reversed or mask
    the original exception the caller is about to re-raise. best_effort=False (restore):
    a reversal failure propagates so the user learns the restore did not fully complete."""
    for a in reversed(actions):
        try:
            if a["type"] == "disable_plugin":
                env.enable_plugin(a["key"], a.get("prev", True))
            elif a["type"] == "remove_mcp_server":
                env.add_mcp_server_raw(a["name"], a["value"], a["scope"])
            elif a["type"] == "move_personal_skill":
                env.move_back(a["to"], a["from"])
        except Exception:
            if not best_effort:
                raise

def apply_migration(env: ClaudeEnv, reg: R.Registry, plan: MigrationPlan, run_id, timestamp) -> dict:
    backup_dir = reg.path.parent / "backups"  # config dir, hermetic in tests
    # Pre-check every planned skill destination BEFORE touching anything on disk, so a
    # would-be move collision fails fast with nothing (Claude- or registry-side) mutated.
    for m in plan.move_personal_skills:
        if pathlib.Path(m["to"]).exists():
            raise FileExistsError(f"destination already exists: {m['to']}")
    actions, backups = [], {}
    try:
        for key in plan.disable_plugins:
            a = env.disable_plugin(key, backup_dir, run_id); actions.append(a)
            if a.get("backup"): backups[str(env.settings)] = a["backup"]
        for name in plan.remove_mcp:
            a = env.remove_mcp_server(name, backup_dir, run_id); actions.append(a)
            if a.get("backup"): backups[str(env.claude_json)] = a["backup"]
        for m in plan.move_personal_skills:
            actions.append(env.move_personal_skill(m["name"], pathlib.Path(m["to"]).parent, backup_dir, run_id))
    except Exception:
        _rollback(env, actions, best_effort=True)  # undo partial work, then propagate original
        raise
    # Claude side fully applied. Register in the durable registry, recording ONLY the
    # entries this run actually added (dedup returns False for pre-existing ones) so
    # restore de-registers exactly what it registered — never a shared/pre-existing dir.
    added_mcp = [name for name, conf in plan.register_mcp.items()
                 if R.add_mcp_server(reg, name, conf.get("command"), conf.get("args"), conf.get("env"))]
    added_dirs = [d for d in plan.register_skill_dirs if R.add_skill_dir(reg, d)]
    manifest = {
        "id": run_id, "created": timestamp,
        "registered": {"mcp_servers": added_mcp, "skill_dirs": added_dirs},
        "claude_actions": actions, "backups": backups,
    }
    reg.migrations.append(manifest)
    R.save_registry(reg)
    return manifest

def restore(env: ClaudeEnv, reg: R.Registry, run_id) -> bool:
    manifest = next((m for m in reg.migrations if m.get("id") == run_id), None)
    if manifest is None:
        return False
    _rollback(env, manifest["claude_actions"])  # reverse the recorded Claude-side actions
    for name in manifest["registered"]["mcp_servers"]:
        R.remove(reg, "mcp", name)
    for d in manifest["registered"]["skill_dirs"]:
        R.remove(reg, "skill", d)
    reg.migrations = [m for m in reg.migrations if m.get("id") != run_id]
    R.save_registry(reg)
    return True
