from __future__ import annotations

import pytest

from pastewisp.hotkey.base import parse_hotkey


def test_parse_ctrl_shift_v():
    spec = parse_hotkey("<Control><Shift>v")
    assert spec.modifiers == frozenset({"ctrl", "shift"})
    assert spec.key == "v"


def test_parse_super_v():
    assert parse_hotkey("<Super>v").modifiers == frozenset({"super"})


def test_parse_aliases():
    assert parse_hotkey("<Primary><Mod1>F1") == parse_hotkey("<Ctrl><Alt>F1")


def test_uppercase_key_normalized_to_lower():
    assert parse_hotkey("<Control>V").key == "v"


def test_named_key_preserved():
    assert parse_hotkey("<Control>space").key == "space"


def test_empty_raises():
    with pytest.raises(ValueError):
        parse_hotkey("")


def test_no_key_raises():
    with pytest.raises(ValueError):
        parse_hotkey("<Control><Shift>")


def test_unknown_modifier_raises():
    with pytest.raises(ValueError):
        parse_hotkey("<Hyper>v")
