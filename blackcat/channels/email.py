"""Email channel implementation using IMAP polling + SMTP replies."""

import asyncio
import html
import imaplib
import mimetypes
import re
import smtplib
import ssl
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field

from blackcat.bus.events import OutboundMessage
from blackcat.bus.queue import MessageBus
from blackcat.channels.base import BaseChannel
from blackcat.config.paths import get_media_dir
from blackcat.config.schema import Base
from blackcat.utils.helpers import safe_filename


class EmailConfig(Base):
    """Email channel configuration (IMAP inbound + SMTP outbound)."""

    enabled: bool = False
    consent_granted: bool = False

    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""

    auto_reply_enabled: bool = True
    poll_interval_seconds: int = 30
    mark_seen: bool = True
    post_action: Literal["delete", "move"] | None = None
    post_action_move_mailbox: str | None = None
    post_action_expunge: bool = False
    post_action_ignore_skipped: bool = True
    max_body_chars: int = 12000
    subject_prefix: str = "Re: "
    allow_from: list[str] = Field(default_factory=list)

    # Email authentication verification (anti-spoofing)
    verify_dkim: bool = True   # Require Authentication-Results with dkim=pass
    verify_spf: bool = True    # Require Authentication-Results with spf=pass

    # Attachment handling — set allowed types to enable (e.g. ["application/pdf", "image/*"], or ["*"] for all)
    allowed_attachment_types: list[str] = Field(default_factory=list)
    max_attachment_size: int = 2_000_000  # 2MB per attachment
    max_attachments_per_email: int = 5


@dataclass
class _ServerFeatures:
    move: bool
    uidplus: bool
    uid_store: bool | None = None


