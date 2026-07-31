import argparse, json, sys
from . import registry as R
from .claude_env import ClaudeEnv
from .config import writable_config_path
from . import migrate as M

def build_parser():
    p = argparse.ArgumentParser(prog="warden")
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

    from .agent_files import SCOPES, AGENT_FILES
    it = sub.add_parser("init")
    it.add_argument("--scope", choices=list(SCOPES), default=None,
                    help="user (~/.claude/CLAUDE.md), project (./CLAUDE.md), or local (./CLAUDE.local.md).")
    it.add_argument("--file", dest="agent_file", choices=list(AGENT_FILES), default=None,
                    help="Which agent-instruction file to write. Default CLAUDE.md.")
    it.add_argument("--remove", action="store_true", help="Remove the warden block instead of adding it.")
    it.add_argument("--print", dest="print_only", action="store_true", help="Print the block and exit.")
    it.add_argument("--yes", action="store_true", help="Do not prompt; use --scope/--file (non-interactive).")

    asc = sub.add_parser("auto-start")
    ascsub = asc.add_subparsers(dest="auto_start_cmd")
    ascsub.add_parser("list")
    aa = ascsub.add_parser("add"); aa.add_argument("names", nargs="+")
    arm = ascsub.add_parser("remove"); arm.add_argument("names", nargs="+")

    rt = sub.add_parser("routing")
    rtsub = rt.add_subparsers(dest="routing_cmd")
    rtsub.add_parser("show")
    sm = rtsub.add_parser("set-mode"); sm.add_argument("mode", choices=["auto", "ask"])
    pf = rtsub.add_parser("prefer")
    pf.add_argument("names", nargs="+", help="append to priority_order (order-preserving, deduped)")
    ex = rtsub.add_parser("exclude")
    ex.add_argument("names", nargs="+", help="append to exclude (order-preserving, deduped)")
    ar = rtsub.add_parser("add-rule")
    ar.add_argument("--ext", nargs="*", default=None)
    ar.add_argument("--glob", default=None)
    ar.add_argument("--prefer", nargs="*", default=None)
    ar.add_argument("--exclude", nargs="*", default=None)
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

def run(argv, env=None, home=None, now=None, cwd=None) -> int:
    import os, pathlib
    env = os.environ if env is None else env
    now = now or _now
    args = build_parser().parse_args(_expand_greedy(list(argv)))
    cmd = args.cmd or "serve"
    if cmd == "serve":
        from .server import mcp, apply_startup_instructions
        apply_startup_instructions()  # fold auto_start Skills in before the client reads instructions
        mcp.run(); return 0
    if cmd == "init":
        init_home = pathlib.Path(env.get("HOME") or pathlib.Path.home())
        init_cwd = pathlib.Path(cwd) if cwd is not None else pathlib.Path.cwd()
        return _run_init(args, init_home, init_cwd)
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
        print(f"migrated (id={man['id']}). Restart Claude Code to apply. Restore with: warden restore --id {man['id']}")
        return 0
    if cmd == "restore":
        ok = M.restore(cenv, reg, args.id)
        print("restored" if ok else f"no migration with id {args.id}"); return 0
    if cmd == "routing":
        return _run_routing(args, reg)
    if cmd == "auto-start":
        return _run_auto_start(args, reg)
    return 2

def _dedupe(seq):
    """Order-preserving de-duplication (for priority_order / exclude appends)."""
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def _run_auto_start(args, reg) -> int:
    sub = args.auto_start_cmd
    if sub is None:
        print("usage: warden auto-start {list,add,remove}", file=sys.stderr)
        return 2
    if sub == "list":
        print(json.dumps(list(reg.auto_start), indent=2)); return 0
    if sub == "add":
        from .catalog import load_skills
        known = {s["name"] for s in load_skills(reg.skill_dirs)}
        for name in args.names:
            R.set_auto_start(reg, name, True)
            if name not in known:
                print(f"warning: '{name}' is not a registered skill; register its "
                      "directory first with `warden add-skill <path>`.", file=sys.stderr)
        R.save_registry(reg)
        print(f"auto_start: {reg.auto_start}")
        print("Restart the MCP client so it reloads warden's instructions.")
        return 0
    if sub == "remove":
        for name in args.names:
            R.set_auto_start(reg, name, False)
        R.save_registry(reg)
        print(f"auto_start: {reg.auto_start}")
        print("Restart the MCP client so it reloads warden's instructions.")
        return 0
    return 2


