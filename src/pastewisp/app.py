from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gio, GObject, Gtk  # noqa: E402

from . import APP_ID, config as cfg, i18n, paths
from .active_window.x11 import X11ActiveWindowProbe
from .cursor import CursorProbe
from .db import Database, Item
from .history import HistoryManager
from .hotkey.base import parse_hotkey
from .hotkey.x11 import X11HotkeyListener
from .paster.x11 import X11AutoPaster
from .ui.popup import PopupWindow
from .ui.preferences import PreferencesWindow
from .ui.tray import TrayManager
from .watcher import ClipboardWatcher

log = logging.getLogger(__name__)


class PastewispApp(Gtk.Application):
    __gtype_name__ = "PastewispApp"

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.config: cfg.Config = cfg.load()
        i18n.set_language(self.config.general.language)
        self.db: Optional[Database] = None
        self.history: Optional[HistoryManager] = None
        self.watcher: Optional[ClipboardWatcher] = None
        self.active_window: Optional[X11ActiveWindowProbe] = None
        self.hotkey: Optional[X11HotkeyListener] = None
        self.paster: Optional[X11AutoPaster] = None
        self.popup: Optional[PopupWindow] = None
        self.prefs: Optional[PreferencesWindow] = None
        self.tray: Optional[TrayManager] = None
        self.cursor: Optional[CursorProbe] = None
        self._prune_timer_id: Optional[int] = None

    # ───────── lifecycle ─────────

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        paths.ensure_dirs()
        self._register_actions()

    def do_activate(self) -> None:
        if self.db is None:
            self._init_components()
        # We don't open a window on first activate — this runs as a background
        # daemon. GtkApplication would normally quit when no windows remain,
        # so call hold() to keep it alive.
        self.hold()

    def do_shutdown(self) -> None:
        log.info("shutdown")
        if self._prune_timer_id is not None:
            GLib.source_remove(self._prune_timer_id)
            self._prune_timer_id = None
        if self.tray:
            self.tray.stop()
        if self.watcher:
            self.watcher.stop()
        if self.hotkey:
            self.hotkey.stop()
        if self.paster:
            self.paster.close()
        if self.active_window:
            self.active_window.close()
        if self.cursor:
            self.cursor.close()
        if self.db:
            self.db.close()
        Gtk.Application.do_shutdown(self)

    # ───────── init ─────────

    def _init_components(self) -> None:
        log.info("initializing components")
        self.db = Database()
        self.history = HistoryManager(self.db, self.config)
        try:
            self.active_window = X11ActiveWindowProbe()
        except Exception:  # noqa: BLE001
            log.exception("active_window init failed; source app tagging disabled")
            self.active_window = None
        self.watcher = ClipboardWatcher(self.history, active_window=self.active_window)
        self.watcher.start()

        try:
            self.cursor = CursorProbe(active_window=self.active_window)
        except Exception:  # noqa: BLE001
            log.exception("cursor probe init failed")
            self.cursor = None

        try:
            self.paster = X11AutoPaster()
        except Exception:  # noqa: BLE001
            log.exception("paster init failed; auto-paste disabled")
            self.paster = None

        self.hotkey = X11HotkeyListener()
        self._bind_hotkey(self.config.general.hotkey)
        self.hotkey.start()

        self.tray = TrayManager()
        self.tray.start()

        # Run prune (image expiry + size cap) once a minute.
        self._prune_timer_id = GLib.timeout_add_seconds(60, self._on_prune_tick)

    def _bind_hotkey(self, accel: str) -> None:
        if self.hotkey is None:
            return
        try:
            spec = parse_hotkey(accel)
        except ValueError as e:
            log.error("invalid hotkey %r: %s", accel, e)
            return
        self.hotkey.bind(spec, self._on_hotkey)

    def _on_hotkey(self) -> None:
        self.activate_action("show-popup", None)

    def _on_prune_tick(self) -> bool:
        if self.history:
            self.history.prune()
        return True

    # ───────── actions (D-Bus exposed) ─────────

    def _register_actions(self) -> None:
        for name, handler in (
            ("show-popup", self._action_show_popup),
            ("show-preferences", self._action_show_preferences),
            ("clear-history", self._action_clear_history),
            ("quit", self._action_quit),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    def _action_show_popup(self, _action, _param) -> None:
        if self.history is None:
            return
        # Compute the popup position before the popup steals focus — AT-SPI
        # caret detection is relative to the currently focused widget, so it
        # must run before present().
        position = None
        if self.cursor is not None:
            try:
                position = self.cursor.current()
            except Exception:  # noqa: BLE001
                log.exception("cursor probe failed")
        log.info("popup position: %s", position)
        if self.popup is None:
            self.popup = PopupWindow(
                self.history,
                on_select=self._on_popup_select,
                on_delete=self._on_popup_delete,
                on_pin_toggle=self._on_popup_pin_toggle,
            )
            self.add_window(self.popup)
        self.popup.reload_and_present(position=position)

    def _action_show_preferences(self, _action, _param) -> None:
        if self.prefs is None:
            self.prefs = PreferencesWindow(self.config, on_apply=self._on_prefs_apply)
            self.add_window(self.prefs)
        else:
            # Sync to the latest config in case it changed.
            self.prefs.config = self.config
        self.prefs.present()

    def _action_clear_history(self, _action, _param) -> None:
        if self.history is None:
            return
        # Destructive: confirm before clearing (req 7.7).
        dialog = Gtk.AlertDialog()
        dialog.set_modal(True)
        dialog.set_message(i18n.t("dialog.clear.title"))
        dialog.set_detail(i18n.t("dialog.clear.detail"))
        dialog.set_buttons([i18n.t("dialog.cancel"), i18n.t("dialog.clear.confirm")])
        dialog.set_cancel_button(0)
        dialog.set_default_button(0)
        parent = self.popup if (self.popup and self.popup.get_visible()) else None
        dialog.choose(parent, None, self._on_clear_confirmed)

    def _on_clear_confirmed(self, dialog: Gtk.AlertDialog, result) -> None:
        try:
            choice = dialog.choose_finish(result)
        except GLib.Error:
            # Dialog dismissed (Esc / closed) — treat as cancel.
            return
        if choice != 1 or self.history is None:
            return
        removed = self.history.clear_all(keep_pinned=True)
        log.info("cleared %d items (kept pinned)", removed)
        if self.popup and self.popup.get_visible():
            self.popup._reload()  # noqa: SLF001

    def _action_quit(self, _action, _param) -> None:
        self.quit()

    # ───────── popup callbacks ─────────

    def _on_popup_select(self, item: Item, paste: bool) -> None:
        if not self._copy_to_clipboard(item):
            return
        if self.history:
            self.history.touch(item.id)
        if paste and self.config.general.auto_paste and self.paster is not None:
            # Small delay so the clipboard set has time to propagate before
            # we synthesize Ctrl+V.
            GLib.timeout_add(60, self._safe_paste)

    def _safe_paste(self) -> bool:
        try:
            if self.paster:
                self.paster.paste()
        except Exception:  # noqa: BLE001
            log.exception("auto paste failed")
        return False

    def _copy_to_clipboard(self, item: Item) -> bool:
        display = Gdk.Display.get_default()
        if display is None:
            return False
        clipboard = display.get_clipboard()
        if item.is_text and item.text is not None:
            text = item.text
            data = text.encode("utf-8")
            provider = Gdk.ContentProvider.new_for_bytes(
                "text/plain;charset=utf-8",
                GLib.Bytes.new(data),
            )
            clipboard.set_content(provider)
            if self.watcher:
                from .db import text_hash
                self.watcher.mark_self_set(text_hash(text))
            return True
        if item.is_image and item.image_blob:
            try:
                gbytes = GLib.Bytes.new(item.image_blob)
                texture = Gdk.Texture.new_from_bytes(gbytes)
            except GLib.Error as e:
                log.warning("texture load failed: %s", e)
                return False
            value = GObject.Value(Gdk.Texture, texture)
            provider = Gdk.ContentProvider.new_for_value(value)
            clipboard.set_content(provider)
            if self.watcher:
                from .db import image_hash
                self.watcher.mark_self_set(image_hash(item.image_blob))
            return True
        return False

    def _on_popup_delete(self, item: Item) -> None:
        if self.history:
            self.history.delete(item.id)

    def _on_popup_pin_toggle(self, item: Item) -> None:
        if self.history:
            self.history.toggle_pin(item.id)

    def _on_prefs_apply(self, new_config: cfg.Config) -> None:
        old_hotkey = self.config.general.hotkey
        old_language = self.config.general.language
        self.config = new_config
        if self.history:
            self.history.replace_config(new_config)
        if new_config.general.hotkey != old_hotkey:
            self._bind_hotkey(new_config.general.hotkey)
        if new_config.general.language != old_language:
            i18n.set_language(new_config.general.language)
            # Tray subprocess has its own language state — restart it.
            if self.tray:
                self.tray.stop()
                self.tray = TrayManager()
                self.tray.start()
            # Discard cached popup/preferences windows so they're rebuilt
            # with the new language strings on next open.
            if self.popup is not None:
                try:
                    self.popup.destroy()
                except Exception:  # noqa: BLE001
                    pass
                self.popup = None
            if self.prefs is not None:
                try:
                    self.prefs.destroy()
                except Exception:  # noqa: BLE001
                    pass
                self.prefs = None


# ───────── CLI entry ─────────


def _self_check() -> int:
    import shutil

    print("=== pastewisp --self-check ===")
    print(f"DISPLAY={os.environ.get('DISPLAY', '<unset>')} "
          f"XDG_SESSION_TYPE={os.environ.get('XDG_SESSION_TYPE', '<unset>')}")
    rc = 0
    # DB
    try:
        paths.ensure_dirs()
        db = Database()
        print(f"[ok] db at {db.path}, {db.count()} items, fts={db._fts_available}")
        db.close()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] db: {e}")
        rc = 1
    # XTest
    try:
        p = X11AutoPaster()
        print("[ok] XTest paster")
        p.close()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] XTest: {e}")
        rc = 1
    # active window
    try:
        w = X11ActiveWindowProbe()
        cur = w.current()
        print(f"[ok] active window probe: {cur}")
        w.close()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] active window: {e}")
        rc = 1
    # AppIndicator typelib (used by the tray subprocess). We can't probe it
    # with require_version here because GTK 4 is already loaded — so just
    # check the typelib file directly.
    typelib_candidates = [
        "/usr/lib/x86_64-linux-gnu/girepository-1.0/AyatanaAppIndicator3-0.1.typelib",
        "/usr/lib/girepository-1.0/AyatanaAppIndicator3-0.1.typelib",
    ]
    if any(os.path.exists(p) for p in typelib_candidates):
        print("[ok] AyatanaAppIndicator3 typelib found")
    else:
        print("[warn] AyatanaAppIndicator3 typelib not found — tray icon may not appear")
        print("       apt: sudo apt install gir1.2-ayatanaappindicator3-0.1")
    # systemd unit registered?
    unit = paths.systemd_user_unit()
    if unit.exists():
        print(f"[ok] systemd unit installed at {unit}")
    else:
        print(f"[warn] systemd unit not installed (expected at {unit})")
    return rc


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if "--self-check" in argv:
        return _self_check()
    if "--version" in argv:
        from . import __version__
        print(__version__)
        return 0
    if "--quit" in argv:
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync(
                APP_ID,
                "/" + APP_ID.replace(".", "/"),
                "org.freedesktop.Application",
                "ActivateAction",
                GLib.Variant("(sava{sv})", ("quit", [], {})),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            return 0
        except GLib.Error as e:
            print(f"failed to signal running instance: {e}", file=sys.stderr)
            return 1
    app = PastewispApp()
    return app.run([sys.argv[0]])
