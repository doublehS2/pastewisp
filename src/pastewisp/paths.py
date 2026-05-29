from __future__ import annotations

import os
from pathlib import Path

from . import APP_NAME


def _xdg(env: str, default_rel: str) -> Path:
    value = os.environ.get(env)
    if value:
        return Path(value)
    return Path.home() / default_rel


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / APP_NAME


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / APP_NAME


def cache_dir() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


def db_file() -> Path:
    return data_dir() / "db.sqlite"


def systemd_user_unit() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "systemd" / "user" / f"{APP_NAME}.service"


def ensure_dirs() -> None:
    for path in (config_dir(), data_dir(), cache_dir()):
        path.mkdir(parents=True, exist_ok=True)
