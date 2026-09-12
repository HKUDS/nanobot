from pathlib import Path

from nanobot_mail_watcher.config import (
    AccountConfig,
    MailAutomationConfig,
    RuleConfig,
    WorkerConfig,
)
from nanobot_mail_watcher.models import MailEvent
from nanobot_mail_watcher.store import MailEventStore
from nanobot_mail_watcher.worker import MailWorker


class FakeMailClient:
    def __init__(
        self,
        validities: list[str] | None = None,
        search_results: dict[tuple[str, str], tuple[str, ...] | Exception] | None = None,
    ) -> None:
        self.moves: list[tuple[str, str, str, str]] = []
        self.reads = 0
        self.validities = validities or ["123"]
        self.search_results = search_results or {}

    def uid_validity(self, account: str, mailbox: str) -> str:
        if len(self.validities) > 1:
            return self.validities.pop(0)
        return self.validities[0]

    def search_uids(self, account: str, mailbox: str) -> tuple[str, ...]:
        result = self.search_results.get((account, mailbox), ())
        if isinstance(result, Exception):
            raise result
        return result

    def read_raw(self, account: str, mailbox: str, uid: str) -> bytes:
        self.reads += 1
        return b"From: news@example.org\r\nSubject: Weekly news\r\n\r\nuntrusted body"

    def move(self, account: str, source: str, destination: str, uid: str) -> None:
        self.moves.append((account, source, destination, uid))


def _config(tmp_path: Path, *, dry_run: bool) -> MailAutomationConfig:
    worker = WorkerConfig(
        database=tmp_path / "events.sqlite3",
        himalaya_binary="/usr/bin/himalaya",
        himalaya_config=None,
        dry_run=dry_run,
        command_timeout_seconds=30,
        max_message_bytes=2_000_000,
        max_attempts=3,
        retry_base_seconds=1,
        stale_after_seconds=300,
        poll_seconds=0.1,
    )
    account = AccountConfig(
        source_mailboxes=("INBOX",),
        allowed_folders=frozenset({"Newsletters"}),
        unmatched_destination=None,
        rules=(
            RuleConfig(
                name="newsletter",
                destination="Newsletters",
                sender_globs=("news@*",),
            ),
        ),
    )
    return MailAutomationConfig(tmp_path / "mail.toml", worker, {"work": account})


def test_dry_run_classifies_without_moving(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=True)
    store = MailEventStore(config.worker.database)
    event_id, _ = store.enqueue(MailEvent("work", "INBOX", "5"))
    client = FakeMailClient()

    assert MailWorker(config, store, client).run_batch() == 1
    assert client.moves == []
    assert store.counts()["done"] == 1
    audit = store.audit(event_id)
    assert audit[-1]["details"]["outcome"] == "dry_run"
    assert "sender" not in str(audit)
    assert "subject" not in str(audit)


def test_enabled_worker_moves_only_to_allowlisted_rule_destination(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=False)
    store = MailEventStore(config.worker.database)
    store.enqueue(MailEvent("work", "INBOX", "5"))
    client = FakeMailClient()

    MailWorker(config, store, client).run_batch()

    assert client.moves == [("work", "INBOX", "Newsletters", "5")]
    assert store.counts()["done"] == 1


def test_known_stale_uidvalidity_never_reads_or_moves(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=False)
    store = MailEventStore(config.worker.database)
    store.enqueue(MailEvent("work", "INBOX", "5", "122"))
    client = FakeMailClient(["123"])

    MailWorker(config, store, client).run_batch()

    assert client.reads == 0
    assert client.moves == []
    assert store.counts()["done"] == 1


def test_uidvalidity_change_immediately_before_move_aborts_move(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=False)
    store = MailEventStore(config.worker.database)
    store.enqueue(MailEvent("work", "INBOX", "5"))
    client = FakeMailClient(["123", "124"])

    MailWorker(config, store, client).run_batch()

    assert client.reads == 1
    assert client.moves == []
    assert store.counts()["done"] == 1


def test_reconcile_enqueues_known_uids_idempotently(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=True)
    store = MailEventStore(config.worker.database)
    client = FakeMailClient(
        ["123", "123", "123", "123"],
        {("work", "INBOX"): ("5", "8")},
    )
    worker = MailWorker(config, store, client)

    first = worker.reconcile()
    second = worker.reconcile()

    assert first["created"] == 2
    assert first["existing"] == 0
    assert second["created"] == 0
    assert second["existing"] == 2
    assert store.counts()["pending"] == 2


def test_reconcile_discards_listing_when_uidvalidity_changes(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=True)
    store = MailEventStore(config.worker.database)
    client = FakeMailClient(["123", "124"], {("work", "INBOX"): ("5",)})

    report = MailWorker(config, store, client).reconcile()

    assert report["failed"] == 1
    assert report["created"] == 0
    assert store.counts()["pending"] == 0


def test_reconcile_isolates_mailbox_failures_and_obeys_interval(tmp_path: Path) -> None:
    config = _config(tmp_path, dry_run=True)
    config = MailAutomationConfig(
        config.path,
        config.worker,
        {
            "broken": AccountConfig(("INBOX",), frozenset(), None, ()),
            "work": config.accounts["work"],
        },
    )
    store = MailEventStore(config.worker.database)
    client = FakeMailClient(
        ["123"],
        {
            ("broken", "INBOX"): RuntimeError("offline"),
            ("work", "INBOX"): ("9",),
        },
    )
    worker = MailWorker(config, store, client)

    first = worker.reconcile_if_due(now=0)
    skipped = worker.reconcile_if_due(now=179)
    second = worker.reconcile_if_due(now=180)

    assert first is not None and first["failed"] == 1 and first["created"] == 1
    assert skipped is None
    assert second is not None and second["failed"] == 1 and second["existing"] == 1
