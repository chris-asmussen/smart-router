import argparse, json, sys
from . import registry as R
from .claude_env import ClaudeEnv
from .config import writable_config_path
from . import migrate as M

def build_parser():
    p = argparse.ArgumentParser(prog="smart-router")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    m = sub.add_parser("migrate")
    m.add_argument("--all", action="store_true")
    m.add_argument("--mcp", nargs="*", default=[]); m.add_argument("--plugins", nargs="*", default=[])
    m.add_argument("--skills", nargs="*", default=[]); m.add_argument("--apply", action="store_true")
    m.add_argument("--home", default=None,
                   help="Operate on this Claude home instead of the real ~/.claude (safe testing).")
    a = sub.add_parser("add-mcp"); a.add_argument("name"); a.add_argument("--command", required=True)
    a.add_argument("--args", action="append", default=None); a.add_argument("--env", action="append", default=None)
    s = sub.add_parser("add-skill"); s.add_argument("path")
    sub.add_parser("list")
    r = sub.add_parser("restore"); r.add_argument("--id", required=True)
    r.add_argument("--home", default=None,
                   help="Operate on this Claude home instead of the real ~/.claude (safe testing).")
    return p

def _now():
    # entry-point supplies time; kept here so core stays deterministic in tests
    import datetime, uuid
    return (uuid.uuid4().hex[:8], datetime.datetime.now(datetime.timezone.utc).isoformat())

def _expand_greedy(argv):
    """argparse's per-value options reject values beginning with '-' (e.g.
    `--args -y srv`), classifying `-y` as an unknown optional. Rewrite each value
    following --args/--env into the `--opt=value` form, which bypasses that
    optional detection; combined with action="append" the values accumulate.
    Stops collecting at the next registered flag."""
    greedy = {"--args", "--env"}
    stops = {"--command", "--args", "--env", "--all", "--apply", "--id", "--home", "-h", "--help"}
    out, i = [], 0
    while i < len(argv):
        tok = argv[i]
        if tok in greedy:
            i += 1
            while i < len(argv) and argv[i] not in stops:
                out.append(f"{tok}={argv[i]}"); i += 1
        else:
            out.append(tok); i += 1
    return out

def run(argv, env=None, home=None, now=None) -> int:
    import os
    env = os.environ if env is None else env
    now = now or _now
    args = build_parser().parse_args(_expand_greedy(list(argv)))
    cmd = args.cmd or "serve"
    if cmd == "serve":
        from .server import mcp
        mcp.run(); return 0
    reg = R.load_registry(writable_config_path(env=env))  # writes persist to config_home, never CWD
    # A CLI --home flag (migrate/restore) overrides the function-param home; both
    # default to None -> the real ~/.claude. Lets users test migration against a
    # throwaway Claude home without touching their live config.
    cenv = ClaudeEnv(getattr(args, "home", None) or home)
    if cmd == "add-mcp":
        env_pairs = {}
        for kv in (args.env or []):
            if "=" not in kv:
                print(f"invalid --env '{kv}' (expected KEY=VALUE)", file=sys.stderr); return 2
            k, v = kv.split("=", 1); env_pairs[k] = v
        R.add_mcp_server(reg, args.name, args.command, args.args or [], env_pairs)
        R.save_registry(reg); print(f"registered mcp server: {args.name}"); return 0
    if cmd == "add-skill":
        R.add_skill_dir(reg, args.path); R.save_registry(reg); print(f"registered skill dir: {args.path}"); return 0
    if cmd == "list":
        print(json.dumps(R.summary(reg), indent=2)); return 0
    if cmd == "migrate":
        targets = {"mcp": "all" if args.all else args.mcp,
                   "plugins": "all" if args.all else args.plugins,
                   "personal_skills": "all" if args.all else args.skills}
        plan = M.plan_migration(cenv, reg, targets)
        if not args.apply:
            print(M.render_plan(plan)); return 0
        run_id, ts = now()
        man = M.apply_migration(cenv, reg, plan, run_id, ts)
        print(f"migrated (id={man['id']}). Restart Claude Code to apply. Restore with: smart-router restore --id {man['id']}")
        return 0
    if cmd == "restore":
        ok = M.restore(cenv, reg, args.id)
        print("restored" if ok else f"no migration with id {args.id}"); return 0
    return 2

def main() -> None:
    sys.exit(run(sys.argv[1:]))
