from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import tomli_w

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from . import paths

DEFAULT_EXCLUDE_APPS = [
    "keepassxc",
    "1password",
    "bitwarden",
    "gnome-keyring",
]


def _coerce_language(value: Any) -> str:
    code = str(value).strip().lower() if value is not None else "auto"
    return code if code in ("auto", "en", "ko") else "auto"


VALID_LANGUAGES = ("auto", "en", "ko")


@dataclass(frozen=True)
class GeneralConfig:
    history_limit: int = 500
    hotkey: str = "<Control><Shift>v"
    auto_paste: bool = True
    start_minimized_to_tray: bool = True
    language: str = "auto"


@dataclass(frozen=True)
class StorageConfig:
    keep_images_days: int = 30
    max_image_bytes: int = 4 * 1024 * 1024  # 4 MiB


@dataclass(frozen=True)
class ExcludeConfig:
    apps: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE_APPS))


@dataclass(frozen=True)
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    exclude: ExcludeConfig = field(default_factory=ExcludeConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "general": asdict(self.general),
            "storage": asdict(self.storage),
            "exclude": asdict(self.exclude),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Config":
        g = data.get("general", {}) or {}
        s = data.get("storage", {}) or {}
        e = data.get("exclude", {}) or {}
        return Config(
            general=GeneralConfig(
                history_limit=int(g.get("history_limit", 500)),
                hotkey=str(g.get("hotkey", "<Control><Shift>v")),
                auto_paste=bool(g.get("auto_paste", True)),
                start_minimized_to_tray=bool(g.get("start_minimized_to_tray", True)),
                language=_coerce_language(g.get("language", "auto")),
            ),
            storage=StorageConfig(
                keep_images_days=int(s.get("keep_images_days", 30)),
                max_image_bytes=int(s.get("max_image_bytes", 4 * 1024 * 1024)),
            ),
            exclude=ExcludeConfig(
                apps=[str(x) for x in e.get("apps", DEFAULT_EXCLUDE_APPS)],
            ),
        )

    def with_general(self, **kwargs: Any) -> "Config":
        return replace(self, general=replace(self.general, **kwargs))

    def with_storage(self, **kwargs: Any) -> "Config":
        return replace(self, storage=replace(self.storage, **kwargs))

    def with_exclude(self, **kwargs: Any) -> "Config":
        return replace(self, exclude=replace(self.exclude, **kwargs))


def load(path: Path | None = None) -> Config:
    path = path or paths.config_file()
    if not path.exists():
        cfg = Config()
        save(cfg, path)
        return cfg
    with path.open("rb") as fp:
        data = tomllib.load(fp)
    return Config.from_dict(data)


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = cfg.to_dict()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as fp:
        tomli_w.dump(payload, fp)
    tmp.replace(path)
