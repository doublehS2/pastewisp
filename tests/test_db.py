from __future__ import annotations

from pathlib import Path

import pytest

from pastewisp.db import Database, image_hash, text_hash


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.sqlite")
    try:
        yield d
    finally:
        d.close()


def test_insert_text_creates_row(db: Database):
    item = db.upsert_text("hello", source_app="gedit", now=1000)
    assert item.id > 0
    assert item.is_text
    assert item.text == "hello"
    assert item.source_app == "gedit"
    assert item.hash == text_hash("hello")
    assert item.created_at == 1000
    assert item.use_count == 1


def test_dedupe_updates_last_used_and_count(db: Database):
    a = db.upsert_text("dup", now=100)
    b = db.upsert_text("dup", now=200)
    assert a.id == b.id
    assert b.last_used_at == 200
    assert b.use_count == 2
    assert db.count() == 1


def test_text_and_image_are_distinct(db: Database):
    db.upsert_text("alpha", now=10)
    db.upsert_image(b"\x89PNGfake", 10, 20, now=20)
    items = db.list_items()
    assert len(items) == 2
    assert {i.content_type for i in items} == {"text", "image"}


def test_image_hash_is_blob_based(db: Database):
    a = db.upsert_image(b"img-a", 1, 1, now=1)
    b = db.upsert_image(b"img-a", 2, 2, now=2)
    assert a.id == b.id
    assert b.last_used_at == 2
    assert image_hash(b"img-a") == a.hash


def test_search_basic(db: Database):
    db.upsert_text("the quick brown fox", now=1)
    db.upsert_text("jumps over lazy dog", now=2)
    db.upsert_text("hello world", now=3)
    hits = [i.text for i in db.search("brown")]
    assert "the quick brown fox" in hits
    assert "hello world" not in hits


def test_search_korean_substring(db: Database):
    db.upsert_text("우분투 클립보드 매니저", now=1)
    db.upsert_text("일반 텍스트", now=2)
    hits = [i.text for i in db.search("클립")]
    assert hits and hits[0] == "우분투 클립보드 매니저"


def test_search_empty_returns_all(db: Database):
    db.upsert_text("a", now=1)
    db.upsert_text("b", now=2)
    assert len(db.search("")) == 2


def test_pin_and_unpin(db: Database):
    item = db.upsert_text("pin me", now=1)
    db.set_pinned(item.id, True)
    refreshed = db.get_by_id(item.id)
    assert refreshed is not None and refreshed.pinned is True
    pinned = db.list_pinned()
    assert len(pinned) == 1
    db.set_pinned(item.id, False)
    assert db.list_pinned() == []


def test_list_items_orders_by_pinned_then_recency(db: Database):
    a = db.upsert_text("a", now=1)
    b = db.upsert_text("b", now=2)
    c = db.upsert_text("c", now=3)
    db.set_pinned(a.id, True)
    items = db.list_items()
    assert items[0].text == "a"  # pinned first
    # Unpinned items follow, sorted by last_used_at DESC.
    assert [i.text for i in items[1:]] == ["c", "b"]


def test_clear_all_keep_pinned(db: Database):
    a = db.upsert_text("a", now=1)
    db.upsert_text("b", now=2)
    db.set_pinned(a.id, True)
    removed = db.clear_all(keep_pinned=True)
    assert removed == 1
    assert db.count() == 1
    assert db.get_by_id(a.id) is not None


def test_clear_all_including_pinned(db: Database):
    a = db.upsert_text("a", now=1)
    db.set_pinned(a.id, True)
    db.upsert_text("b", now=2)
    db.clear_all(keep_pinned=False)
    assert db.count() == 0


def test_prune_to_size_keeps_pinned(db: Database):
    pinned = db.upsert_text("p", now=1)
    db.set_pinned(pinned.id, True)
    for i in range(10):
        db.upsert_text(f"item-{i}", now=10 + i)
    removed = db.prune_to_size(3)
    # 1 pinned + 2 unpinned should remain.
    assert removed == 8
    assert db.count() == 3
    assert db.get_by_id(pinned.id) is not None


def test_prune_old_images(db: Database):
    db.upsert_image(b"old", 1, 1, now=100)
    db.upsert_image(b"new", 1, 1, now=10_000)
    removed = db.prune_old_images(older_than_seconds=1000, now=10_000)
    assert removed == 1
    remaining = db.list_items()
    assert len(remaining) == 1
    assert remaining[0].image_blob == b"new"


def test_delete(db: Database):
    item = db.upsert_text("x", now=1)
    db.delete(item.id)
    assert db.get_by_id(item.id) is None
    assert db.count() == 0


def test_pin_assigns_letter(db: Database):
    a = db.upsert_text("a", now=1)
    b = db.upsert_text("b", now=2)
    db.set_pinned(a.id, True)
    db.set_pinned(b.id, True)
    a2 = db.get_by_id(a.id)
    b2 = db.get_by_id(b.id)
    assert a2.pin_letter == "a"
    assert b2.pin_letter == "b"


def test_unpin_clears_letter(db: Database):
    item = db.upsert_text("p", now=1)
    db.set_pinned(item.id, True)
    assert db.get_by_id(item.id).pin_letter == "a"
    db.set_pinned(item.id, False)
    assert db.get_by_id(item.id).pin_letter is None
    assert db.get_by_id(item.id).pinned is False


def test_pin_reuses_freed_letter(db: Database):
    a = db.upsert_text("a", now=1)
    db.upsert_text("b", now=2)
    db.set_pinned(a.id, True)
    assert db.get_by_id(a.id).pin_letter == "a"
    db.set_pinned(a.id, False)
    # The next pin should reuse the freed 'a'.
    c = db.upsert_text("c", now=3)
    db.set_pinned(c.id, True)
    assert db.get_by_id(c.id).pin_letter == "a"


def test_repin_keeps_same_letter(db: Database):
    item = db.upsert_text("k", now=1)
    db.set_pinned(item.id, True)
    assert db.get_by_id(item.id).pin_letter == "a"
    # Re-pinning an already-pinned item should keep the same letter.
    db.set_pinned(item.id, True)
    assert db.get_by_id(item.id).pin_letter == "a"


def test_pin_letter_runs_out(db: Database):
    items = [db.upsert_text(f"item-{i}", now=i) for i in range(27)]
    for it in items:
        db.set_pinned(it.id, True)
    letters = [db.get_by_id(it.id).pin_letter for it in items]
    assert sorted(letters[:26]) == list("abcdefghijklmnopqrstuvwxyz")
    assert letters[26] is None  # 27th pin gets no letter — alphabet exhausted
