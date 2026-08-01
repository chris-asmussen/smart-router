"""Builds the always-on instruction block for auto_start Skills.

Most Skills stay hidden until `search` surfaces them. That keeps the agent's
context small, which is the point of warden. A few Skills only work when they
are always active, though. A "think before you code" ruleset, for example, must
sit in the context before the agent writes anything; it cannot wait for a
search. `auto_start` is the opt-in escape hatch for that case.

A Skill flagged `auto_start` has its full text folded into warden's MCP server
`instructions`. The MCP client reads those instructions one time, at the start
of each session, so the Skill is always active. This spends context on purpose.
Keep the set small. A change to the set takes effect at the next client
restart, because the client reads the instructions only at startup.

This module is pure. The server passes in the loaded Skills and the wanted
names, and it returns text and warnings.
"""
from typing import Any

# A cap on the appended auto_start text. Past this, warden truncates and warns,
# so one large Skill cannot flood the context by mistake.
MAX_CHARS = 12000


def collect_auto_start(skills: list[dict[str, Any]], names: list[str]):
    """Return the wanted Skills in `names` order, plus the names that no Skill provides.

    A name with no matching Skill goes into `missing` so the caller can warn.
    """
    by_name = {s["name"]: s for s in skills}
    chosen = [by_name[n] for n in names if n in by_name]
    missing = [n for n in names if n not in by_name]
    return chosen, missing


def render_block(skills: list[dict[str, Any]]) -> str:
    """Render the always-on block for the given Skills. Empty input gives ''."""
    if not skills:
        return ""
    parts = ["The following Skills are always active. Apply them to every task, "
             "without a search:"]
    for skill in skills:
        parts.append(f"\n--- Skill: {skill['name']} ---\n{skill['content'].strip()}")
    return "\n".join(parts)


def build_instructions(base: str, skills: list[dict[str, Any]], max_chars: int = MAX_CHARS):
    """Return (instructions, warnings). Append the always-on block to `base`.

    The block holds the full text of each Skill. If the block is longer than
    `max_chars`, warden truncates it and adds a warning. With no Skills, it
    returns `base` unchanged and no warnings.
    """
    warnings: list[str] = []
    block = render_block(skills)
    if not block:
        return base, warnings
    if len(block) > max_chars:
        block = block[:max_chars].rstrip() + "\n[... auto_start text truncated by warden ...]"
        warnings.append(
            f"auto_start text is longer than {max_chars} characters; warden truncated it. "
            "Flag fewer Skills as auto_start.")
    return base + "\n\n" + block, warnings
