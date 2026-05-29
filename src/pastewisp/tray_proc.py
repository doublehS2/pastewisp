"""Tray-icon subprocess (GTK 3 + AyatanaAppIndicator3).

The main app uses GTK 4, but AyatanaAppIndicator3 only works with GTK 3,
so the tray runs in its own process and talks to the main app over D-Bus
using ``org.freedesktop.Application.ActivateAction``.
"""

from __future__ import annotations

import logging
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    HAS_APPINDICATOR = True
except (ValueError, ImportError):
    HAS_APPINDICATOR = False
    AppIndicator = None  # type: ignore[assignment]

from gi.repository import Gtk, Gio, GLib  # noqa: E402

from . import APP_ID, i18n  # noqa: E402

APP_PATH = "/" + APP_ID.replace(".", "/")

log = logging.getLogger(__name__)


def call_action(name: str) -> None:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(
            APP_ID,
            APP_PATH,
            "org.freedesktop.Application",
            "ActivateAction",
            GLib.Variant("(sava{sv})", (name, [], {})),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
        )
    except GLib.Error as e:
        log.warning("tray call_action(%s) failed: %s", name, e)


def _make_menu() -> Gtk.Menu:
    menu = Gtk.Menu()

    def item(label: str, action: str) -> Gtk.MenuItem:
        mi = Gtk.MenuItem(label=label)
        mi.connect("activate", lambda _w, a=action: call_action(a))
        menu.append(mi)
        return mi

    item(i18n.t("tray.open"), "show-popup")
    item(i18n.t("tray.preferences"), "show-preferences")
    menu.append(Gtk.SeparatorMenuItem())
    item(i18n.t("tray.clear"), "clear-history")
    item(i18n.t("tray.quit"), "quit")

    menu.show_all()
    return menu


def _parse_lang(argv: list[str]) -> str:
    for arg in argv:
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return "auto"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="tray: %(message)s")
    i18n.set_language(_parse_lang(sys.argv[1:]))
    # Translate SIGTERM/SIGINT into a graceful Gtk.main_quit.
    signal.signal(signal.SIGTERM, lambda *_: Gtk.main_quit())
    signal.signal(signal.SIGINT, lambda *_: Gtk.main_quit())

    if not HAS_APPINDICATOR:
        log.error("AyatanaAppIndicator3 typelib not available. "
                  "Install gir1.2-ayatanaappindicator3-0.1 via apt.")
        return 1

    indicator = AppIndicator.Indicator.new(
        APP_ID,
        "edit-paste",  # Themed icon name shipped with most icon sets.
        AppIndicator.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    indicator.set_title("Pastewisp")
    indicator.set_menu(_make_menu())
    log.info("tray indicator ready")
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
