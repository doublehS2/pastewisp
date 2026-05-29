from __future__ import annotations

from pathlib import Path

import pytest

from pastewisp.config import Config
from pastewisp.db import Database
from pastewisp.history import HistoryManager, is_excluded_app


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "h.sqlite")
    try:
        yield d
    finally:
        d.close()


@pytest.fixture()
def history(db: Database) -> HistoryManager:
    return HistoryManager(db, Config())


def test_add_text_inserts_then_dedupes(history: HistoryManager):
    r1 = history.add_text("hello", source_app="gedit", now=100)
    assert r1.reason == "inserted"
    assert r1.item is not None
    r2 = history.add_text("hello", source_app="gedit", now=200)
    assert r2.reason == "updated"
    assert r2.item is not None and r2.item.id == r1.item.id
    assert r2.item.use_count == 2


def test_add_text_empty_is_skipped(history: HistoryManager):
    assert history.add_text("").reason == "skipped:empty"
    assert history.add_text("   \n\t").reason == "skipped:empty"


def test_excluded_app_is_skipped(history: HistoryManager):
    # config default includes 'keepassxc'
    r = history.add_text("secret", source_app="org.keepassxc.KeePassXC", now=1)
    assert r.reason == "skipped:excluded"
    assert history.db.count() == 0


def test_excluded_match_is_case_insensitive():
    assert is_excluded_app("KeePassXC", ["keepassxc"])
    assert is_excluded_app("KeePassXC", ["KEEPASS"])
    assert not is_excluded_app("gedit", ["keepassxc"])
    assert not is_excluded_app(None, ["keepassxc"])
    assert not is_excluded_app("anything", [])


def test_add_image_too_large_is_skipped(db: Database):
    cfg = Config().with_storage(max_image_bytes=10)
    h = HistoryManager(db, cfg)
    r = h.add_image(b"x" * 100, 1, 1)
    assert r.reason == "skipped:too-large"
    assert db.count() == 0


def test_size_limit_enforced_on_insert(db: Database):
    cfg = Config().with_general(history_limit=3)
    h = HistoryManager(db, cfg)
    for i in range(5):
        h.add_text(f"item-{i}", now=i)
    assert db.count() == 3
    remaining = [i.text for i in h.list_items()]
    # Only the 3 most recent items should remain.
    assert remaining == ["item-4", "item-3", "item-2"]


def test_pin_then_size_limit_protects_pinned(db: Database):
    cfg = Config().with_general(history_limit=2)
    h = HistoryManager(db, cfg)
    a = h.add_text("a", now=1).item
    assert a is not None
    h.pin(a.id)
    for i in range(5):
        h.add_text(f"item-{i}", now=10 + i)
    # 1 pinned + 1 unpinned = 2 items kept.
    assert db.count() == 2
    items = h.list_items()
    assert items[0].id == a.id
    assert items[1].text == "item-4"


def test_toggle_pin(history: HistoryManager):
    item = history.add_text("p", now=1).item
    assert item is not None
    assert history.toggle_pin(item.id) is True
    assert history.toggle_pin(item.id) is False


def test_search_delegates_to_db(history: HistoryManager):
    history.add_text("alpha beta", now=1)
    history.add_text("gamma delta", now=2)
    hits = [i.text for i in history.search("alpha")]
    assert hits == ["alpha beta"]


def test_clear_all_keeps_pinned(history: HistoryManager):
    a = history.add_text("a", now=1).item
    assert a is not None
    history.add_text("b", now=2)
    history.pin(a.id)
    removed = history.clear_all(keep_pinned=True)
    assert removed == 1
    assert history.db.count() == 1


def test_prune_runs_size_and_image(db: Database):
    cfg = Config().with_general(history_limit=100).with_storage(keep_images_days=1)
    h = HistoryManager(db, cfg)
    for i in range(110):
        h.add_text(f"t-{i}", now=i)
    # Give images timestamps newer than the texts so they survive the size cap.
    h.add_image(b"old-img", 1, 1, now=200)
    h.add_image(b"new-img", 1, 1, now=10_000_000)
    size_removed, image_removed = h.prune(now=10_000_000)
    # Each add_text already enforces the size cap, so size_removed should be 0
    # here; only images are pruned by the older-than-N-days policy.
    assert image_removed == 1
    assert size_removed == 0
