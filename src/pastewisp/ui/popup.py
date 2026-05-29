from __future__ import annotations

import logging
import time
from typing import Callable, Optional

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from ..cursor import Position
from ..db import Item
from ..history import HistoryManager
from ..i18n import t
from ..positioning import move_to_screen_coords

log = logging.getLogger(__name__)

# Callback signatures.
SelectCallback = Callable[[Item, bool], None]  # (item, paste_after_copy)
DeleteCallback = Callable[[Item], None]
PinToggleCallback = Callable[[Item], None]

PREVIEW_MAX_CHARS = 160
LIST_PAGE_SIZE = 500
THUMBNAIL_SIZE = 44

# ─────────────────────────────────────────────────────────────────────────────
# Design tokens. Centralized so the look stays consistent across the popup.
#
# Palette: deep charcoal base + single lavender accent + warm amber for pins.
# Typography: system sans-serif with monospace for shortcut chips, three sizes.
# Spacing: 8px grid.
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
window.pastewisp-popup {
    background-color: #15161a;
    color: #e8e9ed;
    border-radius: 14px;
    /* Soft drop shadow + 1px outer hairline so the window reads as elevated. */
    box-shadow:
        0 28px 64px rgba(0, 0, 0, 0.55),
        0 0 0 1px rgba(255, 255, 255, 0.06);
}

