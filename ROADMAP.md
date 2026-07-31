# Roadmap

The main goal of warden is a small agent context. The agent must still get
access to many MCP servers and Skills when it needs them. Each item here serves
this goal. This document changes over time. Open an issue to propose a change.

## Now (0.1.x — make the current features strong)

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

## Later (ideas, no schedule)

- Support the configuration layout of more MCP clients in `migrate`, not only
  Claude Code. Use the same adapter boundary as `claude_env`.
- Handle a name conflict when two downstream servers have a tool with the same
  name.
- Publish the package to PyPI. Give a one-line install.

## Not in scope

- warden does not proxy the claude.ai integrations, for example Slack or
  Drive. These are not local stdio servers.
- warden does not add more than the 4 model-facing tools (`search`,
  `call_tool`, `use_skill`, and `admin`). A new function is an `admin` action or
  a CLI subcommand.
- warden does not copy the automatic skill start of Claude Code.

Refer to the
[good first issues](https://github.com/chris-asmussen/warden/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)
to start.
