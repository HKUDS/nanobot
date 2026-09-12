"""Durability, transport independence, acknowledgement races and migration."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from nanobot.webui.notification_store import NotificationStore


def make_store(tmp_path, owner="owner"):
    return NotificationStore(tmp_path / "notifications.json", owner=owner, target="target")


def test_pending_notification_survives_restart_without_telegram(tmp_path):
    make_store(tmp_path).record("Meeting starts soon", "calendar:1", "pending")
    restored = make_store(tmp_path)
    assert restored.rows()[0]["delivery_state"] == "pending"
    restored.record("Meeting starts soon", "calendar:1", "uncertain")
    assert make_store(tmp_path).rows()[0]["delivery_state"] == "uncertain"


def test_delivery_updates_never_duplicate_or_reset_read_state(tmp_path):
    store = make_store(tmp_path)
    store.record("Reminder", "event", "pending")
    store.mark_read(["notification:event"])
    store.record("Reminder", "event", "delivered")
    store.record("Reminder", "event", "pending")
    store.record("Reminder", "event", "uncertain")
    rows = make_store(tmp_path).rows()
    assert len(rows) == 1
    assert rows[0]["read"] is True
    assert rows[0]["delivery_state"] == "delivered"


def test_acknowledgement_does_not_mark_unseen_arrival_read(tmp_path):
    store = make_store(tmp_path)
    store.record("One", "one", "delivered")
    observed = [row["id"] for row in store.rows()]
    store.record("Two", "two", "pending")
    assert store.mark_read(observed) == 1
    assert [row["read"] for row in store.rows()] == [True, False]


def test_concurrent_writers_and_acknowledgements_preserve_all_rows(tmp_path):
    def write(index):
        store = make_store(tmp_path)
        store.record(f"Notice {index}", str(index), "pending")
        store.mark_read([f"notification:{index}"])
        store.record(f"Notice {index}", str(index), "delivered")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(30)))
    rows = make_store(tmp_path).rows()
    assert len(rows) == 30
    assert all(row["read"] and row["delivery_state"] == "delivered" for row in rows)


def test_legacy_receipts_remain_visible_and_owner_isolated(tmp_path):
    store = make_store(tmp_path)
    store.path.write_text(json.dumps({
        "owner": "owner", "target": "target", "messages": [{
            "id": "notification:123", "content": "Legacy", "role": "assistant", "createdAt": 1,
        }],
    }), encoding="utf-8")
    assert store.rows()[0]["delivery_state"] == "delivered"
    assert make_store(tmp_path, "another-owner").rows() == []
    store.mark_read(["notification:123"])
    assert make_store(tmp_path).rows()[0]["read"] is True


def test_corrupt_store_is_not_overwritten(tmp_path):
    store = make_store(tmp_path)
    store.path.write_text('{"owner":', encoding="utf-8")
    with pytest.raises(ValueError):
        store.record("New", "new", "pending")
    assert store.path.read_text(encoding="utf-8") == '{"owner":'
