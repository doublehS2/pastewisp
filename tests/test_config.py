from __future__ import annotations

from pathlib import Path

from pastewisp import config


def test_load_creates_default_when_missing(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    cfg = config.load(cfg_path)
    assert cfg.general.history_limit == 500
    assert cfg.general.hotkey == "<Control><Shift>v"
    assert cfg.general.auto_paste is True
    assert "keepassxc" in cfg.exclude.apps
    assert cfg_path.exists()


def test_save_then_load_roundtrip(tmp_path: Path):
    cfg_path = tmp_path / "config.toml"
    original = config.Config().with_general(history_limit=42, hotkey="<Super>v")
    config.save(original, cfg_path)
    loaded = config.load(cfg_path)
    assert loaded.general.history_limit == 42
    assert loaded.general.hotkey == "<Super>v"


def test_with_helpers_are_immutable():
    base = config.Config()
    updated = base.with_storage(keep_images_days=7)
    assert base.storage.keep_images_days == 30
    assert updated.storage.keep_images_days == 7


def test_from_dict_with_partial_data():
    cfg = config.Config.from_dict({"general": {"history_limit": 100}})
    assert cfg.general.history_limit == 100
    assert cfg.general.auto_paste is True  # default preserved
    assert cfg.exclude.apps == config.DEFAULT_EXCLUDE_APPS
