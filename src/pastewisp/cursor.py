"""Decide where the popup should appear on screen.

Priority order:
1. AT-SPI text caret (GNOME Terminal, GTK-native apps — most precise).
2. A sensible anchor inside the active X11 window (terminals that render
   themselves like Warp/Kitty/Alacritty, or apps like Chrome whose a11y tree
   is essentially empty by default).
3. Mouse pointer (last-resort fallback when no active window is known).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import gi

try:
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi  # type: ignore
    HAS_ATSPI = True
except (ValueError, ImportError):
    HAS_ATSPI = False
    Atspi = None  # type: ignore[assignment]

from Xlib import display as xdisplay
from Xlib.error import XError

from .active_window.base import ActiveWindow, ActiveWindowProbe

log = logging.getLogger(__name__)


def _has_state(accessible, state) -> bool:
    try:
        return accessible.get_state_set().contains(state)
    except Exception:
        return False


# Some implementations report bogus caret coordinates like (0, 0) or large
# negatives — treat anything below this as invalid.
_MIN_VALID_COORD = -100_000
_MAX_DEPTH = 12
_MAX_CHILDREN_PER_NODE = 80


@dataclass(frozen=True)
class Position:
    x: int
    y: int
    # For caret-based positions this is the glyph height (used as line spacing
    # when placing the popup below the caret). Zero for other sources.
    char_height: int = 0
    source: str = "mouse"  # 'caret' | 'active-window' | 'mouse'


class CursorProbe:
    def __init__(self, active_window: Optional[ActiveWindowProbe] = None) -> None:
        self._xdisplay = xdisplay.Display()
        self._root = self._xdisplay.screen().root
        self._atspi_inited = False
        self.active_window = active_window

    def close(self) -> None:
        try:
            self._xdisplay.close()
        except Exception:
            pass

    def current(self) -> Optional[Position]:
        # By user request the popup always tracks the mouse. The AT-SPI caret
        # and active-window anchor implementations below are kept intact so
        # the strategy can be reinstated if we want to bring it back later.
        return self._mouse_position()

    def _active_window_now(self) -> Optional[ActiveWindow]:
        if self.active_window is None:
            return None
        try:
            return self.active_window.current()
        except Exception:  # noqa: BLE001
            log.debug("active_window current() failed", exc_info=True)
            return None

    def _anchor_in_window(self, win: ActiveWindow) -> Position:
        # Guess "roughly where the user is typing" inside the active window.
        # Most terminals put the prompt near the bottom; text editors and
        # browsers accept input in the main content area. A point indented
        # from the left edge and slightly above the bottom is a decent
        # default. The popup will be placed above this anchor and the
        # positioning module clamps it inside the monitor.
        anchor_x = win.x + 60
        anchor_y = win.y + win.height - 40
        log.info(
            "active-window anchor: %s @ window(x=%d y=%d %dx%d) -> anchor(%d,%d)",
            win.wm_class_combined or "?", win.x, win.y, win.width, win.height, anchor_x, anchor_y,
        )
        return Position(x=anchor_x, y=anchor_y, char_height=0, source="active-window")

    # ───────── caret ─────────

    def _ensure_atspi(self) -> bool:
        if not HAS_ATSPI:
            return False
        if self._atspi_inited:
            return True
        try:
            Atspi.init()
            self._atspi_inited = True
            return True
        except Exception as e:  # noqa: BLE001
            log.debug("Atspi.init failed: %s", e)
            return False

    def _caret_position(self) -> Optional[Position]:
        if not self._ensure_atspi():
            return None
        try:
            desktop = Atspi.get_desktop(0)
        except Exception as e:  # noqa: BLE001
            log.debug("Atspi.get_desktop failed: %s", e)
            return None

        # Step 1: collect every active frame (= a window the user is looking at).
        try:
            n_apps = desktop.get_child_count()
        except Exception:
            return None
        active_frames: list = []
        for i in range(n_apps):
            try:
                app = desktop.get_child_at_index(i)
            except Exception:
                continue
            if app is None:
                continue
            try:
                m = app.get_child_count()
            except Exception:
                continue
            for j in range(m):
                try:
                    frame = app.get_child_at_index(j)
                except Exception:
                    continue
                if frame is None:
                    continue
                if _has_state(frame, Atspi.StateType.ACTIVE):
                    active_frames.append(frame)
        log.debug("found %d active frames", len(active_frames))

        # Step 2: search each active frame for a FOCUSED widget that supports
        # Text and has a valid caret offset.
        for frame in active_frames:
            pos = self._descend(frame, depth=0)
            if pos is not None:
                return pos
        return None

    def _descend(self, accessible, depth: int) -> Optional[Position]:
        if accessible is None or depth > _MAX_DEPTH:
            return None
        # Try this node first if it's focused and exposes text.
        if _has_state(accessible, Atspi.StateType.FOCUSED):
            pos = self._caret_from(accessible)
            if pos is not None:
                return pos
        try:
            n = accessible.get_child_count()
        except Exception:
            return None
        for i in range(min(n, _MAX_CHILDREN_PER_NODE)):
            try:
                child = accessible.get_child_at_index(i)
            except Exception:
                continue
            pos = self._descend(child, depth + 1)
            if pos is not None:
                return pos
        return None

    def _caret_from(self, accessible) -> Optional[Position]:
        # No caret if the node doesn't implement the Text interface.
        try:
            text_iface = accessible.get_text_iface()
        except Exception:
            text_iface = None
        if text_iface is None:
            return None
        try:
            caret_offset = text_iface.get_caret_offset()
        except Exception:
            return None
        if caret_offset < 0:
            return None
        try:
            ext = text_iface.get_character_extents(caret_offset, Atspi.CoordType.SCREEN)
        except Exception:
            return None
        if ext is None:
            return None
        x, y, w, h = int(ext.x), int(ext.y), int(ext.width), int(ext.height)
        if x <= _MIN_VALID_COORD or y <= _MIN_VALID_COORD:
            return None
        # Zero height can mean an empty-line caret — coordinates are still valid.
        log.debug("caret extents x=%d y=%d w=%d h=%d", x, y, w, h)
        return Position(x=x, y=y, char_height=max(0, h), source="caret")

    # ───────── mouse ─────────

    def _mouse_position(self) -> Position:
        try:
            p = self._root.query_pointer()
            return Position(x=int(p.root_x), y=int(p.root_y), char_height=0, source="mouse")
        except XError as e:
            log.debug("query_pointer failed: %s", e)
            # No idea where the cursor is — let the WM place us at (0, 0).
            return Position(x=0, y=0, char_height=0, source="mouse")