def _run_routing(args, reg) -> int:
    from .routing import load_routing, save_routing
    sub = args.routing_cmd
    if sub is None:
        print("usage: warden routing {show,set-mode,prefer,exclude,add-rule}", file=sys.stderr)
        return 2
    block = load_routing(reg)  # validated, defaults filled
    if sub == "show":
        print(json.dumps(block, indent=2)); return 0
    if sub == "set-mode":
        block["mode"] = args.mode
        save_routing(reg, block); print(f"routing mode: {args.mode}"); return 0
    if sub == "prefer":
        block["priority_order"] = _dedupe(block["priority_order"] + args.names)
        save_routing(reg, block); print(f"priority_order: {block['priority_order']}"); return 0
    if sub == "exclude":
        block["exclude"] = _dedupe(block["exclude"] + args.names)
        save_routing(reg, block); print(f"exclude: {block['exclude']}"); return 0
    if sub == "add-rule":
        # `--ext` with no values (args.ext == []) means the flag was typed but
        # empty; treat it as an error rather than silently dropping the selector.
        if args.ext is not None and len(args.ext) == 0:
            print("routing add-rule: --ext requires at least one extension", file=sys.stderr)
            return 2
        if args.ext is None and args.glob is None:
            print("routing add-rule requires --ext <e...> or --glob <g>", file=sys.stderr)
            return 2
        when = {}
        if args.ext:
            when["extension"] = args.ext
        if args.glob is not None:
            when["path_glob"] = args.glob
        rule = {"when": when}
        if args.prefer:
            rule["prefer"] = args.prefer
        if args.exclude:
            rule["exclude"] = args.exclude
        block["rules"].append(rule)
        save_routing(reg, block); print("added routing rule"); return 0
    return 2

def _prompt(text, default=None):
    """Reads one line. Returns the default when the input is empty or absent."""
    try:
        got = input(text).strip()
    except EOFError:
        return default
    return got or default


def _run_init(args, home, cwd) -> int:
    """Writes (or removes) the warden capability block in an agent file.

    Interactive by default: it shows what it found and asks for the scope, the
    file, and one confirmation before it writes. `--yes` skips the prompts and
    uses `--scope`/`--file`, so scripts and tests stay non-interactive.
    """
    from . import agent_files as A
    if args.print_only:
        print(A.capability_block()); return 0

    interactive = not args.yes
    scope = args.scope
    name = args.agent_file

    if interactive:
        found = [d for d in A.discover(home, cwd) if d["exists"]]
        if found:
            print("Found agent files:")
            for d in found:
                mark = " (has warden block)" if d["has_block"] else ""
                print(f"  [{d['scope']}] {d['path']}{mark}")
        else:
            print("No agent files found yet. warden can create one.")
        if scope is None:
            scope = _prompt(f"Scope {A.SCOPES}? [user]: ", "user")
            if scope not in A.SCOPES:
                print(f"unknown scope '{scope}'", file=sys.stderr); return 2
        # Never assume the file. If several already exist in this scope, ask.
        present = [d["name"] for d in found if d["scope"] == scope]
        if name is None:
            choices = present or list(A.AGENT_FILES)
            default = choices[0]
            name = _prompt(f"File {choices}? [{default}]: ", default)
            if name not in A.AGENT_FILES:
                print(f"unknown file '{name}'", file=sys.stderr); return 2
    else:
        scope = scope or "user"
        name = name or "CLAUDE.md"

    path = A.candidate_path(name, scope, home, cwd)
    verb = "Remove the warden block from" if args.remove else "Write the warden block to"
    if interactive:
        ok = _prompt(f"{verb} {path}? [y/N]: ", "n")
        if ok.lower() not in ("y", "yes"):
            print("no change"); return 0

    changed = A.apply_to_file(path, remove=args.remove)
    if args.remove:
        print(f"removed the warden block from {path}" if changed else f"no warden block in {path}")
    else:
        print(f"wrote the warden block to {path}" if changed else f"{path} already has the warden block")
        if scope == "local":
            print(f"note: add {path.name} to .gitignore so it stays personal.")
    return 0


def main() -> None:
    sys.exit(run(sys.argv[1:]))
