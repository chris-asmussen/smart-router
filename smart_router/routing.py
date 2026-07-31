"""Routing layer: config schema (load/save) + deterministic route ranking.

Pure stdlib module (no ``mcp`` import) mirroring ``registry``/``migrate``: the
server and CLI are thin wrappers over this. The ``routing`` block lives in the
JSON registry next to ``mcp_servers`` / ``skill_dirs`` / ``migrations``.
"""
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
    """Return the registry's routing block with defaults filled (no aliasing)."""
    raw = getattr(reg, "routing", None) or {}
    return {
        "mode": raw.get("mode", DEFAULT_ROUTING["mode"]),
        "priority_order": list(raw.get("priority_order", DEFAULT_ROUTING["priority_order"])),
        "exclude": list(raw.get("exclude", DEFAULT_ROUTING["exclude"])),
        "rules": [_copy_rule(r) for r in raw.get("rules", DEFAULT_ROUTING["rules"])],
    }


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

    return _copy_rule(rule)


# --------------------------------------------------------------------------- #
# Deterministic ranking
# --------------------------------------------------------------------------- #
def _rule_matches(rule, context) -> bool:
    """A rule matches when context has a listed extension or a glob-matching path."""
    if context is None:
        return False
    when = rule.get("when", {})
    exts = when.get("extension")
    if exts and context.get("extension") in exts:
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

    single_option = sum(1 for c in candidates if c["score"] > 0) == 1
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
