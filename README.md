# warden

[![CI](https://github.com/chris-asmussen/warden/actions/workflows/ci.yml/badge.svg)](https://github.com/chris-asmussen/warden/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

warden is one MCP server. It gives an agent access to many other MCP
servers and Skills. The agent sees only 5 tools:

- `search(query, limit=5)` — This tool does a regex or keyword search. It looks
  in the name, the description, and the arguments of each tool. It also looks in
  the name and the description of each Skill. No other data goes to the agent.
- `call_tool(server, name, arguments)` — This tool sends a call to the MCP
  server that has the tool. Use a `search` result to find the server and the
  tool.
- `use_skill(name)` — This tool returns the full instructions for a Skill. Use a
  `search` result to find the Skill.
- `admin(action, params)` — This tool controls the registry. It can also move
  MCP servers and Skills out of Claude Code. The changes are immediate, and you
  do not restart the server. Refer to [The `admin` tool](#the-admin-tool).
- `route(task, context=None, mode=None)` — This tool selects the best tool or
  Skill for a task. It ranks the candidates and returns the best one. It does
  not run the tool. Refer to [Routing](#routing).

At start, warden connects one time to each MCP server in the
configuration and gets its tools with `list_tools`. It also reads each Skill
directory and finds the `SKILL.md` files. warden keeps this catalog on the
server. The model does not get these definitions. The model gets only `search`
results, and only when it asks.

## How to use

The goal is to move your MCP servers and Skills behind warden. Then the
Claude context has only the 5 tools. warden supplies the other data only
when the agent asks for it.

1. **Install.**
   ```bash
   pip install -r requirements.txt        # or: pip install .  (for the warden command)
   ```

2. **Test first (the safe method).** The dry run shows each change. Then apply
   the migration to a temporary Claude home. warden does not change your
   real `~/.claude`.
   ```bash
   warden migrate --all                                   # dry run: shows each change
   warden migrate --all --apply --home /tmp/fake-claude   # apply to a temporary home
   warden restore --id <printed-id> --home /tmp/fake-claude
   ```

3. **Do the real migration.** Remove `--home` to change your real Claude
   configuration. warden adds the items to the registry. warden also
   disables the items in Claude.
   ```bash
   warden migrate --all --apply     # or select items: --plugins X --skills Y --mcp Z
   warden list                      # look at the registry
   ```
   To move only some items, add them one at a time. Use
   `warden add-mcp <name> --command <cmd> [--args ...]` or
   `warden add-skill <path>`.

4. **Set warden as the only MCP server in Claude.** Refer to the JSON in
   [Setup](#setup). Then restart Claude Code. Claude Code reads the disabled
   items at start. warden does not need a restart, because its catalog
   updates immediately.

5. **Use warden.** Give Claude a usual instruction. When Claude needs a
   tool, it calls `search`. Then it calls `call_tool` or `use_skill`.
   warden does not start hidden skills automatically. Add the instruction
   from [Limitation](#limitation-warden-does-not-start-skills-automatically)
   to your `CLAUDE.md`. To add or move more items later, an agent calls the
   `admin` tool, or you use the CLI. To reverse a migration, use
   `warden restore --id <id>`.

Each section below gives more data: [CLI](#cli),
[The `admin` tool](#the-admin-tool),
[Migration from Claude Code](#migration-from-claude-code).

## Setup

```bash
pip install -r requirements.txt
```

warden reads its catalog from a registry file. The registry file has the
same structure as `config.example.json`:

```json
{
  "mcp_servers": {
    "github": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {} }
  },
  "skill_dirs": ["./skills"]
}
```

You do not have to write the registry manually. The commands
`warden add-mcp`, `add-skill`, and `migrate` make the registry and change
it. An empty registry is also correct. Then warden starts with an empty
catalog and prints one line to stderr. An agent can then fill the registry with
the `admin` tool.

### Config location

warden finds the registry in this sequence:

1. `WARDEN_CONFIG` — the full path to the `config.json` file.
2. `WARDEN_HOME` — a directory. The registry is `<home>/config.json`.
3. The default: `~/.config/warden/config.json` (XDG).

All writes go to `WARDEN_CONFIG`, `WARDEN_HOME`, or the XDG default.
The commands `add-mcp`, `add-skill`, `migrate`, and the `admin` tool make these
writes. The writes do not go to the current directory. Therefore the registry
stays available in all sessions and from all directories. For reads, if none of
these are present, warden uses `./warden.config.json`.

To start the server, use one of these commands:

```bash
python3 -m warden          # or: warden  (the installed console command)
```

Each command is the same as `warden serve`.

Set warden as the only MCP server in your MCP client. Example clients are
Claude Desktop, Claude Code, Copilot CLI, and Cursor. For example:

```json
{
  "mcpServers": {
    "warden": {
      "command": "python3",
      "args": ["-m", "warden"],
      "cwd": "/path/to/warden"
    }
  }
}
```

## CLI

The same registry operations are available to you as subcommands. The default
subcommand is `serve`.

| Command | Function |
| --- | --- |
| `warden serve` | Runs the MCP server. This is the default. |
| `warden add-mcp <name> --command <cmd> [--args ...] [--env K=V ...]` | Adds an MCP server to the registry. |
| `warden add-skill <path>` | Adds a Skill directory to the registry. warden reads its `SKILL.md` files. |
| `warden list` | Prints the registry as JSON. It shows the MCP servers, the skill directories, and the migration ids. |
| `warden migrate [--all] [--mcp ...] [--plugins ...] [--skills ...] [--apply] [--home <dir>]` | Moves MCP servers and Skills out of Claude Code. This is a dry run. Add `--apply` to make the changes. Add `--home <dir>` to use a different Claude home for a test. |
| `warden restore --id <migration-id> [--home <dir>]` | Reverses a migration. It puts back the changes in Claude. Add `--home <dir>` for a test home. |
| `warden routing show` | Prints the routing configuration as JSON. |
| `warden routing set-mode <auto\|ask>` | Sets the default routing mode. |
| `warden routing prefer <name...>` | Adds names to `priority_order`. |
| `warden routing exclude <name...>` | Adds names to `exclude`. |
| `warden routing add-rule --ext <e...> \| --glob <g> [--prefer <n...>] [--exclude <n...>]` | Adds a per-file routing rule. |

```bash
warden add-mcp github --command npx --args -y @modelcontextprotocol/server-github
warden add-skill ~/my-skills
warden list
```

## The `admin` tool

The `admin(action, params)` tool gives the registry operations to an agent
through MCP. The agent can set up warden or change it, and the agent does
not restart the server. After each change, warden makes the internal
catalog again. Therefore `search` shows the change immediately. The actions are:

- `list` — returns `{mcp_servers, skill_dirs, migrations}`.
- `register_mcp` — `params: {name, command, args?, env?}`.
- `register_skill` — `params: {path}`.
- `unregister` — `params: {kind: "mcp"|"skill", name}`.
- `migrate` — `params: {targets: {mcp, plugins, personal_skills}, apply?}`. This
  is a dry run and returns the plan. Set `apply` to true to make the changes.
  Each target is an array of names or keys, or the text `"all"`.
- `restore` — `params: {id}`.
- `get_routing` — returns the routing configuration.
- `set_routing` — `params: {mode?, priority_order?, exclude?, rules?}`. It
  changes the routing configuration. Refer to [Routing](#routing).

## Routing

The `route` tool selects the best tool or Skill for a task. It ranks the
candidates and returns the best one. It does not run the tool. The agent then
calls `call_tool` or `use_skill` on the result.

`route(task, context=None, mode=None)`:

- `task` — a description of what you want to do.
- `context` — optional and light. It is `{"file_path"?, "extension"?,
  "project_markers"?}`. It holds references only, not file content. If you omit
  it, warden still ranks from the configuration.
- `mode` — `"auto"` returns the single best pick. `"ask"` returns a ranked list.
  The default comes from the configuration. If only one tool is a candidate,
  warden returns it directly and does not rank.

The result is `{"mode", "single_option", "chosen", "candidates"}`. Each
candidate has a `name`, a `score`, and `reasons`.

Routing rules live in the configuration (the `routing` block). warden reads
them at each call, so a change takes effect immediately.

- `priority_order` — a list of names. An earlier name gets a higher rank and
  wins a tie.
- `exclude` — a list of names. warden never routes to these.
- `rules` — per-file rules. Each rule is
  `{"when": {"extension"?: [...], "path_glob"?: "..."}, "prefer"?: [...],
  "exclude"?: [...]}`. A rule matches the passed `context`. If you omit the
  context, warden skips the context rules and uses `priority_order` and
  `exclude` only.

Set the rules with the CLI or the `admin` `set_routing` action:

```bash
warden routing set-mode ask
warden routing prefer ts-tools code-reviewer
warden routing exclude legacy-linter
warden routing add-rule --ext tsx --prefer ts-tools
warden routing show
```

## Migration from Claude Code

Claude Code loads each MCP tool and Skill into the context at start. The
`migrate` command moves them behind warden. The command does these tasks:

- **MCP servers** — warden copies the server into the registry.
  warden removes the server from `~/.claude.json` (the user scope or the
  project scope).
- **Plugins** — warden adds the Skills directory of the plugin to the
  registry. warden disables the plugin in `~/.claude/settings.json`. This
  action disables all the functions of that plugin. Look at the dry run first.
- **Personal skills** — warden moves the directory
  `~/.claude/skills/<name>` into a warden directory. warden adds that
  directory to the registry.

Before each change, warden makes a backup of the file. warden also
writes a manifest that permits a reverse. Therefore `restore --id <id>` (or
`admin restore`) puts back all the changes.

```bash
warden migrate --all                 # dry run: shows each change
warden migrate --all --apply         # apply the changes and print the migration id
warden restore --id <id>             # reverse the migration
```

**Safe test.** By default, `migrate` and `restore` change your real `~/.claude`.
Add `--home <dir>` to use a different Claude home. Then you can do a full test of
a migration and its `restore`. Your real configuration does not change.

```bash
warden migrate --all --apply --home /tmp/fake-claude
warden restore --id <id> --home /tmp/fake-claude
```

> **Restart Claude Code.** Claude Code reads `~/.claude.json` and
> `~/.claude/settings.json` at start. Therefore the changes to the MCP servers
> and the plugins take effect only after a restart. The warden catalog
> updates immediately.

### Limitation: warden does not start skills automatically

You get skills behind warden only through `search`. Claude Code cannot
start these skills automatically from their description. This is the cost to
keep them out of the context until you need them. To help, tell the model to use
warden first. This is an example `CLAUDE.md` text:

```markdown
## Capabilities

warden hides many tools and skills to keep them out of the context. Before
you decide that a capability is not available, call the warden `search`
with a description of your need. Then call `use_skill` or `call_tool` on a
result.
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

`tests.test_search` and `tests.test_config` are self-contained and need no other
software. `tests.test_integration` runs the full server through stdio MCP. It
uses a test MCP server and a test skill, and it needs `mcp`. If `mcp` is not
installed, this test skips automatically.

## Design notes

- The search is one function. It does regex scoring and keyword scoring
  together, and it uses only the standard `re` module. Refer to
  `warden/search.py`.
- The `call_tool` tool opens a new connection to the MCP server for each call.
  It does not keep a pool of connections. Refer to `warden/downstream.py`.
  This design is simple and correct. It is sufficient, unless the start time of
  the subprocess becomes a measured problem.
- The configuration is plain JSON. It does not need a YAML dependency for two
  keys.
