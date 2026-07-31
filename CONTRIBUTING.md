# How to contribute to smart-router

Thank you for your interest in smart-router. This project puts many MCP servers
and Skills behind a small set of 4 tools. We prefer contributions that keep this
set small and the core light.

## How to start

```bash
git clone https://github.com/chris-asmussen/smart-router
cd smart-router
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installs the mcp dependency and the smart-router command
```

You must have Python 3.10 or later.

## The tests

```bash
python -m unittest discover -s tests -v
```

- `test_search`, `test_config`, `test_registry`, `test_claude_env`,
  `test_migrate`, and `test_cli` are self-contained. They do not need `mcp`.
- `test_integration` runs the full server through stdio MCP. It needs `mcp`.
  `pip install -e .` installs `mcp`. If `mcp` is not present, this test skips
  automatically.

CI runs the full test set on Python 3.10, 3.11, and 3.12 for each pull request.
Make sure `python -m unittest discover -s tests` passes before you open a pull
request.

## Coding standards

These are the standards for each change. Write your contribution in your
preferred way. You can write it by hand or with a tool of your choice. This
project does not require an editor, an assistant, or a workflow. The review
looks only at the code against the standards below.

- **Write the test first.** Each change to the behavior needs a test. This
  codebase is test-driven. Use the patterns in `tests/`. Use temporary
  directories or the builder in `tests/fixtures/fake_claude_home.py`. A test
  must not read or change a real `~/.claude` or `~/.config/smart-router`.
- **Keep the core in the standard library.** The modules `config`, `registry`,
  `claude_env`, `migrate`, and `cli` use only the standard library. Only
  `server.py` imports `mcp`. Open an issue before you add a dependency.
- **Keep the set of tools small.** The purpose of smart-router is a small agent
  context. A new model-facing MCP tool needs a strong reason. Prefer an `admin`
  action or a CLI subcommand.
- **Keep the code deterministic.** The modules `registry` and `migrate` do not
  call `datetime.now()` and do not make UUIDs. The entry points supply the
  timestamps and the run ids. This keeps the tests deterministic.
- **Match the style around your change.** Use small modules with one
  responsibility. Use snake_case. Write short docstrings that give the reason.

## Architecture

The core uses only the standard library. It has small modules, and each module
has one responsibility. `config` finds the paths. `registry` holds the catalog.
`claude_env` is the only module that reads or writes the Claude Code files.
`migrate` does the plan, the apply, and the restore. `cli` is the command-line
interface. `server.py` gives the 4 MCP tools. Refer to the [README](README.md)
for the user behavior. Refer to the docstrings for the reason behind each part.

## Pull requests

1. Fork the repository. Make a branch from `main`.
2. Make the change with a test. Keep the test set green.
3. Write clear commit messages in the
   [Conventional Commits](https://www.conventionalcommits.org/) style. Use
   `feat:`, `fix:`, `docs:`, `test:`, or `refactor:`.
4. Open the pull request against `main`. Complete the template. Link the issue
   that the pull request closes.

We mark good first contributions with the label
[`good first issue`](https://github.com/chris-asmussen/smart-router/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

## How to report a bug or request a feature

Use the issue templates. For a security problem, follow [SECURITY.md](SECURITY.md).
Do not open a public issue for a security problem.

When you contribute, you agree that your contribution uses the project
[MIT License](LICENSE).
