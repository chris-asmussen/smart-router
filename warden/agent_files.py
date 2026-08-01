"""Discovers and edits agent-instruction files (CLAUDE.md, AGENTS.md, GEMINI.md).

`warden init` writes a small "Capabilities via warden" block into the agent
instruction file. The block tells the agent to call `route` or `search` before
it decides that a capability is not available. Without this text, the agent does
not know that warden holds the hidden tools and Skills.

The block sits between two marker comments. Therefore a second run replaces the
block in place, and a remove run strips it cleanly. This keeps `warden init`
idempotent and reversible.

This module is pure. It takes a home directory and a working directory and it
returns paths and text. The caller does the input and the file writes through
the small helpers at the end.
"""
import pathlib
import re

BEGIN = "<!-- warden:begin -->"
END = "<!-- warden:end -->"

# The known agent-instruction files. Each file maps a scope to a path template.
# A "~/" prefix means the home directory. A bare name is relative to the working
# directory. warden stays agnostic: it edits any of these, and it never assumes
# which one you use.
AGENT_FILES = {
    "CLAUDE.md": {
        "user": "~/.claude/CLAUDE.md",
        "project": "CLAUDE.md",
        "local": "CLAUDE.local.md",
    },
    "AGENTS.md": {
        "user": "~/.codex/AGENTS.md",
        "project": "AGENTS.md",
        "local": "AGENTS.local.md",
    },
    "GEMINI.md": {
        "user": "~/.gemini/GEMINI.md",
        "project": "GEMINI.md",
        "local": "GEMINI.local.md",
    },
}

SCOPES = ("user", "project", "local")

_PATTERN = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
# For removal, absorb the newlines that hug the block so the gap closes to a
# single newline. This edits only the block site; it never touches blank runs
# elsewhere in the file.
_REMOVE = re.compile(r"\n*" + re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n*", re.DOTALL)


def capability_block() -> str:
    """Returns the block text with the markers, but with no trailing newline."""
    return (
        f"{BEGIN}\n"
        "## Capabilities via warden\n"
        "\n"
        "warden keeps many tools and Skills out of your context. Before you decide\n"
        "that a capability is not available, use warden first:\n"
        "\n"
        "1. Call `route` with a short description of the task. Add the current file\n"
        "   path if you have one. `route` returns the best tool or Skill to use.\n"
        "2. Or call `search` to find a capability by keyword.\n"
        "3. Then call `call_tool` or `use_skill` on the result.\n"
        f"{END}"
    )


def has_block(text: str) -> bool:
    """True if the text already holds a warden block."""
    return bool(_PATTERN.search(text))


def insert_block(text: str) -> str:
    """Returns the text with the warden block added or replaced in place."""
    block = capability_block()
    if has_block(text):
        # A function replacement keeps backslashes in the block literal.
        return _PATTERN.sub(lambda _m: block, text)
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text += "\n"  # one blank line between the old content and the block
    return text + block + "\n"


def remove_block(text: str) -> str:
    """Returns the text with the warden block removed and the gap closed."""
    if not has_block(text):
        return text
    new = _REMOVE.sub("\n", text).strip("\n")
    return new + "\n" if new else ""


def candidate_path(name: str, scope: str, home: pathlib.Path, cwd: pathlib.Path) -> pathlib.Path:
    """Resolves the path for one agent file in one scope."""
    template = AGENT_FILES[name][scope]
    if template.startswith("~/"):
        return home / template[2:]
    return cwd / template


def discover(home: pathlib.Path, cwd: pathlib.Path) -> list[dict]:
    """Reports every known agent file in every scope: path, exists, has_block."""
    found = []
    for name in AGENT_FILES:
        for scope in SCOPES:
            path = candidate_path(name, scope, home, cwd)
            exists = path.is_file()
            block = has_block(path.read_text(encoding="utf-8")) if exists else False
            found.append({"name": name, "scope": scope, "path": path,
                          "exists": exists, "has_block": block})
    return found


def apply_to_file(path: pathlib.Path, remove: bool = False) -> bool:
    """Writes the block into the file (or removes it). Returns True if it changed.

    It makes the parent directory and the file when they are absent, unless the
    call removes the block from a file that is not there.
    """
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    new = remove_block(text) if remove else insert_block(text)
    if new == text:
        return False
    if not remove:
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8")
    return True
