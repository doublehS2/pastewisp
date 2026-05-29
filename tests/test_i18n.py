from __future__ import annotations

import pytest

from pastewisp import i18n
from pastewisp.config import Config, GeneralConfig


@pytest.fixture(autouse=True)
def reset_language():
    """Ensure each test starts from the module default."""
    previous = i18n.current_language()
    yield
    i18n.set_language(previous)


def test_en_and_ko_have_identical_keys():
    en_keys = set(i18n.EN.keys())
    ko_keys = set(i18n.KO.keys())
    missing_in_ko = en_keys - ko_keys
    extra_in_ko = ko_keys - en_keys
    assert not missing_in_ko, f"keys missing from KO catalog: {sorted(missing_in_ko)}"
    assert not extra_in_ko, f"keys missing from EN catalog: {sorted(extra_in_ko)}"


def test_set_language_explicit_codes():
    assert i18n.set_language("en") == "en"
    assert i18n.t("popup.search_placeholder") == "Search clipboard"
    assert i18n.set_language("ko") == "ko"
    assert i18n.t("popup.search_placeholder") == "클립보드 검색"


def test_unknown_code_falls_back_to_default():
    assert i18n.set_language("fr") == "en"


def test_set_language_auto_uses_env(monkeypatch):
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")
    monkeypatch.delenv("LANGUAGE", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    assert i18n.set_language("auto") == "ko"

    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.set_language("auto") == "en"


def test_detect_from_env_priority(monkeypatch):
    # LANGUAGE wins over LANG.
    monkeypatch.setenv("LANGUAGE", "ko_KR")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    assert i18n.detect_from_env() == "ko"


def test_detect_from_env_handles_colon_list(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "fr_FR:ko_KR:en_US")
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    # First supported entry wins (fr is unsupported, so ko).
    assert i18n.detect_from_env() == "ko"


def test_detect_from_env_no_locale_vars(monkeypatch):
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert i18n.detect_from_env() == "en"


def test_t_format_substitution():
    i18n.set_language("en")
    msg = i18n.t("popup.empty.no_results.hint_with_query", query="abc")
    assert "abc" in msg

    i18n.set_language("ko")
    msg = i18n.t("popup.empty.no_results.hint_with_query", query="abc")
    assert "abc" in msg


def test_t_image_meta_format():
    i18n.set_language("en")
    assert i18n.t("popup.image_meta", w=1920, h=1080) == "Image · 1920 × 1080"
    i18n.set_language("ko")
    assert i18n.t("popup.image_meta", w=1920, h=1080) == "이미지 · 1920 × 1080"


def test_missing_key_returns_key_itself(caplog):
    i18n.set_language("en")
    with caplog.at_level("WARNING"):
        result = i18n.t("does.not.exist")
    assert result == "does.not.exist"


def test_missing_key_in_ko_falls_back_to_en(monkeypatch):
    # Temporarily remove a key from KO to simulate a partial translation.
    key = "popup.search_placeholder"
    monkeypatch.delitem(i18n.KO, key, raising=True)
    i18n.set_language("ko")
    # Should not crash; falls back to EN string.
    assert i18n.t(key) == i18n.EN[key]


def test_config_round_trip_includes_language():
    cfg = Config().with_general(language="ko")
    data = cfg.to_dict()
    assert data["general"]["language"] == "ko"
    restored = Config.from_dict(data)
    assert restored.general.language == "ko"


def test_config_invalid_language_coerces_to_auto():
    restored = Config.from_dict({"general": {"language": "klingon"}})
    assert restored.general.language == "auto"


def test_config_default_language_is_auto():
    assert GeneralConfig().language == "auto"
