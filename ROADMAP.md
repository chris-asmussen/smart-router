# Roadmap

The main goal of warden is a small agent context. The agent must still get
access to many MCP servers and Skills when it needs them. Each item here serves
this goal. This document changes over time. Open an issue to propose a change.

## Shipped

- 0.3.0 — the `warden init` command. It writes a capability block into your
  agent-instruction file (`CLAUDE.md`, `AGENTS.md`, or `GEMINI.md`), so the
  agent calls `route` first. It asks for the scope (user, project, or local) and
  the file. It is idempotent, and `--remove` reverses it.
- 0.2.0 — the `route` tool and the routing configuration. `route` ranks the
  candidate tools and Skills for a task and returns the best one. It does not
  run the tool. The routing block adds `priority_order`, `exclude`, and per-file
  rules, with an `auto` mode and an `ask` mode.

## Now (0.2.x — make the current features strong)

- Add more tests for the edge cases in `migrate` and `restore`. Test a partial
  failure and its rollback. Test mixed selections. Test a second run for
  idempotency.
- Improve the relevance of `search`. The current score uses regex counts and
  substring counts. Look at simple improvements to the rank. Do not add a
  dependency.
- Add a short video or GIF of the migration to the README.

## Next (0.2 — usability)

- Add a `warden status` command. Give the `list` command more output.
- Improve the `migrate` output. Show a dry-run difference by plugin. Show each
  item that `--apply` disables.
- Add a `warden doctor` command. It checks the registry. It checks that
  the MCP servers respond.
- Reuse a connection in `call_tool` when a downstream server gets many calls.
  The current code opens one connection for each call.
- Add an opt-in auto-execute for `route`. Today `route` returns the pick and the
  agent runs it. A flag could make `route` run the chosen tool directly.
- Add project-local routing rules. Read a `./.warden.json` file so a project can
  set its own `priority_order`, `exclude`, and rules, next to the global
  configuration.

## Later (ideas, no schedule)

- Support the configuration layout of more MCP clients in `migrate`, not only
  Claude Code. Use the same adapter boundary as `claude_env`.
- Handle a name conflict when two downstream servers have a tool with the same
  name.
- Publish the package to PyPI. Give a one-line install.

## Not in scope

- warden does not proxy the claude.ai integrations, for example Slack or
  Drive. These are not local stdio servers.
- warden keeps the model-facing tool set as small as possible. A new
  model-facing tool needs a strong reason. Prefer an `admin` action or a CLI
  subcommand instead. The tools today are `search`, `call_tool`, `use_skill`,
  `admin`, and `route`. `route` is the one tool beyond the core four, because
  the agent must call it during a task to select a tool.
- warden does not copy the automatic skill start of Claude Code.

Refer to the
[good first issues](https://github.com/chris-asmussen/warden/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
to start.
