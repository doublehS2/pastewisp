from __future__ import annotations

import logging
import time

from Xlib import X, XK, display
from Xlib.ext import xtest

log = logging.getLogger(__name__)


class X11AutoPaster:
    """Synthesize Ctrl+V key events through the XTest extension."""

    def __init__(self) -> None:
        self._display = display.Display()
        if not self._display.has_extension("XTEST"):
            raise RuntimeError("X server is missing the XTEST extension — auto-paste unavailable")
        self._ctrl_kc = self._display.keysym_to_keycode(XK.XK_Control_L)
        self._v_kc = self._display.keysym_to_keycode(XK.XK_v)
        if self._ctrl_kc == 0 or self._v_kc == 0:
            raise RuntimeError(f"failed to map Ctrl/V keycodes (ctrl={self._ctrl_kc}, v={self._v_kc})")

    def paste(self) -> None:
        d = self._display
        try:
            xtest.fake_input(d, X.KeyPress, self._ctrl_kc)
            d.sync()
            time.sleep(0.005)
            xtest.fake_input(d, X.KeyPress, self._v_kc)
            d.sync()
            time.sleep(0.005)
            xtest.fake_input(d, X.KeyRelease, self._v_kc)
            d.sync()
            time.sleep(0.005)
            xtest.fake_input(d, X.KeyRelease, self._ctrl_kc)
            d.sync()
        except Exception:  # noqa: BLE001
            log.exception("auto paste failed")

    def close(self) -> None:
        try:
            self._display.close()
        except Exception:
            pass
