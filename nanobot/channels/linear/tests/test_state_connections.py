"""Store operations release SQLite resources without waiting for cyclic GC."""

import sqlite3
from dataclasses import replace

import pytest

from nanobot.channels.linear.state import LinearInstallation, LinearStateStore


@pytest.fixture
def connections(monkeypatch):
    connect = sqlite3.connect
    opened = []

    def track(*args, **kwargs):
        connection = connect(*args, **kwargs)
        # Keep references so GC cannot hide a missing explicit close.
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", track)
    yield opened
    for connection in opened:
        connection.close()


def _assert_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
            connection.execute("SELECT 1")


def test_store_closes_connections_and_commits_public_operations(tmp_path, connections):
    store = LinearStateStore(tmp_path / "state.sqlite3")
    _assert_closed(connections)
    installation = LinearInstallation("org", "client", "app", "access", "refresh", 1000)
    store.save_installation(installation)
    assert store.has_installations("client")
    saved = store.installation("org")
    assert saved == installation
    assert store.list_installations("client") == [installation]
    assert store.refresh_installation(saved, replace(saved, access_token="rotated"))
    store.set_member_access("client", "org", "user", allowed=True)
    assert store.member_access("client", "org", "user") is True
    assert store.enqueue_webhook("delivery", {"type": "test"})
    assert not store.enqueue_webhook("delivery", {"type": "test"})
    assert len(store.claim_webhooks()) == 1
    store.recover_processing_webhooks()
    assert len(store.claim_webhooks()) == 1
    store.retry_webhook("delivery", "retry", attempts=0)
    store.complete_webhook("delivery")
    assert store.claim_webhooks() == []
    assert store.delete_installation("org")
    assert not store.delete_installation("org")
    assert not store.has_installations()
    _assert_closed(connections)


def test_store_rolls_back_and_closes_after_partial_write(tmp_path, connections):
    store = LinearStateStore(tmp_path / "state.sqlite3")
    assert store.enqueue_webhook("delivery", {"type": "original"})
    # Force the second enqueue statement to fail, after it writes a receipt.
    with store._connect() as connection:
        connection.execute("DELETE FROM webhook_receipts WHERE delivery_id = 'delivery'")

    with pytest.raises(sqlite3.IntegrityError):
        store.enqueue_webhook("delivery", {"type": "duplicate"})
    _assert_closed(connections)

    store.complete_webhook("delivery")
    # The failed enqueue's receipt must have rolled back, not blocked a retry.
    assert store.enqueue_webhook("delivery", {"type": "retry"})
    assert store.claim_webhooks()[0].payload == {"type": "retry"}
    _assert_closed(connections)


def test_store_closes_connection_when_setup_fails(tmp_path, connections):
    path = tmp_path / "state.sqlite3"
    path.write_bytes(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        LinearStateStore(path)
    _assert_closed(connections)