/* ───── Search area ───── */
.pastewisp-popup .search-area {
    padding: 14px 18px 12px 18px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.pastewisp-popup .search-area entry {
    background: transparent;
    border: none;
    box-shadow: none;
    outline: 0;
    padding: 2px 0;
    color: #e8e9ed;
    font-size: 15px;
    min-height: 22px;
}
.pastewisp-popup .search-area entry > text {
    color: #e8e9ed;
}
.pastewisp-popup .search-area entry > text > placeholder {
    color: #4a4d56;
}
.pastewisp-popup .search-area entry image {
    color: #5a5d66;
}

/* ───── List ───── */
.pastewisp-popup scrolledwindow {
    background: transparent;
    border: none;
}
.pastewisp-popup listview {
    background: transparent;
    padding: 6px 8px;
}
.pastewisp-popup row {
    padding: 0;
    background: transparent;
    border-radius: 8px;
    margin: 1px 0;
    transition: background-color 150ms ease, color 150ms ease;
}
.pastewisp-popup row:hover {
    background-color: rgba(255, 255, 255, 0.05);
}
.pastewisp-popup row:selected {
    background-color: rgba(167, 139, 250, 0.18);
    color: #ffffff;
}
.pastewisp-popup row:selected:hover {
    background-color: rgba(167, 139, 250, 0.22);
}

/* 3px left accent bar — a dedicated widget whose color we toggle. */
.pastewisp-popup .accent-bar {
    background-color: transparent;
    border-radius: 2px;
    margin: 8px 0;
    transition: background-color 150ms ease;
}
.pastewisp-popup row:selected .accent-bar {
    background-color: #a78bfa;
}
.pastewisp-popup row:selected .accent-bar.pinned {
    background-color: #e0a82e;
}

/* Row inner content. */
.pastewisp-popup .row-inner {
    padding: 11px 14px 11px 10px;
}

/* Thin divider between the pinned section and the recent section. */
.pastewisp-popup .section-start {
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    margin-top: 6px;
    padding-top: 4px;
}

/* Shortcut chip: gray for recent items, amber for pinned. */
.pastewisp-popup .shortcut {
    min-width: 32px;
    padding: 2px 7px;
    border-radius: 5px;
    background-color: rgba(255, 255, 255, 0.05);
    color: #9ea2ad;
    font-family: "JetBrains Mono", "Cascadia Code", "Source Code Pro", monospace;
    font-size: 10px;
    font-weight: 500;
}
.pastewisp-popup .shortcut.pinned {
    background-color: rgba(224, 168, 46, 0.15);
    color: #e0a82e;
    font-weight: 700;
}
/* Alt mode (pin-toggle mode): teal accent to distinguish from the ⌃ mode. */
.pastewisp-popup .shortcut.alt-mode {
    background-color: rgba(94, 234, 212, 0.16);
    color: #5eead4;
}
.pastewisp-popup .shortcut.alt-mode.pinned {
    background-color: rgba(94, 234, 212, 0.20);
    color: #5eead4;
}
.pastewisp-popup row:selected .shortcut {
    background-color: rgba(255, 255, 255, 0.10);
    color: #e8e9ed;
}
.pastewisp-popup row:selected .shortcut.pinned {
    background-color: rgba(224, 168, 46, 0.28);
    color: #ffd270;
}

/* Item text */
.pastewisp-popup .item-text {
    color: #e8e9ed;
    font-size: 13px;
}

/* Right-aligned monospace meta (source app). */
.pastewisp-popup .meta {
    color: #5a5d66;
    font-size: 11px;
    font-family: "JetBrains Mono", "Cascadia Code", monospace;
}
.pastewisp-popup row:selected .meta {
    color: #b4b7c0;
}

/* Image thumbnail. */
.pastewisp-popup .thumb {
    min-width: 44px;
    min-height: 44px;
    border-radius: 6px;
}

/* ───── Empty state ───── */
.pastewisp-popup .empty-state {
    padding: 60px 24px;
}
.pastewisp-popup .empty-state-title {
    color: #8a8d97;
    font-size: 14px;
    font-weight: 500;
}
.pastewisp-popup .empty-state-hint {
    color: #5a5d66;
    font-size: 12px;
    margin-top: 4px;
}

/* ───── Footer ───── */
.pastewisp-popup .footer {
    padding: 10px 18px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
}
.pastewisp-popup .footer-text {
    color: #6a6d76;
    font-size: 11px;
}
.pastewisp-popup .footer-key {
    background-color: rgba(255, 255, 255, 0.06);
    color: #a4a7af;
    padding: 1px 6px;
    border-radius: 3px;
    font-family: "JetBrains Mono", "Cascadia Code", monospace;
    font-size: 10px;
    font-weight: 500;
}
.pastewisp-popup .footer-count {
    color: #5a5d66;
    font-size: 11px;
    font-family: "JetBrains Mono", "Cascadia Code", monospace;
}
""".encode("utf-8")


def _install_css() -> None:
    if getattr(_install_css, "_done", False):
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS, len(_CSS))
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    _install_css._done = True  # type: ignore[attr-defined]


class _ItemObj(GObject.Object):
    __gtype_name__ = "PastewispItemObj"

    def __init__(self, item: Item) -> None:
        super().__init__()
        self.item = item


def _preview(text: str) -> str:
    one_line = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    one_line = " ".join(one_line.split())
    if len(one_line) > PREVIEW_MAX_CHARS:
        one_line = one_line[: PREVIEW_MAX_CHARS - 1] + "…"
    return one_line


def _texture_from_png(blob: bytes) -> Optional[Gdk.Texture]:
    try:
        gbytes = GLib.Bytes.new(blob)
        return Gdk.Texture.new_from_bytes(gbytes)
    except GLib.Error as e:
        log.debug("texture load failed: %s", e)
        return None


def _shorten_source(src: Optional[str]) -> str:
    """Collapse `google-chrome Google-chrome` style WM_CLASS into a single short token."""
    if not src:
        return ""
    tokens = src.split()
    # If the first token is a dotted form like `org.foo.Bar`, keep only the last segment.
    head = tokens[0]
    if "." in head:
        head = head.rsplit(".", 1)[-1]
    return head.lower()


def _key_chip(label: str) -> Gtk.Label:
    """Footer key chip (small label with a tinted background)."""
    w = Gtk.Label(label=label)
    w.add_css_class("footer-key")
    return w


def _footer_text(label: str) -> Gtk.Label:
    w = Gtk.Label(label=label)
    w.add_css_class("footer-text")
    return w


class PopupWindow(Gtk.Window):
    __gtype_name__ = "PastewispPopup"

    def __init__(
        self,
        history: HistoryManager,
        on_select: SelectCallback,
        on_delete: Optional[DeleteCallback] = None,
        on_pin_toggle: Optional[PinToggleCallback] = None,
    ) -> None:
        super().__init__()
        _install_css()
        self.history = history
        self.on_select = on_select
        self.on_delete = on_delete
        self.on_pin_toggle = on_pin_toggle

        self.set_title("Pastewisp")
        self.set_decorated(False)
        self.set_default_size(580, 500)
        self.set_resizable(False)
        self.set_modal(False)
        self.set_hide_on_close(True)
        self.add_css_class("pastewisp-popup")
        self._pending_position: Optional[Position] = None
        self._shown_at: float = 0.0  # Last present() timestamp — used to ignore transient blur.
        self._alt_mode: bool = False  # True while Alt is held = pin-toggle mode.
        self.connect("map", self._on_mapped)
        # Clicking another window = focus lost → auto-close the popup.
        self.connect("notify::is-active", self._on_active_changed)

        # ───── Model ─────
        self._store = Gio.ListStore.new(_ItemObj)
        self._filter = Gtk.CustomFilter.new(self._filter_match, None)
        self._filter_model = Gtk.FilterListModel.new(self._store, self._filter)
        self._selection = Gtk.SingleSelection.new(self._filter_model)
        self._selection.set_autoselect(True)
        self._selection.set_can_unselect(False)

        # ───── Root layout ─────
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        # Search area.
        search_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_area.add_css_class("search-area")
        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text(t("popup.search_placeholder"))
        self._search.set_hexpand(True)
        self._search.connect("search-changed", self._on_search_changed)
        self._search.connect("activate", self._on_search_activate)
        search_area.append(self._search)
        root.append(search_area)

        # The list and the empty state share one slot — the empty page is shown
        # when the filtered result is zero items.
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_hexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(120)
        root.append(self._stack)

        # List page.
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_hexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._row_setup)
        factory.connect("bind", self._row_bind)
        self._list = Gtk.ListView.new(self._selection, factory)
        self._list.set_single_click_activate(True)
        self._list.connect("activate", self._on_row_activate)
        scroller.set_child(self._list)
        self._stack.add_named(scroller, "list")

        # Empty state page.
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        empty.set_halign(Gtk.Align.CENTER)
        empty.set_valign(Gtk.Align.CENTER)
        empty.add_css_class("empty-state")
        empty_title = Gtk.Label(label=t("popup.empty.no_results.title"))
        empty_title.add_css_class("empty-state-title")
        empty_hint = Gtk.Label(label=t("popup.empty.no_results.hint_default"))
        empty_hint.add_css_class("empty-state-hint")
        empty.append(empty_title)
        empty.append(empty_hint)
        self._empty_title = empty_title
        self._empty_hint = empty_hint
        self._stack.add_named(empty, "empty")

        # Footer — key chips + item count.
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        footer.add_css_class("footer")
        # Left-side hint group (swapped dynamically by Alt-mode).
        self._hints_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self._hints_box.set_hexpand(True)
        footer.append(self._hints_box)
        # Right-side count.
        self._count_label = Gtk.Label(label="")
        self._count_label.add_css_class("footer-count")
        self._count_label.set_halign(Gtk.Align.END)
        footer.append(self._count_label)
        root.append(footer)
        self._render_footer_hints()

        # Key controller in CAPTURE phase so we intercept Esc/Enter/shortcuts
        # before SearchEntry consumes them.
        key_ctl = Gtk.EventControllerKey()
        key_ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_ctl.connect("key-pressed", self._on_key_pressed)
        key_ctl.connect("key-released", self._on_key_released)
        self.add_controller(key_ctl)
        # Reset Alt-mode when focus is lost (Alt+Tab etc.) so the next popup
        # opens in the regular mode.
        self.connect("notify::is-active", self._reset_alt_mode_on_blur)

    # ───────── lifecycle ─────────

    def reload_and_present(self, position: Optional[Position] = None) -> None:
        self._reload()
        self._search.set_text("")
        self._search.grab_focus()
        self._pending_position = position
        self._shown_at = time.monotonic()
        self.present()
        # The WM may place the window after present() and overwrite our move,
        # so try a few times until the position sticks.
        if position is not None:
            for delay_ms in (30, 100, 250):
                GLib.timeout_add(delay_ms, self._apply_position_at, position)

    def _on_active_changed(self, _w, _pspec) -> None:
        # When the popup loses active state (= focus), treat it as an outside
        # click and hide.
        if self.is_active():
            return
        if not self.get_visible():
            return
        # Ignore the brief blur that happens right after present() while the WM
        # is still transferring focus.
        if time.monotonic() - self._shown_at < 0.3:
            return
        self.set_visible(False)

    def _reset_alt_mode_on_blur(self, _w, _pspec) -> None:
        if not self.is_active() and self._alt_mode:
            self._set_alt_mode(False)

    def _on_mapped(self, _w) -> None:
        if self._pending_position is not None:
            self._apply_position_at(self._pending_position)

    def _apply_position_at(self, pos: Position) -> bool:
        if pos.source == "caret":
            gap = max(4, pos.char_height // 4)
            target_x = pos.x
            target_y = pos.y + pos.char_height + gap
        elif pos.source == "active-window":
            popup_h = self.get_height() or self.get_default_size().height or 500
            target_x = pos.x
            target_y = pos.y - popup_h - 8
        else:
            # Mouse position with a small offset so the popup doesn't sit
            # exactly under the cursor.
            target_x = pos.x + 6
            target_y = pos.y + 6
        log.debug("popup target: source=%s (%d,%d)", pos.source, target_x, target_y)
        move_to_screen_coords(self, target_x, target_y)
        return False

    # ───────── model ─────────

    def _reload(self) -> None:
        items = self.history.list_items(limit=LIST_PAGE_SIZE)
        self._store.remove_all()
        for it in items:
            self._store.append(_ItemObj(it))
        self._sync_visible_page()

    def _filter_match(self, item_obj: GObject.Object, _user_data) -> bool:
        text = self._search.get_text().strip().lower()
        if not text:
            return True
        it: Item = item_obj.item  # type: ignore[attr-defined]
        if it.is_text and it.text:
            return text in it.text.lower()
        if it.is_image:
            # Images don't participate in text search.
            return False
        return False

    def _on_search_changed(self, _entry) -> None:
        self._filter.changed(Gtk.FilterChange.DIFFERENT)
        if self._filter_model.get_n_items() > 0:
            self._selection.set_selected(0)
        self._sync_visible_page()

    def _on_search_activate(self, _entry) -> None:
        self._activate_selected(paste=True)

    def _render_footer_hints(self) -> None:
        """Swap the footer key hints based on Alt-mode state."""
        # Remove existing children.
        c = self._hints_box.get_first_child()
        while c is not None:
            nxt = c.get_next_sibling()
            self._hints_box.remove(c)
            c = nxt
        if self._alt_mode:
            pairs = (
                ("⌥N", t("popup.footer.alt.pin")),
                ("⌥A·B…", t("popup.footer.alt.unpin")),
                ("Alt", t("popup.footer.alt.release")),
                ("Esc", t("popup.footer.close")),
            )
        else:
            pairs = (
                ("↵", t("popup.footer.normal.paste")),
                ("⌃N", t("popup.footer.normal.select")),
                ("Alt", t("popup.footer.normal.pin_mode")),
                ("Esc", t("popup.footer.close")),
            )
        for chip, text in pairs:
            group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            group.append(_key_chip(chip))
            group.append(_footer_text(text))
            self._hints_box.append(group)

    def _sync_visible_page(self) -> None:
        n = self._filter_model.get_n_items()
        total = self._store.get_n_items()
        # Pick the empty-state copy: distinguish "no matches for query" from
        # "history is empty".
        query = self._search.get_text().strip()
        if n == 0:
            if query:
                self._empty_title.set_label(t("popup.empty.no_results.title"))
                self._empty_hint.set_label(t("popup.empty.no_results.hint_with_query", query=query))
            else:
                self._empty_title.set_label(t("popup.empty.history.title"))
                self._empty_hint.set_label(t("popup.empty.history.hint"))
            self._stack.set_visible_child_name("empty")
        else:
            self._stack.set_visible_child_name("list")
        # Counter: show n/total while searching, otherwise just total.
        if query:
            self._count_label.set_label(f"{n} / {total}")
        else:
            self._count_label.set_label(f"{total}")

    # ───────── row factory ─────────

    def _row_setup(self, _factory, list_item: Gtk.ListItem) -> None:
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)

        # 3px left accent bar that gets a color when the row is selected.
        accent = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        accent.add_css_class("accent-bar")
        accent.set_size_request(3, -1)
        outer.append(accent)

        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        inner.add_css_class("row-inner")
        inner.set_hexpand(True)

        shortcut = Gtk.Label(label="")
        shortcut.add_css_class("shortcut")
        shortcut.set_xalign(0.5)
        shortcut.set_yalign(0.5)
        inner.append(shortcut)

        thumb = Gtk.Picture()
        thumb.set_can_shrink(True)
        thumb.set_content_fit(Gtk.ContentFit.SCALE_DOWN)
        thumb.set_size_request(THUMBNAIL_SIZE, THUMBNAIL_SIZE)
        thumb.add_css_class("thumb")
        thumb.set_visible(False)
        inner.append(thumb)

        text_label = Gtk.Label(label="")
        text_label.add_css_class("item-text")
        text_label.set_xalign(0)
        text_label.set_yalign(0.5)
        text_label.set_ellipsize(3)  # END
        text_label.set_hexpand(True)
        inner.append(text_label)

        meta_label = Gtk.Label(label="")
        meta_label.add_css_class("meta")
        meta_label.set_xalign(1.0)
        meta_label.set_yalign(0.5)
        inner.append(meta_label)

        outer.append(inner)
        list_item.set_child(outer)

    def _row_bind(self, _factory, list_item: Gtk.ListItem) -> None:
        outer = list_item.get_child()
        accent = outer.get_first_child()
        inner = accent.get_next_sibling()
        # Walk inner children: shortcut, thumb, text_label, meta_label.
        children = []
        c = inner.get_first_child()
        while c is not None:
            children.append(c)
            c = c.get_next_sibling()
        shortcut, thumb, text_label, meta_label = children[0], children[1], children[2], children[3]

        item_obj: _ItemObj = list_item.get_item()  # type: ignore[assignment]
        it = item_obj.item
        position = list_item.get_position()

        # Shortcut chip: ⌥ prefix in Alt mode (pin toggle), ⌃ otherwise (activate).
        shortcut.remove_css_class("pinned")
        shortcut.remove_css_class("alt-mode")
        accent.remove_css_class("pinned")
        prefix = "⌥" if self._alt_mode else "⌃"
        if it.pinned and it.pin_letter:
            letter_text = it.pin_letter.upper()
            shortcut.set_label(f"{prefix}{letter_text}" if self._alt_mode else letter_text)
            shortcut.add_css_class("pinned")
            if self._alt_mode:
                shortcut.add_css_class("alt-mode")
            accent.add_css_class("pinned")
            shortcut.set_visible(True)
        elif position < 10:
            digit = 0 if position == 9 else position + 1
            shortcut.set_label(f"{prefix}{digit}")
            if self._alt_mode:
                shortcut.add_css_class("alt-mode")
            shortcut.set_visible(True)
        else:
            shortcut.set_label("")
            shortcut.set_visible(False)

        # Mark the first non-pinned row in a list that has pinned items so
        # CSS can draw a section divider above it.
        outer.remove_css_class("section-start")
        if position > 0 and not it.pinned:
            prev_obj = self._filter_model.get_item(position - 1)
            try:
                prev_pinned = bool(prev_obj.item.pinned) if prev_obj else False  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                prev_pinned = False
            if prev_pinned:
                outer.add_css_class("section-start")

        if it.is_image and it.image_blob:
            tex = _texture_from_png(it.image_blob)
            if tex is not None:
                thumb.set_paintable(tex)
                thumb.set_visible(True)
            else:
                thumb.set_visible(False)
            text_label.set_label(t("popup.image_meta", w=it.image_w, h=it.image_h))
        else:
            thumb.set_visible(False)
            thumb.set_paintable(None)
            text_label.set_label(_preview(it.text or ""))

        meta_label.set_label(_shorten_source(it.source_app))

    # ───────── key handling ─────────

    def _on_row_activate(self, _list, _position: int) -> None:
        self._activate_selected(paste=True)

    def _on_key_pressed(self, _ctl, keyval, _keycode, state) -> bool:
        mods = state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(mods & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(mods & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(mods & Gdk.ModifierType.ALT_MASK)

        # Alt alone (no other key) → enter pin-toggle mode.
        if keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R):
            self._set_alt_mode(True)
            return False  # Let other handlers see it too.

        if keyval == Gdk.KEY_Escape:
            self.set_visible(False)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._activate_selected(paste=not shift)
            return True
        if keyval == Gdk.KEY_Down:
            self._move_selection(+1)
            return True
        if keyval == Gdk.KEY_Up:
            self._move_selection(-1)
            return True
        if keyval == Gdk.KEY_Page_Down:
            self._move_selection(+8)
            return True
        if keyval == Gdk.KEY_Page_Up:
            self._move_selection(-8)
            return True
        if keyval == Gdk.KEY_Delete:
            self._delete_selected()
            return True
        if ctrl and shift and keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self._toggle_pin_selected()
            return True
        # Alt + digit/letter → toggle pin (no activation).
        if alt and not ctrl and Gdk.KEY_0 <= keyval <= Gdk.KEY_9:
            digit = keyval - Gdk.KEY_0
            position = 9 if digit == 0 else digit - 1
            return self._toggle_pin_at_position(position)
        if alt and not ctrl and Gdk.KEY_a <= keyval <= Gdk.KEY_z:
            letter = chr(keyval)
            return self._toggle_pin_by_letter(letter)
        # Ctrl + digit/letter → activate + close.
        if ctrl and not shift and Gdk.KEY_0 <= keyval <= Gdk.KEY_9:
            digit = keyval - Gdk.KEY_0
            position = 9 if digit == 0 else digit - 1
            return self._activate_at_position(position)
        if ctrl and not shift and Gdk.KEY_a <= keyval <= Gdk.KEY_z:
            letter = chr(keyval)
            return self._activate_by_pin_letter(letter)
        return False

    def _on_key_released(self, _ctl, keyval, _keycode, _state) -> None:
        if keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R):
            self._set_alt_mode(False)

    def _set_alt_mode(self, enabled: bool) -> None:
        if self._alt_mode == enabled:
            return
        self._alt_mode = enabled
        # Update the shortcut badge labels on visible rows directly —
        # items_changed does not trigger a re-bind because the GObject
        # instances are unchanged.
        self._refresh_visible_badges()
        # Footer key chips reflect the mode.
        self._render_footer_hints()

    def _refresh_visible_badges(self) -> None:
        """Walk the ListView's row widgets and update shortcut labels in-place."""
        prefix = "⌥" if self._alt_mode else "⌃"
        child = self._list.get_first_child()
        position = 0
        # Item-to-position lookup goes through the filter model; the ListView's
        # child order matches the model order.
        while child is not None:
            outer = child.get_first_child()
            if outer is not None:
                # outer = [accent, inner]
                accent = outer.get_first_child()
                inner = accent.get_next_sibling() if accent else None
                shortcut = inner.get_first_child() if inner else None
                if shortcut is not None and isinstance(shortcut, Gtk.Label):
                    obj = self._filter_model.get_item(position)
                    if obj is not None:
                        it: Item = obj.item  # type: ignore[attr-defined]
                        shortcut.remove_css_class("alt-mode")
                        if it.pinned and it.pin_letter:
                            letter_text = it.pin_letter.upper()
                            if self._alt_mode:
                                shortcut.set_label(f"{prefix}{letter_text}")
                                shortcut.add_css_class("alt-mode")
                            else:
                                shortcut.set_label(letter_text)
                        elif position < 10:
                            digit = 0 if position == 9 else position + 1
                            shortcut.set_label(f"{prefix}{digit}")
                            if self._alt_mode:
                                shortcut.add_css_class("alt-mode")
            position += 1
            child = child.get_next_sibling()

    def _move_selection(self, delta: int) -> None:
        n = self._filter_model.get_n_items()
        if n == 0:
            return
        idx = self._selection.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            idx = 0
        new_idx = max(0, min(n - 1, idx + delta))
        self._selection.set_selected(new_idx)
        # Ensure the newly selected row is visible.
        try:
            self._list.scroll_to(new_idx, Gtk.ListScrollFlags.NONE, None)
        except Exception:  # noqa: BLE001
            pass

    def _selected_item(self) -> Optional[Item]:
        idx = self._selection.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION:
            return None
        obj = self._filter_model.get_item(idx)
        if obj is None:
            return None
        return obj.item  # type: ignore[attr-defined]

    def _activate_selected(self, paste: bool) -> None:
        item = self._selected_item()
        if item is None:
            return
        self.set_visible(False)
        # Hide the window first, then invoke the callback so focus has time to
        # return to the previously focused window before auto-paste runs.
        GLib.timeout_add(60, lambda: (self.on_select(item, paste), False)[1])

    def _activate_at_position(self, idx: int) -> bool:
        n = self._filter_model.get_n_items()
        if idx >= n:
            return True
        self._selection.set_selected(idx)
        self._activate_selected(paste=True)
        return True

    def _activate_by_pin_letter(self, letter: str) -> bool:
        n = self._filter_model.get_n_items()
        for i in range(n):
            obj = self._filter_model.get_item(i)
            if obj is None:
                continue
            it: Item = obj.item  # type: ignore[attr-defined]
            if it.pinned and it.pin_letter == letter:
                self._selection.set_selected(i)
                self._activate_selected(paste=True)
                return True
        return True

    def _toggle_pin_at_position(self, idx: int) -> bool:
        """Alt + digit → toggle pin for the row at that position. Popup stays open."""
        n = self._filter_model.get_n_items()
        if idx >= n:
            return True
        obj = self._filter_model.get_item(idx)
        if obj is None:
            return True
        item: Item = obj.item  # type: ignore[attr-defined]
        if self.on_pin_toggle:
            self.on_pin_toggle(item)
        self._reload()
        return True

    def _toggle_pin_by_letter(self, letter: str) -> bool:
        """Alt + letter → unpin the pinned item with that letter. Popup stays open."""
        n = self._filter_model.get_n_items()
        for i in range(n):
            obj = self._filter_model.get_item(i)
            if obj is None:
                continue
            it: Item = obj.item  # type: ignore[attr-defined]
            if it.pinned and it.pin_letter == letter:
                if self.on_pin_toggle:
                    self.on_pin_toggle(it)
                self._reload()
                return True
        return True

    def _toggle_pin_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        if self.on_pin_toggle:
            self.on_pin_toggle(item)
        self._reload()

    def _delete_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        if self.on_delete:
            self.on_delete(item)
        self._reload()
