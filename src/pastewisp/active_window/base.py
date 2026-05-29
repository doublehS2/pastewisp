from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class ActiveWindow:
    window_id: int
    wm_class_instance: Optional[str]
    wm_class: Optional[str]
    title: Optional[str]
    # Absolute screen coordinates; all zero when unknown.
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def wm_class_combined(self) -> str:
        parts = [p for p in (self.wm_class_instance, self.wm_class) if p]
        return " ".join(parts).strip()

    @property
    def has_geometry(self) -> bool:
        return self.width > 0 and self.height > 0


class ActiveWindowProbe(Protocol):
    def current(self) -> Optional[ActiveWindow]:
        ...

    def close(self) -> None:
        ...
