"""Queue worker coordinating policy, Himalaya, retries, and audit records."""

from __future__ import annotations

import logging
import time
from typing import Protocol

from nanobot_mail_watcher.config import MailAutomationConfig
from nanobot_mail_watcher.himalaya import HimalayaClient, MessageTooLargeError
from nanobot_mail_watcher.models import MailEvent, QueuedMailEvent
from nanobot_mail_watcher.rules import classify, parse_message
from nanobot_mail_watcher.store import LostLeaseError, MailEventStore

logger = logging.getLogger(__name__)


class AmbiguousMoveError(RuntimeError):
    """A previous MOVE may have completed, so it must not be repeated automatically."""


class MailClient(Protocol):
    def uid_validity(self, account: str, mailbox: str) -> str: ...

    def search_uids(self, account: str, mailbox: str) -> tuple[str, ...]: ...

    def read_raw(self, account: str, mailbox: str, uid: str) -> bytes: ...

    def move(self, account: str, source: str, destination: str, uid: str) -> None: ...


class MailWorker:
    def __init__(
        self,
        config: MailAutomationConfig,
        store: MailEventStore | None = None,
        client: MailClient | None = None,
    ) -> None:
        self.config = config
        self.store = store or MailEventStore(config.worker.database)
        self.client = client or HimalayaClient(config.worker)
        self._next_reconcile_at = 0.0

    def recover(self) -> int:
        return self.store.recover_stale(
            self.config.worker.stale_after_seconds,
            max_attempts=self.config.worker.max_attempts,
        )

    def run_batch(self, *, limit: int = 20) -> int:
        # Claim just before processing so later batch items cannot expire while waiting.
        processed = 0
        while processed < limit:
            claimed = self.store.claim(limit=1)
            if not claimed:
                break
            self._process_safely(claimed[0])
            processed += 1
        return processed

    def reconcile(self) -> dict[str, object]:
        """Discover missed messages in every approved source without stopping on one failure."""
        mailboxes = listed = created_count = existing = failed = 0
        errors: list[dict[str, str]] = []
        for account, policy in self.config.accounts.items():
            for mailbox in policy.source_mailboxes:
                mailboxes += 1
                try:
                    before = self.client.uid_validity(account, mailbox)
                    uids = self.client.search_uids(account, mailbox)
                    after = self.client.uid_validity(account, mailbox)
                    if before != after:
                        raise RuntimeError("UIDVALIDITY changed while listing the mailbox")
                    listed += len(uids)
                    for uid in uids:
                        _, created = self.store.enqueue(
                            MailEvent(
                                account,
                                mailbox,
                                uid,
                                before,
                                metadata={"source": "reconcile"},
                            )
                        )
                        if created:
                            created_count += 1
                        else:
                            existing += 1
                except Exception as exc:
                    failed += 1
                    error = " ".join(str(exc).split())[:500] or "reconciliation failed"
                    errors.append({"account": account, "mailbox": mailbox, "error": error})
                    logger.warning(
                        "Mailbox reconciliation failed for %s/%s: %s",
                        account,
                        mailbox,
                        error,
                    )
        return {
            "mailboxes": mailboxes,
            "listed": listed,
            "created": created_count,
            "existing": existing,
            "failed": failed,
            "errors": errors,
        }

    def reconcile_if_due(self, *, now: float | None = None) -> dict[str, object] | None:
        """Run at most once per configured interval; a restart intentionally runs immediately."""
        current = time.monotonic() if now is None else now
        if current < self._next_reconcile_at:
            return None
        self._next_reconcile_at = current + self.config.worker.reconcile_interval_seconds
        return self.reconcile()

    def run_forever(self) -> None:
        recovered = self.recover()
        if recovered:
            logger.warning("Recovered %d interrupted mail event(s)", recovered)
        while True:
            report = self.reconcile_if_due()
            if report is not None:
                logger.info(
                    "Mail reconciliation: %d created, %d existing, %d failed mailbox(es)",
                    report["created"],
                    report["existing"],
                    report["failed"],
                )
            processed = self.run_batch()
            if not processed:
                time.sleep(self.config.worker.poll_seconds)

    def _process_safely(self, queued: QueuedMailEvent) -> None:
        try:
            self._process(queued)
        except LostLeaseError as exc:
            logger.warning("Mail event %d stopped after losing its lease: %s", queued.id, exc)
        except (MessageTooLargeError, AmbiguousMoveError) as exc:
            self.store.fail(
                queued.id,
                queued.claim_token,
                str(exc),
                max_attempts=self.config.worker.max_attempts,
                retry_base_seconds=self.config.worker.retry_base_seconds,
                permanent=True,
            )
            logger.error("Mail event %d permanently failed: %s", queued.id, exc)
        except Exception as exc:
            retry = self.store.fail(
                queued.id,
                queued.claim_token,
                str(exc),
                max_attempts=self.config.worker.max_attempts,
                retry_base_seconds=self.config.worker.retry_base_seconds,
            )
            logger.warning(
                "Mail event %d failed (%s): %s",
                queued.id,
                "retry scheduled" if retry else "permanent failure",
                exc,
            )

    def _process(self, queued: QueuedMailEvent) -> None:
        event = queued.event
        account_config = self.config.accounts.get(event.account)
        if account_config is None:
            raise ValueError(f"unknown configured account: {event.account}")
        if event.mailbox not in account_config.source_mailboxes:
            raise ValueError(
                f"mailbox {event.mailbox!r} is not an approved source for {event.account!r}"
            )

        if queued.action_started:
            raise AmbiguousMoveError(
                "a previous MOVE was started but its result was not committed; manual review required"
            )

        self.store.renew_lease(queued.id, queued.claim_token)
        current_uid_validity = self.client.uid_validity(event.account, event.mailbox)
        if event.uid_validity_known and event.uid_validity != current_uid_validity:
            self.store.complete(
                queued.id,
                queued.claim_token,
                {
                    "outcome": "stale_uid_validity",
                    "expected": event.uid_validity,
                    "current": current_uid_validity,
                },
            )
            return
        if not event.uid_validity_known:
            duplicate_of = self.store.resolve_uid_validity(queued, current_uid_validity)
            if duplicate_of is not None:
                logger.info("Mail event %d duplicates event %d", queued.id, duplicate_of)
                return

        self.store.renew_lease(queued.id, queued.claim_token)
        raw = self.client.read_raw(event.account, event.mailbox, event.uid)
        decision = classify(parse_message(raw), account_config)
        decision_data = decision.as_dict()
        self.store.record_decision(queued.id, queued.claim_token, decision_data)

        if decision.destination is None:
            self.store.complete(
                queued.id,
                queued.claim_token,
                {"decision": decision_data, "outcome": "no_action"},
            )
            return
        if decision.destination not in account_config.allowed_folders:
            raise ValueError("classifier selected a folder outside the account allowlist")
        if self.config.worker.dry_run:
            self.store.complete(
                queued.id,
                queued.claim_token,
                {"decision": decision_data, "outcome": "dry_run"},
            )
            return

        self.store.renew_lease(queued.id, queued.claim_token)
        before_move_uid_validity = self.client.uid_validity(event.account, event.mailbox)
        if before_move_uid_validity != current_uid_validity:
            self.store.complete(
                queued.id,
                queued.claim_token,
                {
                    "decision": decision_data,
                    "outcome": "uid_validity_changed_before_move",
                },
            )
            return
        self.store.record_action_started(queued.id, queued.claim_token, decision_data)
        self.client.move(event.account, event.mailbox, decision.destination, event.uid)
        self.store.complete(
            queued.id,
            queued.claim_token,
            {"decision": decision_data, "outcome": "moved"},
        )
