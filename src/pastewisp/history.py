from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from .config import Config
from .db import Database, Item, image_hash, text_hash

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddResult:
    item: Optional[Item]
    reason: str  # 'inserted' | 'updated' | 'skipped:excluded' | 'skipped:empty' | 'skipped:too-large'


def is_excluded_app(source_app: Optional[str], excluded: Iterable[str]) -> bool:
    if not source_app:
        return False
    s = source_app.lower()
    return any(pat.lower() in s for pat in excluded if pat)


class HistoryManager:
    """High-level clipboard history API.

    Wraps the database with dedupe, app-exclusion and size-cap policies.
    """

    def __init__(self, db: Database, config: Config) -> None:
        self.db = db
        self.config = config

    def replace_config(self, config: Config) -> None:
        self.config = config

    # ───────── add ─────────

    def add_text(self, text: str, source_app: Optional[str] = None, now: Optional[int] = None) -> AddResult:
        if not text or not text.strip():
            return AddResult(None, "skipped:empty")
        if is_excluded_app(source_app, self.config.exclude.apps):
            return AddResult(None, "skipped:excluded")
        existing = self.db.get_by_hash(text_hash(text))
        item = self.db.upsert_text(text, source_app=source_app, now=now)
        reason = "updated" if existing else "inserted"
        if reason == "inserted":
            self._enforce_size_limit()
        return AddResult(item, reason)

    def add_image(
        self,
        png_blob: bytes,
        width: int,
        height: int,
        source_app: Optional[str] = None,
        now: Optional[int] = None,
    ) -> AddResult:
        if not png_blob:
            return AddResult(None, "skipped:empty")
        if is_excluded_app(source_app, self.config.exclude.apps):
            return AddResult(None, "skipped:excluded")
        if len(png_blob) > self.config.storage.max_image_bytes:
            return AddResult(None, "skipped:too-large")
        existing = self.db.get_by_hash(image_hash(png_blob))
        item = self.db.upsert_image(png_blob, width, height, source_app=source_app, now=now)
        reason = "updated" if existing else "inserted"
        if reason == "inserted":
            self._enforce_size_limit()
        return AddResult(item, reason)

    # ───────── reuse on paste ─────────

    def touch(self, item_id: int, now: Optional[int] = None) -> None:
        self.db.touch(item_id, now=now)

    # ───────── query ─────────

    def list_items(self, limit: int = 500) -> list[Item]:
        return self.db.list_items(limit=limit)

    def list_pinned(self) -> list[Item]:
        return self.db.list_pinned()

    def search(self, query: str, limit: int = 500) -> list[Item]:
        return self.db.search(query, limit=limit)

    # ───────── mutate ─────────

    def pin(self, item_id: int) -> None:
        self.db.set_pinned(item_id, True)

    def unpin(self, item_id: int) -> None:
        self.db.set_pinned(item_id, False)

    def toggle_pin(self, item_id: int) -> bool:
        item = self.db.get_by_id(item_id)
        if item is None:
            return False
        new_state = not item.pinned
        self.db.set_pinned(item_id, new_state)
        return new_state

    def delete(self, item_id: int) -> None:
        self.db.delete(item_id)

    def clear_all(self, keep_pinned: bool = True) -> int:
        return self.db.clear_all(keep_pinned=keep_pinned)

    # ───────── maintenance ─────────

    def prune(self, now: Optional[int] = None) -> tuple[int, int]:
        ts = now if now is not None else int(time.time())
        size_removed = self._enforce_size_limit()
        image_removed = self.db.prune_old_images(
            older_than_seconds=self.config.storage.keep_images_days * 86400,
            now=ts,
        )
        if size_removed or image_removed:
            log.info("prune: size_removed=%s image_removed=%s", size_removed, image_removed)
        return size_removed, image_removed

    def _enforce_size_limit(self) -> int:
        return self.db.prune_to_size(self.config.general.history_limit)
