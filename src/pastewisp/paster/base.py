from __future__ import annotations

from typing import Protocol


class AutoPaster(Protocol):
    def paste(self) -> None:
        """Send Ctrl+V to whichever window has focus right now."""

    def close(self) -> None:
        ...
