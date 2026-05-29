from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .. import config as cfg
from ..config import Config
from ..i18n import t

log = logging.getLogger(__name__)

OnApply = Callable[[Config], None]


def _accel_to_label(accel: str) -> str:
    """Render a GTK accelerator (e.g. `<Control><Shift>v`) as a human-readable label."""
    ok, keyval, mods = Gtk.accelerator_parse(accel)
    if not ok:
        return accel
    label = Gtk.accelerator_get_label(keyval, mods)
    return label or accel


class PreferencesWindow(Gtk.Window):
    __gtype_name__ = "PastewispPreferences"

    def __init__(self, config: Config, on_apply: OnApply) -> None:
        super().__init__()
        self.set_title(t("prefs.title"))
        self.set_default_size(520, 500)
        self.set_modal(False)
        self.set_hide_on_close(True)
        self.config = config
        self.on_apply = on_apply
        self._capturing_hotkey = False
        self._captured: Optional[str] = config.general.hotkey
        # Mirrors prefs.language.* order: ("auto", "en", "ko").
        self._language_codes: tuple[str, ...] = ("auto", "en", "ko")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(outer)

        grid = Gtk.Grid(column_spacing=12, row_spacing=10, margin_top=14, margin_bottom=14,
                        margin_start=14, margin_end=14)
        outer.append(grid)

        row = 0

        # ─ Hotkey ─
        grid.attach(Gtk.Label(label=t("prefs.hotkey"), xalign=0), 0, row, 1, 1)
        hotkey_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._hotkey_label = Gtk.Label(label=_accel_to_label(config.general.hotkey), xalign=0)
        self._hotkey_label.set_hexpand(True)
        self._hotkey_btn = Gtk.Button(label=t("prefs.hotkey.change"))
        self._hotkey_btn.connect("clicked", self._begin_capture)
        hotkey_box.append(self._hotkey_label)
        hotkey_box.append(self._hotkey_btn)
        grid.attach(hotkey_box, 1, row, 1, 1)
        row += 1

        # ─ History size ─
        grid.attach(Gtk.Label(label=t("prefs.history_size"), xalign=0), 0, row, 1, 1)
        self._history_spin = Gtk.SpinButton.new_with_range(10, 5000, 10)
        self._history_spin.set_value(config.general.history_limit)
        grid.attach(self._history_spin, 1, row, 1, 1)
        row += 1

        # ─ Auto-paste ─
        grid.attach(Gtk.Label(label=t("prefs.auto_paste"), xalign=0), 0, row, 1, 1)
        self._auto_paste = Gtk.Switch()
        self._auto_paste.set_halign(Gtk.Align.START)
        self._auto_paste.set_active(config.general.auto_paste)
        grid.attach(self._auto_paste, 1, row, 1, 1)
        row += 1

        # ─ Image retention ─
        grid.attach(Gtk.Label(label=t("prefs.keep_images_days"), xalign=0), 0, row, 1, 1)
        self._image_days = Gtk.SpinButton.new_with_range(1, 365, 1)
        self._image_days.set_value(config.storage.keep_images_days)
        grid.attach(self._image_days, 1, row, 1, 1)
        row += 1

        # ─ Language ─
        grid.attach(Gtk.Label(label=t("prefs.language"), xalign=0), 0, row, 1, 1)
        self._language = Gtk.DropDown.new_from_strings([
            t("prefs.language.auto"),
            t("prefs.language.en"),
            t("prefs.language.ko"),
        ])
        try:
            current_idx = self._language_codes.index(config.general.language)
        except ValueError:
            current_idx = 0
        self._language.set_selected(current_idx)
        self._language.set_halign(Gtk.Align.START)
        grid.attach(self._language, 1, row, 1, 1)
        row += 1

        # ─ Excluded apps ─
        grid.attach(Gtk.Label(label=t("prefs.excluded"), xalign=0),
                    0, row, 2, 1)
        row += 1
        excl_scroller = Gtk.ScrolledWindow()
        excl_scroller.set_min_content_height(140)
        excl_scroller.set_hexpand(True)
        self._exclude_view = Gtk.TextView()
        self._exclude_view.set_monospace(True)
        buf = self._exclude_view.get_buffer()
        buf.set_text("\n".join(config.exclude.apps))
        excl_scroller.set_child(self._exclude_view)
        grid.attach(excl_scroller, 0, row, 2, 1)
        row += 1

        # ─ Hint ─
        hint = Gtk.Label(
            label=t("prefs.hotkey_hint"),
            xalign=0,
        )
        hint.add_css_class("dim-label")
        grid.attach(hint, 0, row, 2, 1)
        row += 1

        # ─ Buttons ─
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          margin_top=8, margin_bottom=14, margin_start=14, margin_end=14)
        actions.set_halign(Gtk.Align.END)
        self._cancel_btn = Gtk.Button(label=t("prefs.cancel"))
        self._cancel_btn.connect("clicked", lambda _b: self.close())
        self._save_btn = Gtk.Button(label=t("prefs.save"))
        self._save_btn.add_css_class("suggested-action")
        self._save_btn.connect("clicked", self._on_save)
        actions.append(self._cancel_btn)
        actions.append(self._save_btn)
        outer.append(actions)

        # Key controller for hotkey capture.
        self._key_ctl = Gtk.EventControllerKey()
        self._key_ctl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._key_ctl)

    # ───────── hotkey capture ─────────

    def _begin_capture(self, _btn) -> None:
        self._capturing_hotkey = True
        self._hotkey_label.set_label(t("prefs.hotkey.capture"))
        self._hotkey_btn.set_label(t("prefs.hotkey.cancel"))

    def _end_capture(self, accel: Optional[str]) -> None:
        self._capturing_hotkey = False
        if accel:
            self._captured = accel
            self._hotkey_label.set_label(_accel_to_label(accel))
        else:
            self._hotkey_label.set_label(_accel_to_label(self._captured or self.config.general.hotkey))
        self._hotkey_btn.set_label(t("prefs.hotkey.change"))

    def _on_key_pressed(self, _ctl, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        if not self._capturing_hotkey:
            return False
        if keyval == Gdk.KEY_Escape:
            self._end_capture(None)
            return True
        # Ignore presses of modifier keys alone.
        if keyval in (
            Gdk.KEY_Control_L, Gdk.KEY_Control_R,
            Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
            Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
            Gdk.KEY_Super_L, Gdk.KEY_Super_R,
        ):
            return True
        mods = state & Gtk.accelerator_get_default_mod_mask()
        accel = Gtk.accelerator_name(keyval, mods)
        if not accel:
            return True
        self._end_capture(accel)
        return True

    # ───────── save ─────────

    def _on_save(self, _btn) -> None:
        hotkey = self._captured or self.config.general.hotkey
        buf = self._exclude_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        apps = [line.strip() for line in text.splitlines() if line.strip()]
        lang_idx = self._language.get_selected()
        if 0 <= lang_idx < len(self._language_codes):
            language = self._language_codes[lang_idx]
        else:
            language = self.config.general.language
        new_cfg = (
            self.config
            .with_general(
                hotkey=hotkey,
                history_limit=int(self._history_spin.get_value()),
                auto_paste=bool(self._auto_paste.get_active()),
                language=language,
            )
            .with_storage(keep_images_days=int(self._image_days.get_value()))
            .with_exclude(apps=apps)
        )
        try:
            cfg.save(new_cfg)
        except Exception as e:  # noqa: BLE001
            log.exception("config save failed")
            dialog = Gtk.AlertDialog(message=t("prefs.save_failed"), detail=str(e))
            dialog.show(self)
            return
        self.config = new_cfg
        self.on_apply(new_cfg)
        self.close()
