from pathlib import Path

import pytest

from nanobot_mail_watcher.models import MailEvent
from nanobot_mail_watcher.store import LostLeaseError, MailEventStore


def test_enqueue_is_idempotent_and_audited(tmp_path: Path) -> None:
    store = MailEventStore(tmp_path / "events.sqlite3")
    event = MailEvent("work", "INBOX", "42", "9001")

    first_id, first_created = store.enqueue(event, now=10)
    second_id, second_created = store.enqueue(event, now=11)

    assert first_id == second_id
    assert first_created is True
    assert second_created is False
    assert store.counts()["pending"] == 1
    assert [row["action"] for row in store.audit(first_id)] == ["enqueued"]


def test_retry_backoff_and_stale_recovery(tmp_path: Path) -> None:
    store = MailEventStore(tmp_path / "events.sqlite3")
    event_id, _ = store.enqueue(MailEvent("work", "INBOX", "1", "2"), now=10)
    item = store.claim(now=10)[0]
    assert item.attempts == 1

    assert store.fail(
        event_id,
        item.claim_token,
        "temporary failure",
        max_attempts=3,
        retry_base_seconds=5,
        now=11,
    )
    assert store.claim(now=15) == []
    retry = store.claim(now=16)[0]
    assert retry.attempts == 2

    assert store.recover_stale(10, max_attempts=3, now=25) == 0
    assert store.recover_stale(10, max_attempts=3, now=26) == 1
    assert store.counts()["retry"] == 1


def test_unknown_uidvalidity_is_promoted_and_deduplicated(tmp_path: Path) -> None:
    store = MailEventStore(tmp_path / "events.sqlite3")
    known_id, _ = store.enqueue(MailEvent("work", "INBOX", "7", "99"), now=1)
    known = store.claim(now=1)[0]
    store.complete(known.id, known.claim_token, {"outcome": "done"}, now=2)

    unknown_id, _ = store.enqueue(MailEvent("work", "INBOX", "7"), now=3)
    unknown = store.claim(now=3)[0]
    duplicate_of = store.resolve_uid_validity(unknown, "99", now=4)

    assert duplicate_of == known_id
    assert unknown_id != known_id
    assert store.counts()["done"] == 2
    assert store.audit(unknown_id)[-1]["action"] == "deduplicated"


def test_old_owner_cannot_complete_after_lease_recovery(tmp_path: Path) -> None:
    store = MailEventStore(tmp_path / "events.sqlite3")
    event_id, _ = store.enqueue(MailEvent("work", "INBOX", "8", "99"), now=1)
    old = store.claim(now=1)[0]
    assert store.recover_stale(10, max_attempts=3, now=12) == 1
    new = store.claim(now=12)[0]

    with pytest.raises(LostLeaseError):
        store.complete(event_id, old.claim_token, {"outcome": "old"}, now=13)

    store.complete(event_id, new.claim_token, {"outcome": "new"}, now=13)
    assert store.counts()["done"] == 1


def test_recovery_honors_attempt_budget(tmp_path: Path) -> None:
    store = MailEventStore(tmp_path / "events.sqlite3")
    store.enqueue(MailEvent("work", "INBOX", "9", "99"), now=1)
    store.claim(now=1)

    assert store.recover_stale(10, max_attempts=1, now=12) == 1
    assert store.counts()["failed"] == 1


def test_move_started_marker_survives_retry(tmp_path: Path) -> None:
    store = MailEventStore(tmp_path / "events.sqlite3")
    event_id, _ = store.enqueue(MailEvent("work", "INBOX", "10", "99"), now=1)
    item = store.claim(now=1)[0]
    store.record_action_started(
        event_id,
        item.claim_token,
        {"rule": "orders", "destination": "Orders"},
        now=2,
    )
    assert store.fail(
        event_id,
        item.claim_token,
        "move result unavailable",
        max_attempts=3,
        retry_base_seconds=1,
        now=3,
    )

    retried = store.claim(now=4)[0]
    assert retried.action_started is True
