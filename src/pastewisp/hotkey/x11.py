from __future__ import annotations

import logging
import threading
from typing import Optional

from gi.repository import GLib
from Xlib import X, XK, display
from Xlib.error import BadAccess, XError

from .base import HotkeyCallback, HotkeySpec

log = logging.getLogger(__name__)

# Caps/Num/Scroll lock are irrelevant to the grab but the X server still
# requires the exact modifier mask to match — so we register every combination.
_IGNORED_MODS = [
    0,
    X.LockMask,                    # Caps Lock
    X.Mod2Mask,                    # Num Lock
    X.LockMask | X.Mod2Mask,
]


def _modifier_mask(modifiers) -> int:
    mask = 0
    if "ctrl" in modifiers:
        mask |= X.ControlMask
    if "shift" in modifiers:
        mask |= X.ShiftMask
    if "alt" in modifiers:
        mask |= X.Mod1Mask
    if "super" in modifiers:
        mask |= X.Mod4Mask
    return mask


def _keysym_for(key: str) -> int:
    # Single-character keys map directly via their ASCII value.
    if len(key) == 1:
        return XK.string_to_keysym(key)
    # Named keys like F1, space, Return.
    sym = XK.string_to_keysym(key)
    if sym:
        return sym
    # Common aliases.
    aliases = {"return": "Return", "enter": "Return", "esc": "Escape", "space": "space"}
    fallback = aliases.get(key.lower())
    if fallback:
        return XK.string_to_keysym(fallback)
    raise ValueError(f"unknown key name: {key!r}")


class X11HotkeyListener:
    """Runs XGrabKey in a background thread with its own X11 connection."""

    def __init__(self) -> None:
        self._display = display.Display()
        self._root = self._display.screen().root
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._spec: Optional[HotkeySpec] = None
        self._callback: Optional[HotkeyCallback] = None
        self._grabbed: list[tuple[int, int]] = []  # (keycode, modmask)
        self._lock = threading.Lock()

    # ───────── public ─────────

    def bind(self, spec: HotkeySpec, callback: HotkeyCallback) -> None:
        with self._lock:
            self._ungrab_locked()
            self._spec = spec
            self._callback = callback
            self._grab_locked(spec)

    def unbind(self) -> None:
        with self._lock:
            self._ungrab_locked()
            self._spec = None
            self._callback = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="pastewisp-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._ungrab_locked()
        try:
            self._display.close()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    # ───────── internals ─────────

    def _grab_locked(self, spec: HotkeySpec) -> None:
        sym = _keysym_for(spec.key)
        if not sym:
            log.error("could not resolve keysym for %r", spec.key)
            return
        keycode = self._display.keysym_to_keycode(sym)
        if keycode == 0:
            log.error("no keycode for keysym 0x%x (key=%r)", sym, spec.key)
            return
        base_mod = _modifier_mask(spec.modifiers)
        failures = 0
        for extra in _IGNORED_MODS:
            mask = base_mod | extra
            try:
                self._root.grab_key(
                    keycode,
                    mask,
                    1,  # owner_events
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                )
                self._grabbed.append((keycode, mask))
            except BadAccess:
                failures += 1
                log.warning(
                    "XGrabKey BadAccess for keycode=%d mask=0x%x — another app may already hold this combo",
                    keycode,
                    mask,
                )
            except XError as e:
                failures += 1
                log.warning("XGrabKey error: %s", e)
        self._display.sync()
        log.info("grabbed hotkey %s (keycode=%d, failures=%d)", spec, keycode, failures)

    def _ungrab_locked(self) -> None:
        for keycode, mask in self._grabbed:
            try:
                self._root.ungrab_key(keycode, mask)
            except XError:
                pass
        self._grabbed.clear()
        try:
            self._display.sync()
        except Exception:
            pass

    def _run(self) -> None:
        # next_event() blocks, so we poll pending_events() instead.
        while not self._stop_event.is_set():
            try:
                # Wake roughly every 50ms.
                if self._display.pending_events() == 0:
                    self._stop_event.wait(0.05)
                    continue
                event = self._display.next_event()
            except Exception as e:  # noqa: BLE001
                if self._stop_event.is_set():
                    return
                log.debug("hotkey loop error: %s", e)
                continue
            if event.type == X.KeyPress:
                cb = self._callback
                if cb is not None:
                    log.debug("hotkey pressed")
                    GLib.idle_add(_invoke, cb)


def _invoke(cb: HotkeyCallback) -> bool:
    try:
        cb()
    except Exception:  # noqa: BLE001
        log.exception("hotkey callback raised")
    return False  # one-shot
