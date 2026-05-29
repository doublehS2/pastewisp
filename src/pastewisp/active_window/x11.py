from __future__ import annotations

import logging
import threading
from typing import Optional

from Xlib import X, display
from Xlib.error import XError

from .base import ActiveWindow

log = logging.getLogger(__name__)


class X11ActiveWindowProbe:
    """Look up the focused window via `_NET_ACTIVE_WINDOW`.

    A lock guards each call so the probe can be shared across threads.
    """

    def __init__(self) -> None:
        self._display = display.Display()
        self._root = self._display.screen().root
        self._atom_active = self._display.intern_atom("_NET_ACTIVE_WINDOW")
        self._atom_name = self._display.intern_atom("_NET_WM_NAME")
        self._atom_utf8 = self._display.intern_atom("UTF8_STRING")
        self._lock = threading.Lock()

    def current(self) -> Optional[ActiveWindow]:
        with self._lock:
            try:
                return self._read_locked()
            except XError as e:  # e.g. the window vanished between calls
                log.debug("active_window read failed: %s", e)
                return None

    def _read_locked(self) -> Optional[ActiveWindow]:
        prop = self._root.get_full_property(self._atom_active, X.AnyPropertyType)
        if prop is None or not prop.value:
            return None
        try:
            window_id = int(prop.value[0])
        except (IndexError, TypeError):
            return None
        if window_id == 0:
            return None
        win = self._display.create_resource_object("window", window_id)
        wm_class_instance: Optional[str] = None
        wm_class: Optional[str] = None
        try:
            wm = win.get_wm_class()
            if wm:
                wm_class_instance, wm_class = wm[0], wm[1]
        except XError:
            pass
        title: Optional[str] = None
        try:
            name_prop = win.get_full_property(self._atom_name, self._atom_utf8)
            if name_prop and name_prop.value:
                title = name_prop.value.decode("utf-8", errors="replace")
            else:
                t = win.get_wm_name()
                if isinstance(t, bytes):
                    title = t.decode("utf-8", errors="replace")
                elif isinstance(t, str):
                    title = t
        except XError:
            pass
        # Window geometry: get_geometry() returns coordinates relative to the
        # parent, so we translate to the root to get absolute screen coordinates.
        x, y, width, height = 0, 0, 0, 0
        try:
            geom = win.get_geometry()
            width = int(geom.width)
            height = int(geom.height)
            coord = self._root.translate_coords(win, 0, 0)
            x = int(coord.x)
            y = int(coord.y)
        except XError as e:
            log.debug("active window geom failed: %s", e)
        return ActiveWindow(
            window_id=window_id,
            wm_class_instance=wm_class_instance,
            wm_class=wm_class,
            title=title,
            x=x, y=y, width=width, height=height,
        )

    def close(self) -> None:
        try:
            self._display.close()
        except Exception:
            pass