class EmailChannel(BaseChannel):
    """
    Email channel.

    Inbound:
    - Poll IMAP mailbox for unread messages.
    - Convert each message into an inbound event.

    Outbound:
    - Send responses via SMTP back to the sender address.
    """

    name = "email"
    display_name = "Email"
    _IMAP_MONTHS = (
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    )
    _IMAP_RECONNECT_MARKERS = (
        "disconnected for inactivity",
        "eof occurred in violation of protocol",
        "socket error",
        "connection reset",
        "broken pipe",
        "bye",
    )
    _IMAP_MISSING_MAILBOX_MARKERS = (
        "mailbox doesn't exist",
        "select failed",
        "no such mailbox",
        "can't open mailbox",
        "does not exist",
    )

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return EmailConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = EmailConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: EmailConfig = config
        self._self_addresses = self._collect_self_addresses()
        self._last_subject_by_chat: dict[str, str] = {}
        self._last_message_id_by_chat: dict[str, str] = {}
        self._processed_uids: set[str] = set()  # Capped to prevent unbounded growth
        self._MAX_PROCESSED_UIDS = 100000

    async def start(self) -> None:
        """Start polling IMAP for inbound emails."""
        if not self.config.consent_granted:
            self.logger.warning(
                "Email channel disabled: consent_granted is false. "
                "Set channels.email.consentGranted=true after explicit user permission."
            )
            return

        if not self._validate_config():
            return

        self._running = True
        if not self.config.verify_dkim and not self.config.verify_spf:
            self.logger.warning(
                "DKIM and SPF verification are both DISABLED. "
                "Emails with spoofed From headers will be accepted. "
                "Set verify_dkim=true and verify_spf=true for anti-spoofing protection."
            )
        self.logger.info("Starting Email channel (IMAP polling mode)...")

        poll_seconds = max(5, int(self.config.poll_interval_seconds))
        while self._running:
            try:
                inbound_items, skipped_uids = await asyncio.to_thread(self._fetch_new_messages)
                should_apply_post_action = self._should_apply_post_action()
                post_actions_uids: set[str] = set()
                for item in inbound_items:
                    sender = item["sender"]
                    subject = item.get("subject", "")
                    message_id = item.get("message_id", "")

                    if subject:
                        self._last_subject_by_chat[sender] = subject
                    if message_id:
                        self._last_message_id_by_chat[sender] = message_id

                    try:
                        await self._handle_message(
                            sender_id=sender,
                            chat_id=sender,
                            content=item["content"],
                            media=item.get("media") or None,
                            metadata=item.get("metadata", {}),
                        )
                    except Exception:
                        self.logger.exception("Error delivering email from {}", sender)
                        continue

                    uid = str((item.get("metadata") or {}).get("uid") or "")
                    if uid and should_apply_post_action:
                        post_actions_uids.add(uid)

                if should_apply_post_action and not self.config.post_action_ignore_skipped:
                    post_actions_uids.update(skipped_uids)

                if post_actions_uids:
                    await asyncio.to_thread(self._apply_post_actions_batch, sorted(post_actions_uids))
            except Exception:
                self.logger.exception("Polling error")

            await asyncio.sleep(poll_seconds)

    async def stop(self) -> None:
        """Stop polling loop."""
        self._running = False

    async def _send_impl(self, msg: OutboundMessage) -> None:
        """Send email via SMTP."""
        if not self.config.consent_granted:
            self.logger.warning("Skip email send: consent_granted is false")
            return

        if not self.config.smtp_host:
            self.logger.warning("SMTP host not configured")
            return

        # Skip progress messages to prevent sending an empty email after each tool call
        if (msg.metadata or {}).get("_progress"):
            self.logger.debug("Skip progress message to {}", msg.chat_id)
            return

        to_addr = msg.chat_id.strip()
        if not to_addr:
            self.logger.warning("Missing recipient address")
            return

        # Determine if this is a reply (recipient has sent us an email before)
        is_reply = to_addr in self._last_subject_by_chat
        force_send = bool((msg.metadata or {}).get("force_send"))

        # autoReplyEnabled only controls automatic replies, not proactive sends
        if is_reply and not self.config.auto_reply_enabled and not force_send:
            self.logger.info("Skip automatic reply to {}: auto_reply_enabled is false", to_addr)
            return

        base_subject = self._last_subject_by_chat.get(to_addr, "blackcat reply")
        subject = self._reply_subject(base_subject)
        if msg.metadata and isinstance(msg.metadata.get("subject"), str):
            override = msg.metadata["subject"].strip()
            if override:
                subject = override

        attachments: list[tuple[bytes, str, str, str]] = []
        failed_attachments: list[str] = []
        max_attachment_size = max(0, int(self.config.max_attachment_size))
        max_attachment_count = max(0, int(self.config.max_attachments_per_email))
        for media_path in msg.media or []:
            path = Path(media_path)
            filename = path.name or "attachment"
            if len(attachments) >= max_attachment_count:
                failed_attachments.append(f"[attachment: {filename} - too many attachments]")
                self.logger.warning("Attachment count limit reached, skipping: {}", media_path)
                continue
            if not path.is_file():
                failed_attachments.append(f"[attachment: {filename} - send failed]")
                self.logger.warning("Attachment not found, skipping: {}", media_path)
                continue
            try:
                size = path.stat().st_size
                if max_attachment_size <= 0 or size > max_attachment_size:
                    failed_attachments.append(f"[attachment: {filename} - too large]")
                    self.logger.warning(
                        "Attachment too large, skipping: {} ({} > {} bytes)",
                        media_path,
                        size,
                        max_attachment_size,
                    )
                    continue
                data = path.read_bytes()
                ctype, _ = mimetypes.guess_type(str(path))
                if ctype is None:
                    ctype = "application/octet-stream"
                maintype, subtype = ctype.split("/", 1)
                attachments.append((data, maintype, subtype, filename))
                self.logger.info("Attached file: {}", filename)
            except Exception:
                failed_attachments.append(f"[attachment: {filename} - send failed]")
                self.logger.exception("Failed to attach file {}", media_path)

        content = msg.content or ""
        if failed_attachments:
            fallback = "\n".join(failed_attachments)
            content = f"{content.rstrip()}\n\n{fallback}" if content.strip() else fallback

        email_msg = EmailMessage()
        email_msg["From"] = self.config.from_address or self.config.smtp_username or self.config.imap_username
        email_msg["To"] = to_addr
        email_msg["Subject"] = subject
        email_msg.set_content(content)

        for data, maintype, subtype, filename in attachments:
            email_msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=filename,
            )

        in_reply_to = self._last_message_id_by_chat.get(to_addr)
        if in_reply_to:
            email_msg["In-Reply-To"] = in_reply_to
            email_msg["References"] = in_reply_to

        try:
            await asyncio.to_thread(self._smtp_send, email_msg)
        except Exception:
            self.logger.exception("Error sending to {}", to_addr)
            raise

    def _validate_config(self) -> bool:
        missing = []
        if not self.config.imap_host:
            missing.append("imap_host")
        if not self.config.imap_username:
            missing.append("imap_username")
        if not self.config.imap_password:
            missing.append("imap_password")
        if not self.config.smtp_host:
            missing.append("smtp_host")
        if not self.config.smtp_username:
            missing.append("smtp_username")
        if not self.config.smtp_password:
            missing.append("smtp_password")

        if self.config.post_action == "move" and not (self.config.post_action_move_mailbox or "").strip():
            missing.append("post_action_move_mailbox")

        if missing:
            self.logger.error("Channel not configured, missing: {}", ', '.join(missing))
            return False
        return True

    def _smtp_send(self, msg: EmailMessage) -> None:
        timeout = 30
        if self.config.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=timeout,
            ) as smtp:
                smtp.login(self.config.smtp_username, self.config.smtp_password)
                smtp.send_message(msg)
            return

        with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=timeout) as smtp:
            if self.config.smtp_use_tls:
                smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.config.smtp_username, self.config.smtp_password)
            smtp.send_message(msg)

    def _fetch_new_messages(self) -> tuple[list[dict[str, Any]], set[str]]:
        """Poll IMAP and return parsed unread messages plus skipped message UIDs."""
        return self._fetch_messages(
            search_criteria=("UNSEEN",),
            mark_seen=self.config.mark_seen,
            dedupe=True,
            limit=0,
        )

    def fetch_messages_between_dates(
        self,
        start_date: date,
        end_date: date,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Fetch messages in [start_date, end_date) by IMAP date search.

        This is used for historical summarization tasks (e.g. "yesterday").
        """
        if end_date <= start_date:
            return []

        messages, _ = self._fetch_messages(
            search_criteria=(
                "SINCE",
                self._format_imap_date(start_date),
                "BEFORE",
                self._format_imap_date(end_date),
            ),
            mark_seen=False,
            dedupe=False,
            limit=max(1, int(limit)),
        )
        return messages

    def _fetch_messages(
        self,
        search_criteria: tuple[str, ...],
        mark_seen: bool,
        dedupe: bool,
        limit: int,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        messages: list[dict[str, Any]] = []
        skipped_uids: set[str] = set()
        cycle_uids: set[str] = set()

        for attempt in range(2):
            try:
                self._fetch_messages_once(
                    search_criteria,
                    mark_seen,
                    dedupe,
                    limit,
                    messages,
                    skipped_uids,
                    cycle_uids,
                )
                return messages, skipped_uids
            except Exception as exc:
                if attempt == 1 or not self._is_stale_imap_error(exc):
                    raise
                self.logger.warning("IMAP connection went stale, retrying once: {}", exc)

        return messages, skipped_uids

    def _fetch_messages_once(
        self,
        search_criteria: tuple[str, ...],
        mark_seen: bool,
        dedupe: bool,
        limit: int,
        messages: list[dict[str, Any]],
        skipped_uids: set[str],
        cycle_uids: set[str],
    ) -> None:
        """Fetch messages by arbitrary IMAP search criteria."""
        mailbox = self.config.imap_mailbox or "INBOX"

        client = self._open_imap_client(mailbox=mailbox, missing_mailbox_ok=True)
        if client is None:
            return messages

        try:
            status, data = client.search(None, *search_criteria)
            if status != "OK" or not data:
                return messages

            ids = data[0].split()
            if limit > 0 and len(ids) > limit:
                ids = ids[-limit:]
            for imap_id in ids:
                status, fetched = client.fetch(imap_id, "(BODY.PEEK[] UID)")
                if status != "OK" or not fetched:
                    continue

                raw_bytes = self._extract_message_bytes(fetched)
                if raw_bytes is None:
                    continue

                uid = self._extract_uid(fetched)
                if uid and uid in cycle_uids:
                    continue
                if dedupe and uid and uid in self._processed_uids:
                    continue

                parsed = BytesParser(policy=policy.default).parsebytes(raw_bytes)
                sender = parseaddr(parsed.get("From", ""))[1].strip().lower()
                if not sender:
                    continue
                if self._is_self_address(sender):
                    self.logger.info("From {} ignored: matches bot-owned address", sender)
                    self._remember_processed_uid(uid, dedupe, cycle_uids)
                    if mark_seen:
                        client.store(imap_id, "+FLAGS", "\\Seen")
                    if uid:
                        skipped_uids.add(uid)
                    continue

                # --- Anti-spoofing: verify Authentication-Results ---
                spf_pass, dkim_pass = self._check_authentication_results(parsed)
                if self.config.verify_spf and not spf_pass:
                    self.logger.warning(
                        "From {} rejected: SPF verification failed "
                        "(no 'spf=pass' in Authentication-Results header)",
                        sender,
                    )
                    self._remember_processed_uid(uid, dedupe, cycle_uids)
                    if uid:
                        skipped_uids.add(uid)
                    continue
                if self.config.verify_dkim and not dkim_pass:
                    self.logger.warning(
                        "From {} rejected: DKIM verification failed "
                        "(no 'dkim=pass' in Authentication-Results header)",
                        sender,
                    )
                    self._remember_processed_uid(uid, dedupe, cycle_uids)
                    if uid:
                        skipped_uids.add(uid)
                    continue

                if not self.is_allowed(sender):
                    self._remember_processed_uid(uid, dedupe, cycle_uids)
                    if mark_seen:
                        client.store(imap_id, "+FLAGS", "\\Seen")
                    if uid:
                        skipped_uids.add(uid)
                    continue

                subject = self._decode_header_value(parsed.get("Subject", ""))
                date_value = parsed.get("Date", "")
                message_id = parsed.get("Message-ID", "").strip()
                body = self._extract_text_body(parsed)

                if not body:
                    body = "(empty email body)"

                body = body[: self.config.max_body_chars]
                content = (
                    f"[EMAIL-CONTEXT] Email received.\n"
                    f"From: {sender}\n"
                    f"Subject: {subject}\n"
                    f"Date: {date_value}\n\n"
                    f"{body}"
                )

                # --- Attachment extraction ---
                attachment_paths: list[str] = []
                if self.config.allowed_attachment_types:
                    saved = self._extract_attachments(
                        parsed,
                        uid or "noid",
                        allowed_types=self.config.allowed_attachment_types,
                        max_size=self.config.max_attachment_size,
                        max_count=self.config.max_attachments_per_email,
                    )
                    for p in saved:
                        attachment_paths.append(str(p))
                        content += f"\n[attachment: {p.name} — saved to {p}]"

                metadata = {
                    "message_id": message_id,
                    "subject": subject,
                    "date": date_value,
                    "sender_email": sender,
                    "uid": uid,
                }
                messages.append(
                    {
                        "sender": sender,
                        "subject": subject,
                        "message_id": message_id,
                        "content": content,
                        "metadata": metadata,
                        "media": attachment_paths,
                    }
                )

                self._remember_processed_uid(uid, dedupe, cycle_uids)

                if mark_seen:
                    client.store(imap_id, "+FLAGS", "\\Seen")
        finally:
            self._close_imap_client(client)

    def _open_imap_client(self, mailbox: str, *, missing_mailbox_ok: bool = False) -> Any | None:
        if self.config.imap_use_ssl:
            client: Any = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
        else:
            client = imaplib.IMAP4(self.config.imap_host, self.config.imap_port)

        try:
            client.login(self.config.imap_username, self.config.imap_password)
            try:
                status, _ = client.select(mailbox)
            except Exception as exc:
                if missing_mailbox_ok and self._is_missing_mailbox_error(exc):
                    self.logger.warning("Mailbox unavailable, skipping poll for {}: {}", mailbox, exc)
                    self._close_imap_client(client)
                    return None
                raise

            if status != "OK":
                self.logger.warning("Mailbox select returned {}, skipping poll for {}", status, mailbox)
                self._close_imap_client(client)
                return None
        except Exception:
            self._close_imap_client(client)
            raise

        return client

    @staticmethod
    def _close_imap_client(client: Any) -> None:
        with suppress(Exception):
            client.logout()

    def _collect_self_addresses(self) -> set[str]:
        """Return normalized email addresses owned by this channel instance."""
        candidates = (
            self.config.from_address,
            self.config.smtp_username,
            self.config.imap_username,
        )
        normalized = {
            addr
            for candidate in candidates
            if (addr := self._normalize_address(candidate))
        }
        return normalized

    @staticmethod
    def _normalize_address(value: str) -> str:
        """Normalize an address or mailbox-like identifier for comparisons."""
        raw = (value or "").strip()
        if not raw:
            return ""
        parsed = parseaddr(raw)[1].strip().lower()
        if parsed:
            return parsed
        if "@" in raw:
            return raw.lower()
        return ""

    def _is_self_address(self, sender: str) -> bool:
        """Return True when an inbound sender belongs to the bot itself."""
        normalized_sender = self._normalize_address(sender)
        return bool(normalized_sender) and normalized_sender in self._self_addresses

    def _remember_processed_uid(self, uid: str, dedupe: bool, cycle_uids: set[str]) -> None:
        """Track a fetched UID so skipped messages are not reprocessed forever."""
        if not uid:
            return
        cycle_uids.add(uid)
        if dedupe:
            self._processed_uids.add(uid)
            # mark_seen is the primary dedup; this set is a safety net
            if len(self._processed_uids) > self._MAX_PROCESSED_UIDS:
                # Evict a random half to cap memory; mark_seen is the primary dedup
                self._processed_uids = set(list(self._processed_uids)[len(self._processed_uids) // 2:])

    def _should_apply_post_action(self) -> bool:
        return self.config.post_action in {"delete", "move"}

    def _apply_post_actions_batch(self, post_actions_uids: list[str]) -> None:
        if not self._should_apply_post_action() or not post_actions_uids:
            return

        mailbox = self.config.imap_mailbox or "INBOX"
        client = self._open_imap_client(mailbox=mailbox)
        if client is None:
            return

        try:
            features = self._server_features(client)
            # Apply all post-actions in one IMAP session. `features` also carries
            # session-learned behavior (e.g. UID STORE support) so later UIDs can
            # skip known-broken paths.
            for uid in post_actions_uids:
                if uid:
                    self._apply_post_action(client, uid, features)
        finally:
            self._close_imap_client(client)

    def _apply_post_action(
        self,
        client: Any,
        uid: str,
        features: _ServerFeatures,
    ) -> None:
        action = self.config.post_action

        if action == "delete":
            if not self._uid_store_deleted(client, uid, features):
                return
            self._uid_expunge_or_fallback(client, uid, features)
            return

        if action == "move":
            target = (self.config.post_action_move_mailbox or "").strip()
            if features.move:
                status, _ = client.uid("MOVE", uid, target)
                if status != "OK":
                    self.logger.warning("Post-action move failed (UID MOVE) for UID {} to mailbox {}", uid, target)
                return

            status, _ = client.uid("COPY", uid, target)
            if status != "OK":
                self.logger.warning("Post-action move failed (UID COPY) for UID {} to mailbox {}", uid, target)
                return
            if not self._uid_store_deleted(client, uid, features):
                return
            self._uid_expunge_or_fallback(client, uid, features)

    @staticmethod
    def _server_features(client: Any) -> _ServerFeatures:
        caps: set[str] = set()
        with suppress(Exception):
            status, data = client.capability()
            if status == "OK" and data:
                for raw in data:
                    if isinstance(raw, (bytes, bytearray)):
                        caps.update(token.upper() for token in raw.decode("utf-8", errors="ignore").split())
                    elif isinstance(raw, str):
                        caps.update(token.upper() for token in raw.split())
        return _ServerFeatures(move="MOVE" in caps, uidplus="UIDPLUS" in caps)

    @staticmethod
    def _lookup_imap_id_by_uid(client: Any, uid: str) -> bytes | None:
        # IMAP exposes two message identifiers: UID (stable) and sequence number
        # (session-local). We target by UID first, but some servers may reject
        # UID STORE. In that case we resolve the current sequence number for the
        # UID and retry with STORE using that sequence id.
        status, data = client.search(None, "UID", uid)
        if status != "OK" or not data or not data[0]:
            return None
        return data[0].split()[0]

    def _uid_store_deleted(self, client: Any, uid: str, features: _ServerFeatures) -> bool:
        # Optimistic path: try UID STORE first because UID is stable and avoids
        # sequence-number lookup. If this fails once for the session, remember it
        # and use the sequence STORE fallback directly for remaining UIDs.
        if features.uid_store is not False:
            status, _ = client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            if status == "OK":
                features.uid_store = True
                return True
            features.uid_store = False

        # Compatibility fallback for servers where UID STORE is unavailable or
        # unreliable: resolve the current sequence number from UID and use STORE.
        imap_id = self._lookup_imap_id_by_uid(client, uid)
        if not imap_id:
            self.logger.warning("Post-action skipped: UID {} not found", uid)
            return False

        status, _ = client.store(imap_id, "+FLAGS", "\\Deleted")
        if status != "OK":
            self.logger.warning("Post-action failed: could not mark UID {} as deleted", uid)
            return False
        return True

    def _uid_expunge_or_fallback(self, client: Any, uid: str, features: _ServerFeatures) -> None:
        # Prefer UID-scoped expunge when supported to avoid expunging unrelated
        # messages already marked \Deleted in the selected mailbox.
        if features.uidplus:
            status, _ = client.uid("EXPUNGE", uid)
            if status == "OK":
                return
            self.logger.warning("UID EXPUNGE failed for UID {}, falling back to EXPUNGE", uid)
            if not self.config.post_action_expunge:
                return
        # No UIDPLUS: a plain EXPUNGE is the only way to actually remove
        # messages marked \Deleted via the sequence-number STORE fallback —
        # without it the delete post-action silently no-ops on such servers.
        client.expunge()

    @classmethod
    def _is_stale_imap_error(cls, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in cls._IMAP_RECONNECT_MARKERS)

    @classmethod
    def _is_missing_mailbox_error(cls, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in cls._IMAP_MISSING_MAILBOX_MARKERS)

    @classmethod
    def _format_imap_date(cls, value: date) -> str:
        """Format date for IMAP search (always English month abbreviations)."""
        month = cls._IMAP_MONTHS[value.month - 1]
        return f"{value.day:02d}-{month}-{value.year}"

    @staticmethod
    def _extract_message_bytes(fetched: list[Any]) -> bytes | None:
        for item in fetched:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], (bytes, bytearray)):
                return bytes(item[1])
        return None

    @staticmethod
    def _extract_uid(fetched: list[Any]) -> str:
        for item in fetched:
            if isinstance(item, tuple) and item and isinstance(item[0], (bytes, bytearray)):
                head = bytes(item[0]).decode("utf-8", errors="ignore")
                m = re.search(r"UID\s+(\d+)", head)
                if m:
                    return m.group(1)
        return ""

    @staticmethod
    def _decode_header_value(value: str) -> str:
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @classmethod
    def _extract_text_body(cls, msg: Any) -> str:
        """Best-effort extraction of readable body text."""
        if msg.is_multipart():
            plain_parts: list[str] = []
            html_parts: list[str] = []
            for part in msg.walk():
                if part.get_content_disposition() == "attachment":
                    continue
                content_type = part.get_content_type()
                try:
                    payload = part.get_content()
                except Exception:
                    payload_bytes = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    payload = payload_bytes.decode(charset, errors="replace")
                if not isinstance(payload, str):
                    continue
                if content_type == "text/plain":
                    plain_parts.append(payload)
                elif content_type == "text/html":
                    html_parts.append(payload)
            if plain_parts:
                return "\n\n".join(plain_parts).strip()
            if html_parts:
                return cls._html_to_text("\n\n".join(html_parts)).strip()
            return ""

        try:
            payload = msg.get_content()
        except Exception:
            payload_bytes = msg.get_payload(decode=True) or b""
            charset = msg.get_content_charset() or "utf-8"
            payload = payload_bytes.decode(charset, errors="replace")
        if not isinstance(payload, str):
            return ""
        if msg.get_content_type() == "text/html":
            return cls._html_to_text(payload).strip()
        return payload.strip()

    @staticmethod
    def _check_authentication_results(parsed_msg: Any) -> tuple[bool, bool]:
        """Parse Authentication-Results headers for SPF and DKIM verdicts.

        Returns:
            A tuple of (spf_pass, dkim_pass) booleans.
        """
        spf_pass = False
        dkim_pass = False
        for ar_header in parsed_msg.get_all("Authentication-Results") or []:
            ar_lower = ar_header.lower()
            if re.search(r"\bspf\s*=\s*pass\b", ar_lower):
                spf_pass = True
            if re.search(r"\bdkim\s*=\s*pass\b", ar_lower):
                dkim_pass = True
        return spf_pass, dkim_pass

    @classmethod
    def _extract_attachments(
        cls,
        msg: Any,
        uid: str,
        *,
        allowed_types: list[str],
        max_size: int,
        max_count: int,
    ) -> list[Path]:
        """Extract and save email attachments to the media directory.

        Returns list of saved file paths.
        """
        if not msg.is_multipart():
            return []

        saved: list[Path] = []
        media_dir = get_media_dir("email")

        for part in msg.walk():
            if len(saved) >= max_count:
                break
            if part.get_content_disposition() != "attachment":
                continue

            content_type = part.get_content_type()
            if not any(fnmatch(content_type, pat) for pat in allowed_types):
                logger.debug("Attachment skipped (type {}): not in allowed list", content_type)
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            if len(payload) > max_size:
                logger.warning(
                    "Attachment skipped: size {} exceeds limit {}",
                    len(payload),
                    max_size,
                )
                continue

            raw_name = part.get_filename() or "attachment"
            sanitized = safe_filename(raw_name) or "attachment"
            dest = media_dir / f"{uid}_{sanitized}"

            try:
                dest.write_bytes(payload)
                saved.append(dest)
                logger.info("Attachment saved: {}", dest)
            except Exception as exc:
                logger.warning("Failed to save attachment {}: {}", dest, exc)

        return saved

    @staticmethod
    def _html_to_text(raw_html: str) -> str:
        text = re.sub(r"<\s*br\s*/?>", "\n", raw_html, flags=re.IGNORECASE)
        text = re.sub(r"<\s*/\s*p\s*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(text)

    def _reply_subject(self, base_subject: str) -> str:
        subject = (base_subject or "").strip() or "blackcat reply"
        prefix = self.config.subject_prefix or "Re: "
        if subject.lower().startswith("re:"):
            return subject
        return f"{prefix}{subject}"
