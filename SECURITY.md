# Security policy

## How to report a vulnerability

Do not open a public issue for a security vulnerability.

Report the vulnerability in private. Use the GitHub
[private vulnerability report](https://github.com/chris-asmussen/warden/security/advisories/new).
This is the "Report a vulnerability" button on the Security tab of the
repository. If this method is not available, contact the maintainer in private.
Do not open a public issue.

Include this data in your report:

- a description of the problem and its effect,
- the steps to reproduce the problem, or a proof of concept,
- the version or the commit that has the problem.

We acknowledge your report as soon as possible. We keep you informed about the
correction.

## Notes on scope

warden runs on your local machine. By design, it can read and change the
Claude Code files (`~/.claude.json` and `~/.claude/settings.json`). It can also
start the downstream MCP-server subprocesses in its registry. Keep these two
points in mind:

- The `migrate` command changes your Claude configuration. It makes a backup
  first. It also records a manifest for the reverse (`restore`). The `--home`
  option lets you do a test against a temporary directory. This command changes
  local configuration, so use it with care.
- warden runs each downstream MCP server with the command, the arguments,
  and the environment that you register. Register only a server that you trust.
  Use the same care as when you configure the server in Claude.

We welcome a report about these functions if you find a way to abuse them beyond
their intended use.
