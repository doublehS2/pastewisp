"""Move a GTK 4 window to an absolute X11 screen coordinate.

GTK 4 doesn't expose a window-positioning API, so we grab the underlying
X11 surface XID and use Xlib's ``XConfigureWindow`` directly. We also
clamp the position to the surrounding monitor so the popup never lands
off-screen.
"""

from __future__ import annotations

import logging
from typing import Optional

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # type: ignore
    HAS_GDK_X11 = True
except (ValueError, ImportError):
    HAS_GDK_X11 = False
    GdkX11 = None  # type: ignore[assignment]

from Xlib import display as xdisplay
from Xlib.error import XError

log = logging.getLogger(__name__)

_MARGIN = 12  # px of breathing room from monitor edges


def _surface_xid(window: Gtk.Window) -> Optional[int]:
    if not HAS_GDK_X11:
        return None
    surface = window.get_surface()
    if surface is None:
        return None
    if not isinstance(surface, GdkX11.X11Surface):
        return None
    try:
        return int(surface.get_xid())
    except Exception:  # noqa: BLE001
        return None


def _monitor_geometry_for(window: Gtk.Window, x: int, y: int) -> Optional[Gdk.Rectangle]:
    display = window.get_display() or Gdk.Display.get_default()
    if display is None:
        return None
    monitors = display.get_monitors()
    # Iterate the Gio.ListModel of monitors and find the one that contains (x, y).
    for i in range(monitors.get_n_items()):
        m = monitors.get_item(i)
        if m is None:
            continue
        g: Gdk.Rectangle = m.get_geometry()
        if g.x <= x < g.x + g.width and g.y <= y < g.y + g.height:
            return g
    # Nothing contains the point — fall back to the first monitor.
    if monitors.get_n_items() > 0:
        return monitors.get_item(0).get_geometry()
    return None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def move_to_screen_coords(window: Gtk.Window, x: int, y: int) -> bool:
    """Move ``window`` to absolute screen coordinates ``(x, y)``.

    The position is clamped to the surrounding monitor so the popup
    doesn't end up partially off-screen.
    """
    xid = _surface_xid(window)
    if xid is None:
        log.debug("no X11 surface XID — positioning skipped")
        return False

    # Window dimensions — used to clamp. Fall back to the default size if the
    # window hasn't been measured yet.
    width = window.get_width() or window.get_default_size().width or 560
    height = window.get_height() or window.get_default_size().height or 480

    geom = _monitor_geometry_for(window, x, y)
    if geom is not None:
        x = _clamp(x, geom.x + _MARGIN, geom.x + geom.width - width - _MARGIN)
        y = _clamp(y, geom.y + _MARGIN, geom.y + geom.height - height - _MARGIN)

    try:
        d = xdisplay.Display()
        xwin = d.create_resource_object("window", xid)
        xwin.configure(x=int(x), y=int(y))
        d.flush()
        d.close()
        log.info("moved window xid=0x%x to (%d, %d)", xid, x, y)
        return True
    except XError as e:
        log.warning("XConfigure failed: %s", e)
        return False
