"""Typed records used by the mailbox automation boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

UNKNOWN_UID_VALIDITY = "unknown"


@dataclass(frozen=True, slots=True)
class MailEvent:
    """A notification identifying one message in one IMAP UID namespace."""

    account: str
    mailbox: str
    uid: str
    uid_validity: str = UNKNOWN_UID_VALIDITY
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        account = self.account.strip()
        # LIST returns opaque mailbox IDs: trimming can redirect a UID to a
        # different folder. Only INBOX is case-insensitive in IMAP.
        mailbox = "INBOX" if self.mailbox.casefold() == "inbox" else self.mailbox
        uid = self.uid.strip()
        uid_validity = self.uid_validity.strip().lower()
        if not account or len(account) > 128 or "\x00" in account:
            raise ValueError("account must be non-empty and at most 128 characters")
        if not mailbox.strip() or len(mailbox) > 1024 or any(ch in mailbox for ch in "\r\n\x00"):
            raise ValueError("mailbox is empty or contains forbidden characters")
        if mailbox.startswith("-"):
            raise ValueError("mailbox names beginning with '-' are not supported")
        if not uid.isascii() or not uid.isdigit() or len(uid) > 20 or int(uid) < 1:
            raise ValueError("uid must be a positive decimal IMAP UID")
        if uid_validity != UNKNOWN_UID_VALIDITY:
            if (
                not uid_validity.isascii()
                or not uid_validity.isdigit()
                or len(uid_validity) > 20
                or int(uid_validity) < 1
            ):
                raise ValueError("uid_validity must be 'unknown' or a positive decimal number")
        encoded_metadata = json.dumps(self.metadata, ensure_ascii=False, sort_keys=True)
        if len(encoded_metadata.encode("utf-8")) > 16_384:
            raise ValueError("event metadata exceeds 16 KiB")
        object.__setattr__(self, "account", account)
        object.__setattr__(self, "mailbox", mailbox)
        object.__setattr__(self, "uid", uid)
        object.__setattr__(self, "uid_validity", uid_validity)

    @property
    def event_key(self) -> str:
        identity = json.dumps(
            [self.account, self.mailbox, self.uid_validity, self.uid],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(identity).hexdigest()

    @property
    def uid_validity_known(self) -> bool:
        return self.uid_validity != UNKNOWN_UID_VALIDITY


@dataclass(frozen=True, slots=True)
class QueuedMailEvent:
    id: int
    event: MailEvent
    status: str
    attempts: int
    created_at: float
    available_at: float
    claim_token: str
    action_started: bool = False
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    sender: str
    subject: str
    headers: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    rule: str | None
    destination: str | None
    sender: str
    subject: str

    def as_dict(self) -> dict[str, str | None]:
        """Return the minimum audit record, intentionally excluding personal headers."""
        return {
            "rule": self.rule,
            "destination": self.destination,
        }
