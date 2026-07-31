"""Routing layer: config schema (load/save) + deterministic route ranking.

Pure stdlib module (no ``mcp`` import) mirroring ``registry``/``migrate``: the
server and CLI are thin wrappers over this. The ``routing`` block lives in the
JSON registry next to ``mcp_servers`` / ``skill_dirs`` / ``migrations``.
"""
import pathlib
from fnmatch import fnmatch

from .registry import save_registry
from .search import score

# Fixed, bounded boosts so a strong ``text_score`` still dominates; ties and
# near-ties are where the config decides (see plan "Decisions").
PRIORITY_BOOST_BASE = 3
CONTEXT_BOOST = 2

DEFAULT_ROUTING = {"mode": "auto", "priority_order": [], "exclude": [], "rules": []}


# --------------------------------------------------------------------------- #
# Config schema: load / save
# --------------------------------------------------------------------------- #
def load_routing(reg) -> dict:
    """Return the registry's routing block, validated and with defaults filled.

    A stored block is validated the same way ``save_routing`` validates on the
    write path: a corrupt hand-edited ``routing`` fails loudly with ``ValueError``
    (consistent with ``config.load_config`` rejecting a non-object config).
    """
    raw = getattr(reg, "routing", None) or {}
    return _validate_routing(raw)


def save_routing(reg, routing) -> None:
    """Validate ``routing``, store the normalized block on ``reg``, persist it."""
    block = _validate_routing(routing)
    reg.routing = block
    save_registry(reg)


def _copy_rule(rule) -> dict:
    out = {}
    if isinstance(rule, dict):
        for key in ("when", "prefer", "exclude"):
            if key in rule:
                out[key] = _deepish(rule[key])
    return out


def _deepish(value):
    if isinstance(value, dict):
        return {k: _deepish(v) for k, v in value.items()}
    if isinstance(value, list):
        return list(value)
    return value


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _normalize_ext(value):
    """Normalize an extension to 'lowercase, no leading dot' (e.g. '.TSX' -> 'tsx').

    Non-string input is returned unchanged so callers can degrade gracefully.
    """
    if not isinstance(value, str):
        return value
    return value.lstrip(".").lower()


def _validate_routing(routing) -> dict:
    if not isinstance(routing, dict):
        raise ValueError("routing block must be a JSON object")

    mode = routing.get("mode", "auto")
    if mode not in ("auto", "ask"):
        raise ValueError(f"routing.mode must be 'auto' or 'ask', got {mode!r}")

    for key in ("priority_order", "exclude"):
        val = routing.get(key, [])
        if not _is_str_list(val):
            raise ValueError(f"routing.{key} must be a list of strings")

    rules = routing.get("rules", [])
    if not isinstance(rules, list):
        raise ValueError("routing.rules must be a list")
    norm_rules = [_validate_rule(r, i) for i, r in enumerate(rules)]

    return {
        "mode": mode,
        "priority_order": list(routing.get("priority_order", [])),
        "exclude": list(routing.get("exclude", [])),
        "rules": norm_rules,
    }


def _validate_rule(rule, idx) -> dict:
    if not isinstance(rule, dict):
        raise ValueError(f"routing.rules[{idx}] must be an object")

    when = rule.get("when", {})
    if not isinstance(when, dict):
        raise ValueError(f"routing.rules[{idx}].when must be an object")
    if "extension" in when and not _is_str_list(when["extension"]):
        raise ValueError(f"routing.rules[{idx}].when.extension must be a list of strings")
    if "path_glob" in when and not isinstance(when["path_glob"], str):
        raise ValueError(f"routing.rules[{idx}].when.path_glob must be a string")

    for key in ("prefer", "exclude"):
        if key in rule and not _is_str_list(rule[key]):
            raise ValueError(f"routing.rules[{idx}].{key} must be a list of strings")

    out = _copy_rule(rule)
    if "extension" in out.get("when", {}):
        out["when"]["extension"] = [_normalize_ext(e) for e in out["when"]["extension"]]
    return out


# --------------------------------------------------------------------------- #
# Deterministic ranking
# --------------------------------------------------------------------------- #
def _context_extension(context):
    """Derive a normalized extension from ``context``.

    Prefers an explicit ``extension`` (any case, with or without a leading dot);
    falls back to the suffix of ``file_path``. Returns ``None`` when neither is
    present so extension rules simply do not match (graceful degrade).
    """
    ext = context.get("extension")
    if ext is None:
        file_path = context.get("file_path")
        if isinstance(file_path, str) and file_path:
            ext = pathlib.Path(file_path).suffix
    if ext is None:
        return None
    return _normalize_ext(ext)


