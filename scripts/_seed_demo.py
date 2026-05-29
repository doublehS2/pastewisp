"""Seed an isolated Pastewisp DB with clean, non-sensitive demo items.

Run with XDG_DATA_HOME pointed at a throwaway directory so the demo never
touches real clipboard history. Items are inserted with increasing timestamps
so the most recently 'used' appears first in the popup.
"""
from __future__ import annotations

import time

from pastewisp.db import Database

DEMO_ITEMS = [
    "Pastewisp — clipboard history for Linux",
    "https://github.com/doublehS2/pastewisp",
    "The quick brown fox jumps over the lazy dog",
    "hello@example.com",
    "git commit --amend --no-edit",
    "SELECT * FROM items ORDER BY last_used_at DESC;",
    "def main() -> int:\n    return 0",
    "192.168.1.42",
    "rgb(34, 197, 94)",
    "Meeting notes: ship v0.1.0 on Friday",
]


def main() -> None:
    db = Database()
    base = int(time.time()) - len(DEMO_ITEMS) * 60
    for i, text in enumerate(DEMO_ITEMS):
        db.upsert_text(text, source_app="demo", now=base + i * 60)
    print(f"seeded {db.count()} items at {db.path}")
    db.close()


if __name__ == "__main__":
    main()
