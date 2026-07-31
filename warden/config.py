"""Loads warden config: downstream MCP servers + skill directories.

READ resolution order (``resolve_config_path``):

1. an explicit ``path`` argument, else
2. the ``WARDEN_CONFIG`` environment variable, else
3. ``config_home()/config.json`` if it exists, else
4. ``warden.config.json`` in the current working directory.

WRITE resolution (``writable_config_path``) always targets ``config_home()``
(never CWD) so the registry persists to a stable home path across sessions.

``config_home()`` is ``$WARDEN_HOME`` if set, else ``~/.config/warden``.
"""
import json
import os
import pathlib
from typing import Any

DEFAULT_CONFIG_PATH = pathlib.Path("warden.config.json")


def config_home(env=None) -> pathlib.Path:
    env = os.environ if env is None else env
    override = env.get("WARDEN_HOME")
    if override:
        return pathlib.Path(override)
    return pathlib.Path("~/.config/warden").expanduser()


def resolve_config_path(path=None, env=None) -> pathlib.Path:
    env = os.environ if env is None else env
    if path is not None:
        return pathlib.Path(path)
    if env.get("WARDEN_CONFIG"):
        return pathlib.Path(env["WARDEN_CONFIG"])
    home_cfg = config_home(env) / "config.json"
    if home_cfg.exists():
        return home_cfg
    return DEFAULT_CONFIG_PATH


def writable_config_path(path=None, env=None) -> pathlib.Path:
    env = os.environ if env is None else env
    if path is not None:
        return pathlib.Path(path)
    if env.get("WARDEN_CONFIG"):
        return pathlib.Path(env["WARDEN_CONFIG"])
    return config_home(env) / "config.json"


def config_dir(path=None, env=None) -> pathlib.Path:
    return resolve_config_path(path, env).parent


def load_config(path=None) -> dict[str, Any]:
    resolved = resolve_config_path(path)
    if not resolved.exists():
        raise FileNotFoundError(
            f"warden config not found at '{resolved}'. Copy config.example.json to "
            "'warden.config.json', set WARDEN_CONFIG, or run `warden migrate` first."
        )
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"warden config at '{resolved}' must be a JSON object.")
    data.setdefault("mcp_servers", {})
    data.setdefault("skill_dirs", [])
    return data
