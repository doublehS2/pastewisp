from __future__ import annotations

import logging
import sys
from typing import Optional

from gi.repository import Gio, GLib

from .. import i18n

log = logging.getLogger(__name__)


class TrayManager:
    """Manage the tray subprocess (``python -m pastewisp.tray_proc``).

    The main GTK 4 process can't host a GTK 3 AppIndicator, so the tray
    runs in its own process and communicates over D-Bus actions.
    """

    def __init__(self) -> None:
        self._proc: Optional[Gio.Subprocess] = None

    def start(self) -> None:
        if self._proc is not None:
            return
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.NONE)
        # Inherit the parent environment so the child sees DISPLAY/XAUTHORITY
        # and any other X11-related variables.
        try:
            argv = [
                sys.executable,
                "-m",
                "pastewisp.tray_proc",
                f"--lang={i18n.current_language()}",
            ]
            self._proc = launcher.spawnv(argv)
            self._proc.wait_async(None, self._on_exit, None)
            log.info("tray subprocess spawned")
        except GLib.Error as e:
            log.warning("tray subprocess spawn failed: %s", e)
            self._proc = None

    def stop(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            proc.send_signal(15)  # SIGTERM
        except Exception:  # noqa: BLE001
            pass

    def _on_exit(self, proc, result, _user_data) -> None:
        try:
            proc.wait_finish(result)
        except GLib.Error as e:
            log.debug("tray wait failed: %s", e)
        if self._proc is proc:
            self._proc = None
            log.info("tray subprocess exited")
