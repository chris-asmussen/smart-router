"""Scores catalog entries (tools + skills) against a free-text or regex query.

One function handles both query styles (regex and plain-English keywords)
instead of exposing two separate search tools like Anthropic's
tool_search_tool_regex / tool_search_tool_bm25 split: we fully control the
matcher, so there's no need for the model to pick a mode up front.
"""
import re
from typing import Any


def _blob(entry: dict[str, Any]) -> str:
    parts = [entry.get("name", ""), entry.get("description", "")]
    schema = entry.get("input_schema") or {}
    parts += list(schema.get("properties", {}).keys())
    return " ".join(parts)


def score(entry: dict[str, Any], query: str) -> int:
    blob = _blob(entry).lower()
    q = query.strip().lower()
    if not q:
        return 0

    total = 0
    try:
        total += len(re.findall(query, blob, re.IGNORECASE))
    except re.error:
        pass  # not a valid regex; keyword scoring below still applies

    tokens = re.findall(r"[a-z0-9]+", q)
    total += sum(blob.count(t) for t in tokens)
    return total


def search_catalog(entries: list[dict[str, Any]], query: str, limit: int = 5) -> list[dict[str, Any]]:
    scored = [(score(e, query), e) for e in entries]
    scored = [(s, e) for s, e in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [e for _, e in scored[:limit]]
