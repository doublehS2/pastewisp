"""Seed an isolated Pastewisp DB with clean, non-sensitive demo items.

Run with XDG_DATA_HOME pointed at a throwaway directory so the demo never
touches real clipboard history. Items are inserted with increasing timestamps
so the most recently 'used' appears first in the popup.
"""
from __future__ import annotations

import io
import os
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


def _sample_png(w: int = 360, h: int = 220) -> bytes:
    """A small, pleasant gradient PNG to demonstrate image clipboard support."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (
                int(60 + 150 * x / w),
                int(90 + 110 * y / h),
                int(200 - 80 * x / w),
            )
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([14, 14, w - 14, h - 14], radius=18, outline=(255, 255, 255), width=3)
    d.ellipse([w // 2 - 34, h // 2 - 34, w // 2 + 34, h // 2 + 34], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    db = Database()
    base = int(time.time()) - (len(DEMO_ITEMS) + 1) * 60
    for i, text in enumerate(DEMO_ITEMS):
        db.upsert_text(text, source_app="demo", now=base + i * 60)
    # Optionally seed an image item (most recent, so it shows at the top) to
    # demonstrate that images can also be stored. Enabled for screenshots only.
    if os.environ.get("PASTEWISP_SEED_IMAGE"):
        w, h = 360, 220
        db.upsert_image(_sample_png(w, h), w, h, source_app="screenshot",
                        now=base + (len(DEMO_ITEMS) + 1) * 60)
    print(f"seeded {db.count()} items at {db.path}")
    db.close()


if __name__ == "__main__":
    main()
