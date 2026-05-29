from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from . import paths

TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS items (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        content_type  TEXT    NOT NULL CHECK (content_type IN ('text', 'image')),
        text          TEXT,
        image_blob    BLOB,
        image_w       INTEGER,
        image_h       INTEGER,
        source_app    TEXT,
        hash          TEXT    NOT NULL UNIQUE,
        pinned        INTEGER NOT NULL DEFAULT 0,
        pin_letter    TEXT,
        created_at    INTEGER NOT NULL,
        last_used_at  INTEGER NOT NULL,
        use_count     INTEGER NOT NULL DEFAULT 1
    )
"""

INDEX_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_items_hash ON items(hash)",
    "CREATE INDEX IF NOT EXISTS idx_items_pinned_used ON items(pinned DESC, last_used_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_items_pin_letter ON items(pin_letter) WHERE pin_letter IS NOT NULL",
]

PIN_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class Item:
    id: int
    content_type: str
    text: Optional[str]
    image_blob: Optional[bytes]
    image_w: Optional[int]
    image_h: Optional[int]
    source_app: Optional[str]
    hash: str
    pinned: bool
    pin_letter: Optional[str]
    created_at: int
    last_used_at: int
    use_count: int

    @property
    def is_text(self) -> bool:
        return self.content_type == "text"

    @property
    def is_image(self) -> bool:
        return self.content_type == "image"


def text_hash(text: str) -> str:
    return "t:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def image_hash(blob: bytes) -> str:
    return "i:" + hashlib.sha256(blob).hexdigest()


def _row_to_item(row: sqlite3.Row) -> Item:
    # pin_letter may not exist on databases predating that migration; tolerate it.
    try:
        pin_letter = row["pin_letter"]
    except (IndexError, KeyError):
        pin_letter = None
    return Item(
        id=row["id"],
        content_type=row["content_type"],
        text=row["text"],
        image_blob=row["image_blob"],
        image_w=row["image_w"],
        image_h=row["image_h"],
        source_app=row["source_app"],
        hash=row["hash"],
        pinned=bool(row["pinned"]),
        pin_letter=pin_letter,
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        use_count=row["use_count"],
    )


class Database:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or paths.db_file()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._fts_available = self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def _init_schema(self) -> bool:
        # 1. Ensure the table exists (on a fresh DB the column list is already complete).
        self._conn.execute(TABLE_DDL)
        # 2. Migrate existing DBs — add pin_letter column before creating its index.
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(items)").fetchall()}
        if "pin_letter" not in cols:
            self._conn.execute("ALTER TABLE items ADD COLUMN pin_letter TEXT")
        # 3. Indexes (run after the column is guaranteed to exist).
        for stmt in INDEX_DDL:
            self._conn.execute(stmt)
        # 4. Back-fill letters for items that were already pinned before this migration.
        rows = self._conn.execute(
            "SELECT id FROM items WHERE pinned = 1 AND pin_letter IS NULL "
            "ORDER BY last_used_at DESC"
        ).fetchall()
        if rows:
            used = {
                r[0] for r in self._conn.execute(
                    "SELECT pin_letter FROM items WHERE pin_letter IS NOT NULL"
                ).fetchall() if r[0]
            }
            available = [c for c in PIN_LETTERS if c not in used]
            for row, letter in zip(rows, available):
                self._conn.execute("UPDATE items SET pin_letter = ? WHERE id = ?", (letter, row["id"]))
        # FTS5 isn't always available depending on the SQLite build — fall back to LIKE.
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts "
                "USING fts5(text, content='items', content_rowid='id', tokenize='unicode61')"
            )
            self._conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items
                BEGIN
                    INSERT INTO items_fts(rowid, text) VALUES (new.id, COALESCE(new.text, ''));
                END;
                CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items
                BEGIN
                    INSERT INTO items_fts(items_fts, rowid, text) VALUES('delete', old.id, COALESCE(old.text, ''));
                END;
                CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items
                BEGIN
                    INSERT INTO items_fts(items_fts, rowid, text) VALUES('delete', old.id, COALESCE(old.text, ''));
                    INSERT INTO items_fts(rowid, text) VALUES (new.id, COALESCE(new.text, ''));
                END;
                """
            )
            return True
        except sqlite3.OperationalError:
            return False

    # ───────── insert/touch ─────────

    def get_by_hash(self, hash_: str) -> Optional[Item]:
        cur = self._conn.execute("SELECT * FROM items WHERE hash = ?", (hash_,))
        row = cur.fetchone()
        return _row_to_item(row) if row else None

    def upsert_text(self, text: str, source_app: Optional[str] = None, now: Optional[int] = None) -> Item:
        h = text_hash(text)
        return self._upsert(
            hash_=h,
            content_type="text",
            text=text,
            image_blob=None,
            image_w=None,
            image_h=None,
            source_app=source_app,
            now=now,
        )

    def upsert_image(
        self,
        blob: bytes,
        width: int,
        height: int,
        source_app: Optional[str] = None,
        now: Optional[int] = None,
    ) -> Item:
        h = image_hash(blob)
        return self._upsert(
            hash_=h,
            content_type="image",
            text=None,
            image_blob=blob,
            image_w=width,
            image_h=height,
            source_app=source_app,
            now=now,
        )

    def _upsert(
        self,
        *,
        hash_: str,
        content_type: str,
        text: Optional[str],
        image_blob: Optional[bytes],
        image_w: Optional[int],
        image_h: Optional[int],
        source_app: Optional[str],
        now: Optional[int],
    ) -> Item:
        ts = now if now is not None else int(time.time())
        existing = self.get_by_hash(hash_)
        if existing:
            with self._tx() as conn:
                conn.execute(
                    "UPDATE items SET last_used_at = ?, use_count = use_count + 1, "
                    "source_app = COALESCE(?, source_app) WHERE id = ?",
                    (ts, source_app, existing.id),
                )
            return self.get_by_id(existing.id)  # type: ignore[return-value]
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO items "
                "(content_type, text, image_blob, image_w, image_h, source_app, hash, pinned, created_at, last_used_at, use_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 1)",
                (content_type, text, image_blob, image_w, image_h, source_app, hash_, ts, ts),
            )
            item_id = cur.lastrowid
        item = self.get_by_id(item_id)
        assert item is not None
        return item

    def touch(self, item_id: int, now: Optional[int] = None) -> None:
        ts = now if now is not None else int(time.time())
        with self._tx() as conn:
            conn.execute(
                "UPDATE items SET last_used_at = ?, use_count = use_count + 1 WHERE id = ?",
                (ts, item_id),
            )

    # ───────── queries ─────────

    def get_by_id(self, item_id: int) -> Optional[Item]:
        cur = self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = cur.fetchone()
        return _row_to_item(row) if row else None

    def list_items(self, limit: int = 500, offset: int = 0) -> list[Item]:
        cur = self._conn.execute(
            "SELECT * FROM items ORDER BY pinned DESC, last_used_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [_row_to_item(r) for r in cur.fetchall()]

    def list_pinned(self) -> list[Item]:
        cur = self._conn.execute(
            "SELECT * FROM items WHERE pinned = 1 ORDER BY last_used_at DESC"
        )
        return [_row_to_item(r) for r in cur.fetchall()]

    def search(self, query: str, limit: int = 500) -> list[Item]:
        q = query.strip()
        if not q:
            return self.list_items(limit=limit)
        if self._fts_available:
            try:
                # Prefix match each token via FTS5.
                tokens = [t for t in q.split() if t]
                if not tokens:
                    return self.list_items(limit=limit)
                fts_q = " ".join(f'"{t.replace(chr(34), chr(34) * 2)}"*' for t in tokens)
                cur = self._conn.execute(
                    "SELECT items.* FROM items "
                    "JOIN items_fts ON items_fts.rowid = items.id "
                    "WHERE items_fts MATCH ? "
                    "ORDER BY items.pinned DESC, items.last_used_at DESC LIMIT ?",
                    (fts_q, limit),
                )
                rows = cur.fetchall()
                if rows:
                    return [_row_to_item(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        # LIKE fallback — also handles CJK/unicode substring matches.
        like = f"%{q}%"
        cur = self._conn.execute(
            "SELECT * FROM items WHERE text LIKE ? "
            "ORDER BY pinned DESC, last_used_at DESC LIMIT ?",
            (like, limit),
        )
        return [_row_to_item(r) for r in cur.fetchall()]

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM items")
        return int(cur.fetchone()["c"])

    # ───────── mutate ─────────

    def set_pinned(self, item_id: int, pinned: bool) -> None:
        with self._tx() as conn:
            if pinned:
                # Reuse the existing letter if any; otherwise assign the next free one.
                cur = conn.execute("SELECT pin_letter FROM items WHERE id = ?", (item_id,))
                row = cur.fetchone()
                current_letter = row["pin_letter"] if row else None
                if current_letter:
                    letter = current_letter
                else:
                    letter = self._next_pin_letter_locked(conn)
                conn.execute(
                    "UPDATE items SET pinned = 1, pin_letter = ? WHERE id = ?",
                    (letter, item_id),
                )
            else:
                conn.execute(
                    "UPDATE items SET pinned = 0, pin_letter = NULL WHERE id = ?",
                    (item_id,),
                )

    def _next_pin_letter_locked(self, conn: sqlite3.Connection) -> Optional[str]:
        used = {
            row["pin_letter"]
            for row in conn.execute(
                "SELECT pin_letter FROM items WHERE pin_letter IS NOT NULL"
            ).fetchall()
            if row["pin_letter"]
        }
        for c in PIN_LETTERS:
            if c not in used:
                return c
        return None  # All 26 letters are in use — pin without a letter.

    def delete(self, item_id: int) -> None:
        with self._tx() as conn:
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))

    def clear_all(self, keep_pinned: bool = True) -> int:
        with self._tx() as conn:
            if keep_pinned:
                cur = conn.execute("DELETE FROM items WHERE pinned = 0")
            else:
                cur = conn.execute("DELETE FROM items")
            return cur.rowcount or 0

    def prune_to_size(self, max_items: int) -> int:
        """Trim oldest unpinned items so total count is <= max_items."""
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM items WHERE pinned = 0")
        unpinned = int(cur.fetchone()["c"])
        # Pinned items are always preserved; only unpinned items count toward the budget.
        cur = self._conn.execute("SELECT COUNT(*) AS c FROM items WHERE pinned = 1")
        pinned = int(cur.fetchone()["c"])
        budget = max(0, max_items - pinned)
        excess = max(0, unpinned - budget)
        if excess <= 0:
            return 0
        with self._tx() as conn:
            cur = conn.execute(
                "DELETE FROM items WHERE id IN ("
                "  SELECT id FROM items WHERE pinned = 0 ORDER BY last_used_at ASC LIMIT ?"
                ")",
                (excess,),
            )
            return cur.rowcount or 0

    def prune_old_images(self, older_than_seconds: int, now: Optional[int] = None) -> int:
        ts = (now if now is not None else int(time.time())) - older_than_seconds
        with self._tx() as conn:
            cur = conn.execute(
                "DELETE FROM items WHERE content_type = 'image' AND pinned = 0 AND last_used_at < ?",
                (ts,),
            )
            return cur.rowcount or 0
