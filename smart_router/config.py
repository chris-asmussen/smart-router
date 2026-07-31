"""Loads smart-router config: downstream MCP servers + skill directories.

READ resolution order (``resolve_config_path``):

1. an explicit ``path`` argument, else
2. the ``SMART_ROUTER_CONFIG`` environment variable, else
3. ``config_home()/config.json`` if it exists, else
4. ``smart-router.config.json`` in the current working directory.

WRITE resolution (``writable_config_path``) always targets ``config_home()``
(never CWD) so the registry persists to a stable home path across sessions.

``config_home()`` is ``$SMART_ROUTER_HOME`` if set, else ``~/.config/smart-router``.
"""
import json
import os
import pathlib
from typing import Any

DEFAULT_CONFIG_PATH = pathlib.Path("smart-router.config.json")


def config_home(env=None) -> pathlib.Path:
    env = os.environ if env is None else env
    override = env.get("SMART_ROUTER_HOME")
    if override:
        return pathlib.Path(override)
    return pathlib.Path("~/.config/smart-router").expanduser()


def resolve_config_path(path=None, env=None) -> pathlib.Path:
    env = os.environ if env is None else env
    if path is not None:
        return pathlib.Path(path)
    if env.get("SMART_ROUTER_CONFIG"):
        return pathlib.Path(env["SMART_ROUTER_CONFIG"])
    home_cfg = config_home(env) / "config.json"
    if home_cfg.exists():
        return home_cfg
    return DEFAULT_CONFIG_PATH


def writable_config_path(path=None, env=None) -> pathlib.Path:
    env = os.environ if env is None else env
    if path is not None:
        return pathlib.Path(path)
    if env.get("SMART_ROUTER_CONFIG"):
        return pathlib.Path(env["SMART_ROUTER_CONFIG"])
    return config_home(env) / "config.json"


def config_dir(path=None, env=None) -> pathlib.Path:
    return resolve_config_path(path, env).parent


def load_config(path=None) -> dict[str, Any]:
    resolved = resolve_config_path(path)
    if not resolved.exists():
        raise FileNotFoundError(
            f"smart-router config not found at '{resolved}'. Copy config.example.json to "
            "'smart-router.config.json', set SMART_ROUTER_CONFIG, or run `smart-router migrate` first."
        )
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"smart-router config at '{resolved}' must be a JSON object.")
    data.setdefault("mcp_servers", {})
    data.setdefault("skill_dirs", [])
    return data
