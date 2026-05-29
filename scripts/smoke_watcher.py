"""Manual smoke test for ClipboardWatcher.

Usage:
    .venv/bin/python scripts/smoke_watcher.py

Starts the watcher and prints every clipboard change to stdout for a few
seconds. In a separate terminal, run something like
``echo "hello" | xclip -selection clipboard`` to feed it data.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

from pastewisp.config import Config  # noqa: E402
from pastewisp.db import Database  # noqa: E402
from pastewisp.history import HistoryManager  # noqa: E402
from pastewisp.watcher import ClipboardWatcher  # noqa: E402
from pastewisp.active_window.x11 import X11ActiveWindowProbe  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = Gtk.Application(application_id="com.xnsystems.pastewisp.smoke")
    state = {}

    def on_activate(app):
        path = Path(tempfile.mkstemp(suffix=".sqlite")[1])
        db = Database(path)
        history = HistoryManager(db, Config())
        probe = X11ActiveWindowProbe()
        watcher = ClipboardWatcher(history, active_window=probe, on_added=lambda r: print(f"[on_added] {r}"))
        watcher.start()
        state["db"] = db
        state["watcher"] = watcher

        def tick():
            print(f"[tick] items={db.count()}", flush=True)
            return True

        GLib.timeout_add_seconds(1, tick)
        GLib.timeout_add_seconds(8, app.quit)
        # Print the initial state immediately.
        tick()

    app.connect("activate", on_activate)
    rc = app.run([])
    if "db" in state:
        print(f"[final] items={state['db'].count()}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
