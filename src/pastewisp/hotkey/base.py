from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


@dataclass(frozen=True)
class HotkeySpec:
    """Platform-neutral hotkey representation.

    modifiers: a subset of {"ctrl", "shift", "alt", "super"}.
    key: a single lowercase letter or a named key like 'space' or 'F1'.
    """

    modifiers: frozenset[str]
    key: str

    def __post_init__(self) -> None:
        bad = self.modifiers - {"ctrl", "shift", "alt", "super"}
        if bad:
            raise ValueError(f"unknown modifiers: {bad}")
        if not self.key:
            raise ValueError("hotkey key must be non-empty")


_MOD_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "ctrl": "ctrl",
    "primary": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "mod1": "alt",
    "meta": "alt",
    "super": "super",
    "mod4": "super",
    "win": "super",
}

_TOKEN_RE = re.compile(r"<([^<>]+)>|([^<>\s]+)")


def parse_hotkey(spec: str) -> HotkeySpec:
    """Parse a GTK-style hotkey string such as `<Control><Shift>v`."""
    if not spec or not spec.strip():
        raise ValueError("empty hotkey spec")
    modifiers: set[str] = set()
    key: Optional[str] = None
    for m in _TOKEN_RE.finditer(spec.strip()):
        mod_tok, key_tok = m.group(1), m.group(2)
        if mod_tok is not None:
            normalized = _MOD_ALIASES.get(mod_tok.lower())
            if normalized is None:
                raise ValueError(f"unknown modifier: {mod_tok}")
            modifiers.add(normalized)
        elif key_tok is not None:
            if key is not None:
                raise ValueError(f"multiple keys in spec: {spec!r}")
            key = key_tok
    if key is None:
        raise ValueError(f"no key in spec: {spec!r}")
    # Normalize single ASCII letters to lowercase for consistency.
    if len(key) == 1 and key.isalpha():
        key = key.lower()
    return HotkeySpec(modifiers=frozenset(modifiers), key=key)


HotkeyCallback = Callable[[], None]


class HotkeyListener(Protocol):
    def bind(self, spec: HotkeySpec, callback: HotkeyCallback) -> None:
        ...

    def unbind(self) -> None:
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...
