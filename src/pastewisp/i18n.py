"""Lightweight i18n catalog for Pastewisp.

Two-language catalog (English, Korean) held in plain Python dicts. The
translation function ``t(key, **kwargs)`` looks up the active language and
applies ``str.format(**kwargs)``. Missing keys fall back to the key itself
(noisy enough to notice during development; safe at runtime).

Language is selected at startup via ``set_language()`` from
``config.general.language``. The value can be ``"auto"`` (detect from
``$LANGUAGE`` / ``$LC_ALL`` / ``$LC_MESSAGES`` / ``$LANG``), ``"en"``, or
``"ko"``.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

log = logging.getLogger(__name__)

SUPPORTED: tuple[str, ...] = ("en", "ko")
DEFAULT_LANGUAGE = "en"

EN: dict[str, str] = {
    # ── popup ──
    "popup.search_placeholder": "Search clipboard",
    "popup.empty.no_results.title": "No results",
    "popup.empty.no_results.hint_default": "Try a different query",
    "popup.empty.no_results.hint_with_query": "Nothing matches '{query}'",
    "popup.empty.history.title": "History is empty",
    "popup.empty.history.hint": "Copy something — it'll show up here",
    "popup.footer.alt.pin": "Pin",
    "popup.footer.alt.unpin": "Unpin",
    "popup.footer.alt.release": "release to exit",
    "popup.footer.normal.paste": "Paste",
    "popup.footer.normal.select": "Select",
    "popup.footer.normal.pin_mode": "Pin mode",
    "popup.footer.close": "Close",
    "popup.image_meta": "Image · {w} × {h}",
    # ── preferences ──
    "prefs.title": "Pastewisp — Preferences",
    "prefs.hotkey": "Popup hotkey",
    "prefs.hotkey.change": "Change",
    "prefs.hotkey.cancel": "Cancel",
    "prefs.hotkey.capture": "Press a shortcut… (Esc to cancel)",
    "prefs.history_size": "History size",
    "prefs.auto_paste": "Auto-paste on Enter",
    "prefs.keep_images_days": "Keep images for (days)",
    "prefs.excluded": "Excluded apps (WM_CLASS substring, one per line)",
    "prefs.language": "Language",
    "prefs.language.auto": "Auto (system)",
    "prefs.language.en": "English",
    "prefs.language.ko": "한국어",
    "prefs.hotkey_hint": "Hotkey syntax: <Control><Shift>v / <Super>v / <Control><Alt>F12 …",
    "prefs.cancel": "Cancel",
    "prefs.save": "Save",
    "prefs.save_failed": "Failed to save preferences",
    # ── tray ──
    "tray.open": "Open clipboard",
    "tray.preferences": "Preferences…",
    "tray.clear": "Clear history",
    "tray.quit": "Quit",
    # ── dialogs ──
    "dialog.clear.title": "Clear clipboard history?",
    "dialog.clear.detail": "This removes all unpinned items. Pinned items are kept.",
    "dialog.clear.confirm": "Clear",
    "dialog.cancel": "Cancel",
}

KO: dict[str, str] = {
    # ── popup ──
    "popup.search_placeholder": "클립보드 검색",
    "popup.empty.no_results.title": "검색 결과 없음",
    "popup.empty.no_results.hint_default": "다른 검색어로 시도해 보세요",
    "popup.empty.no_results.hint_with_query": "'{query}'과(와) 일치하는 항목이 없습니다",
    "popup.empty.history.title": "기록이 비어 있습니다",
    "popup.empty.history.hint": "무언가를 복사하면 여기에 나타납니다",
    "popup.footer.alt.pin": "고정",
    "popup.footer.alt.unpin": "고정 해제",
    "popup.footer.alt.release": "놓으면 종료",
    "popup.footer.normal.paste": "붙여넣기",
    "popup.footer.normal.select": "선택",
    "popup.footer.normal.pin_mode": "고정 모드",
    "popup.footer.close": "닫기",
    "popup.image_meta": "이미지 · {w} × {h}",
    # ── preferences ──
    "prefs.title": "Pastewisp — 환경설정",
    "prefs.hotkey": "팝업 단축키",
    "prefs.hotkey.change": "변경",
    "prefs.hotkey.cancel": "취소",
    "prefs.hotkey.capture": "단축키를 누르세요… (Esc로 취소)",
    "prefs.history_size": "기록 크기",
    "prefs.auto_paste": "Enter 키로 자동 붙여넣기",
    "prefs.keep_images_days": "이미지 보관 기간 (일)",
    "prefs.excluded": "제외할 앱 (WM_CLASS 부분 일치, 한 줄에 하나)",
    "prefs.language": "언어",
    "prefs.language.auto": "자동 (시스템)",
    "prefs.language.en": "English",
    "prefs.language.ko": "한국어",
    "prefs.hotkey_hint": "단축키 형식: <Control><Shift>v / <Super>v / <Control><Alt>F12 …",
    "prefs.cancel": "취소",
    "prefs.save": "저장",
    "prefs.save_failed": "환경설정 저장에 실패했습니다",
    # ── tray ──
    "tray.open": "클립보드 열기",
    "tray.preferences": "환경설정…",
    "tray.clear": "기록 지우기",
    "tray.quit": "종료",
    # ── dialogs ──
    "dialog.clear.title": "클립보드 기록을 지울까요?",
    "dialog.clear.detail": "고정되지 않은 모든 항목이 삭제됩니다. 고정된 항목은 유지됩니다.",
    "dialog.clear.confirm": "지우기",
    "dialog.cancel": "취소",
}

CATALOGS: dict[str, dict[str, str]] = {"en": EN, "ko": KO}

_current: str = DEFAULT_LANGUAGE


def _match_token(token: str) -> str | None:
    """Map a locale token (e.g. ``ko_KR.UTF-8``) to a supported code, or None."""
    if not token:
        return None
    code = token.strip().lower()
    if code.startswith("ko"):
        return "ko"
    if code.startswith("en"):
        return "en"
    return None


def detect_from_env(env: dict[str, str] | None = None) -> str:
    """Pick a supported language code from locale-related env vars.

    Probes LANGUAGE, LC_ALL, LC_MESSAGES, LANG in that order. Returns the
    first supported token (e.g. ``"ko_KR.UTF-8"`` → ``"ko"``). Tokens for
    unsupported languages are skipped so a list like ``fr_FR:ko_KR`` still
    resolves to ``"ko"``. Falls back to English.
    """
    e = os.environ if env is None else env
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        raw = e.get(var)
        if not raw:
            continue
        # LANGUAGE can be colon-separated priority list.
        for token in raw.split(":"):
            matched = _match_token(token)
            if matched is not None:
                return matched
    return DEFAULT_LANGUAGE


def resolve(lang: str) -> str:
    """Resolve a config value (``'auto' | 'en' | 'ko'``) to a concrete code."""
    code = (lang or "").strip().lower()
    if code == "auto" or not code:
        return detect_from_env()
    if code in SUPPORTED:
        return code
    return DEFAULT_LANGUAGE


def set_language(lang: str) -> str:
    """Set the active language. Accepts ``'auto'``, ``'en'``, ``'ko'``.

    Returns the concrete code that ended up active.
    """
    global _current
    _current = resolve(lang)
    return _current


def current_language() -> str:
    return _current


def t(key: str, /, **kwargs: object) -> str:
    """Look up ``key`` in the active catalog and apply ``.format(**kwargs)``.

    Missing keys log a warning and return the key itself so the UI keeps
    working even if a string is added in code but not in a catalog.
    """
    catalog = CATALOGS.get(_current, EN)
    template = catalog.get(key)
    if template is None:
        # Fall back to English if the active language is missing this key.
        template = EN.get(key)
    if template is None:
        log.warning("i18n: missing key %r", key)
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError) as e:
        log.warning("i18n: format failed for %r (%s): %s", key, kwargs, e)
        return template


def all_keys() -> Iterable[str]:
    return EN.keys()
