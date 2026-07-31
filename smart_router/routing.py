"""Routing layer: config schema (load/save) + deterministic route ranking.

Pure stdlib module (no ``mcp`` import) mirroring ``registry``/``migrate``: the
server and CLI are thin wrappers over this. The ``routing`` block lives in the
JSON registry next to ``mcp_servers`` / ``skill_dirs`` / ``migrations``.
"""
from .registry import save_registry

DEFAULT_ROUTING = {"mode": "auto", "priority_order": [], "exclude": [], "rules": []}


# --------------------------------------------------------------------------- #
# Config schema: load / save
# --------------------------------------------------------------------------- #
def load_routing(reg) -> dict:
    """Return the registry's routing block with defaults filled (no aliasing)."""
    raw = getattr(reg, "routing", None) or {}
    return {
        "mode": raw.get("mode", "auto"),
        "priority_order": list(raw.get("priority_order", [])),
        "exclude": list(raw.get("exclude", [])),
        "rules": [_copy_rule(r) for r in raw.get("rules", [])],
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
