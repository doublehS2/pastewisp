from __future__ import annotations

import logging
from typing import Callable, Optional

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gio  # noqa: E402

from .active_window.base import ActiveWindowProbe
from .db import image_hash, text_hash
from .history import HistoryManager

log = logging.getLogger(__name__)

OnAdded = Callable[[str], None]  # 'inserted' | 'updated' | 'skipped:*'


class ClipboardWatcher:
    """Subscribe to GDK clipboard changes and forward them to HistoryManager."""

    def __init__(
        self,
        history: HistoryManager,
        active_window: Optional[ActiveWindowProbe] = None,
        on_added: Optional[OnAdded] = None,
    ) -> None:
        self.history = history
        self.active_window = active_window
        self.on_added = on_added
        display = Gdk.Display.get_default()
        if display is None:
            raise RuntimeError("GDK display unavailable; running headless?")
        self.clipboard: Gdk.Clipboard = display.get_clipboard()
        self._handler_id: Optional[int] = None
        self._self_set_hashes: set[str] = set()

    def start(self) -> None:
        if self._handler_id is not None:
            return
        self._handler_id = self.clipboard.connect("changed", self._on_changed)
        # Absorb whatever is currently on the clipboard on startup.
        self._on_changed(self.clipboard)

    def stop(self) -> None:
        if self._handler_id is not None:
            self.clipboard.disconnect(self._handler_id)
            self._handler_id = None

    def mark_self_set(self, hash_: str) -> None:
        """Suppress the next "changed" event for this hash.

        Used when the popup itself sets the clipboard after a selection so we
        don't double-count it.
        """
        self._self_set_hashes.add(hash_)

    # ───────── internals ─────────

    def _current_app(self) -> Optional[str]:
        if self.active_window is None:
            return None
        try:
            w = self.active_window.current()
        except Exception:  # noqa: BLE001
            return None
        if w is None:
            return None
        return w.wm_class_combined or None

    def _on_changed(self, clipboard: Gdk.Clipboard) -> None:
        formats = clipboard.get_formats()
        # Try image first — some apps offer a text fallback alongside the image,
        # but we prefer the richer payload.
        has_image = False
        for mime in ("image/png", "image/jpeg", "image/bmp"):
            try:
                if formats.contain_mime_type(mime):
                    has_image = True
                    break
            except Exception:  # noqa: BLE001
                pass
        if has_image:
            self._read_texture()
        else:
            self._read_text()

    def _read_text(self) -> None:
        self.clipboard.read_text_async(None, self._on_text)

    def _on_text(self, source: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
        try:
            text = source.read_text_finish(result)
        except GLib.Error as e:
            log.debug("read_text failed: %s", e)
            return
        if not text:
            return
        h = text_hash(text)
        if h in self._self_set_hashes:
            self._self_set_hashes.discard(h)
            log.debug("skipping self-set text hash=%s", h)
            return
        app = self._current_app()
        result_add = self.history.add_text(text, source_app=app)
        log.debug("clipboard text added: %s (app=%s)", result_add.reason, app)
        if self.on_added:
            self.on_added(result_add.reason)

    def _read_texture(self) -> None:
        self.clipboard.read_texture_async(None, self._on_texture)

    def _on_texture(self, source: Gdk.Clipboard, result: Gio.AsyncResult) -> None:
        try:
            texture = source.read_texture_finish(result)
        except GLib.Error as e:
            log.debug("read_texture failed: %s, falling back to text", e)
            self._read_text()
            return
        if texture is None:
            self._read_text()
            return
        try:
            gbytes = texture.save_to_png_bytes()
        except Exception as e:  # noqa: BLE001
            log.debug("texture -> png failed: %s", e)
            return
        png_blob = bytes(gbytes.get_data())
        if not png_blob:
            return
        h = image_hash(png_blob)
        if h in self._self_set_hashes:
            self._self_set_hashes.discard(h)
            log.debug("skipping self-set image hash=%s", h)
            return
        width = texture.get_width()
        height = texture.get_height()
        app = self._current_app()
        result_add = self.history.add_image(png_blob, width, height, source_app=app)
        log.debug("clipboard image added: %s (%dx%d, app=%s)", result_add.reason, width, height, app)
        if self.on_added:
            self.on_added(result_add.reason)
