import json, pathlib

def build_fake_claude_home(root: pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(root)
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    # indent=2 to match how claude_env re-writes these files (keeps diffs clean;
    # round-trip tests compare parsed JSON, not bytes, so formatting is not load-bearing).
    (root / ".claude.json").write_text(json.dumps({
        "mcpServers": {"github": {"command": "npx", "args": ["-y", "srv"], "env": {}}},
        "projects": {"/tmp/p": {"mcpServers": {"local": {"command": "python", "args": ["s.py"]}}}},
    }, indent=2))
    (root / ".claude" / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"alpha@example-market": True, "beta@other-market": True},
    }, indent=2))
    sk = root / ".claude" / "skills" / "myskill"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text("---\nname: myskill\ndescription: does a thing\n---\nBody")
    cache = root / ".claude" / "plugins" / "cache"
    # alpha has two cached hash dirs. installed_plugins.json (below) records
    # abc123 as the active install even though def456 sorts greater, so the
    # dedup MUST prefer the recorded hash, not the max.
    for h in ("abc123", "def456"):
        pk = cache / "example-market" / "alpha" / h / "skills" / "alpha"
        pk.mkdir(parents=True)
        (pk / "SKILL.md").write_text("---\nname: alpha\ndescription: does alpha things\n---\nBody")
    # beta has two cached hash dirs but is ABSENT from installed_plugins.json,
    # exercising the max-hash fallback (2.0.0 wins over 1.0.0).
    for h in ("1.0.0", "2.0.0"):
        pk = cache / "other-market" / "beta" / h / "skills" / "beta"
        pk.mkdir(parents=True)
        (pk / "SKILL.md").write_text("---\nname: beta\ndescription: does beta things\n---\nBody")
    # installPath is absolute against the recorded home; only its basename (the
    # hash dir) is used for matching, so a real-home path never collides with a
    # temp fixture. version is a usable secondary signal.
    (root / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({
        "version": 2,
        "plugins": {
            "alpha@example-market": [
                {"scope": "user",
                 "installPath": str(cache / "example-market" / "alpha" / "abc123"),
                 "version": "abc123"},
            ],
        },
    }, indent=2))
    return root