def _rule_matches(rule, context) -> bool:
    """A rule matches when context has a listed extension or a glob-matching path."""
    if context is None:
        return False
    when = rule.get("when", {})
    exts = when.get("extension")
    if exts and _context_extension(context) in exts:
        return True
    glob = when.get("path_glob")
    file_path = context.get("file_path")
    if glob and file_path and fnmatch(file_path, glob):
        return True
    return False


def _priority_boost(name, priority_order) -> int:
    if name not in priority_order:
        return 0
    return max(1, PRIORITY_BOOST_BASE - priority_order.index(name))


def plan_route(catalog, task, context, routing, mode) -> dict:
    """Rank ``catalog`` entries for ``task`` under ``routing`` config.

    Pure. Returns the result shape documented in the plan (unit 2). Never
    executes anything.
    """
    priority_order = list(routing.get("priority_order", []))
    global_exclude = set(routing.get("exclude", []))
    rules = routing.get("rules", [])

    # Rules that apply for this context (skipped entirely when context is None).
    active_rules = [r for r in rules if _rule_matches(r, context)]
    rule_excluded = set()
    prefer_names = set()
    for r in active_rules:
        rule_excluded.update(r.get("exclude", []))
        prefer_names.update(r.get("prefer", []))

    excluded = global_exclude | rule_excluded

    candidates = []
    for entry in catalog:
        name = entry.get("name", "")
        if name in excluded:
            continue

        text = score(entry, task)
        pboost = _priority_boost(name, priority_order)
        cboost = CONTEXT_BOOST if name in prefer_names else 0
        total = text + pboost + cboost

        reasons = []
        if text:
            reasons.append(f"text score {text}")
        if pboost:
            reasons.append(f"priority_order #{priority_order.index(name) + 1} (+{pboost})")
        if cboost:
            reasons.append(f"rule prefer (+{cboost})")

        cand = {"type": entry.get("type"), "name": name, "score": total, "reasons": reasons}
        if entry.get("server") is not None:
            cand["server"] = entry.get("server")
        candidates.append(cand)

    # Keep only viable candidates (score > 0), like search_catalog.
    candidates = [c for c in candidates if c["score"] > 0]

    def _pindex(name):
        return priority_order.index(name) if name in priority_order else len(priority_order)

    candidates.sort(key=lambda c: (-c["score"], _pindex(c["name"]), c["name"]))

    single_option = len(candidates) == 1
    resolved_mode = mode if mode is not None else routing.get("mode", "auto")

    if single_option:
        chosen = candidates[0]
        result_candidates = candidates
    elif resolved_mode == "ask":
        chosen = None
        result_candidates = candidates[:5]
    else:  # auto (default for any non-"ask" resolved mode)
        chosen = candidates[0] if candidates else None
        result_candidates = candidates

    return {
        "mode": resolved_mode,
        "single_option": single_option,
        "chosen": chosen,
        "candidates": result_candidates,
    }


# --------------------------------------------------------------------------- #
# Human-readable rendering (dry inspection / CLI)
# --------------------------------------------------------------------------- #
def _render_candidate(cand) -> str:
    name = cand.get("name", "")
    server = cand.get("server")
    label = f"{server}/{name}" if server else name
    reasons = cand.get("reasons") or []
    tail = f" — {'; '.join(reasons)}" if reasons else ""
    return f"{label} (score {cand.get('score')}){tail}"


def render_route(result) -> str:
    """Render a ``plan_route`` result as a short human-readable summary.

    Pure and side-effect free; mirrors ``migrate.render_plan`` for dry inspection.
    """
    header = f"mode: {result.get('mode', 'auto')}"
    if result.get("single_option"):
        header += " (single option)"
    lines = [header]

    chosen = result.get("chosen")
    lines.append(f"chosen: {_render_candidate(chosen)}" if chosen else "chosen: none")

    candidates = result.get("candidates") or []
    if candidates:
        lines.append("candidates:")
        lines.extend(f"  {i}. {_render_candidate(c)}" for i, c in enumerate(candidates, 1))
    else:
        lines.append("candidates: none")

    return "\n".join(lines)
