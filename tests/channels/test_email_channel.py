from email.message import EmailMessage
from datetime import date
from pathlib import Path
import imaplib

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.email import EmailChannel
from nanobot.channels.email import EmailConfig


def _make_config(**overrides) -> EmailConfig:
    defaults = dict(
        enabled=True,
        consent_granted=True,
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="bot@example.com",
        imap_password="secret",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="bot@example.com",
        smtp_password="secret",
        mark_seen=True,
        # Disable auth verification by default so existing tests are unaffected
        verify_dkim=False,
        verify_spf=False,
    )
    defaults.update(overrides)
    return EmailConfig(**defaults)


def _make_raw_email(
    from_addr: str = "alice@example.com",
    subject: str = "Hello",
    body: str = "This is the body.",
    auth_results: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "bot@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<m1@example.com>"
    if auth_results:
        msg["Authentication-Results"] = auth_results
    msg.set_content(body)
    return msg.as_bytes()


def test_fetch_new_messages_parses_unseen_and_marks_seen(monkeypatch) -> None:
    raw = _make_raw_email(subject="Invoice", body="Please pay")

    class FakeIMAP:
        def __init__(self) -> None:
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 123 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["sender"] == "alice@example.com"
    assert items[0]["subject"] == "Invoice"
    assert "Please pay" in items[0]["content"]
    assert fake.store_calls == [(b"1", "+FLAGS", "\\Seen")]

    # Same UID should be deduped in-process.
    items_again = channel._fetch_new_messages()
    assert items_again == []


def test_fetch_new_messages_skips_self_sent_email_and_marks_seen(monkeypatch) -> None:
    raw = _make_raw_email(from_addr="Nanobot <bot@example.com>", subject="Loop test")

    class FakeIMAP:
        def __init__(self) -> None:
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 123 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(from_address="bot@example.com"), MessageBus())
    items = channel._fetch_new_messages()

    assert items == []
    assert fake.store_calls == [(b"1", "+FLAGS", "\\Seen")]

    # Same UID should still be deduped after being ignored.
    items_again = channel._fetch_new_messages()
    assert items_again == []


def test_fetch_new_messages_retries_once_when_imap_connection_goes_stale(monkeypatch) -> None:
    raw = _make_raw_email(subject="Invoice", body="Please pay")
    fail_once = {"pending": True}

    class FlakyIMAP:
        def __init__(self) -> None:
            self.store_calls: list[tuple[bytes, str, str]] = []
            self.search_calls = 0

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            self.search_calls += 1
            if fail_once["pending"]:
                fail_once["pending"] = False
                raise imaplib.IMAP4.abort("socket error")
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 123 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake_instances: list[FlakyIMAP] = []

    def _factory(_host: str, _port: int):
        instance = FlakyIMAP()
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", _factory)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert len(fake_instances) == 2
    assert fake_instances[0].search_calls == 1
    assert fake_instances[1].search_calls == 1


def test_fetch_new_messages_keeps_messages_collected_before_stale_retry(monkeypatch) -> None:
    raw_first = _make_raw_email(subject="First", body="First body")
    raw_second = _make_raw_email(subject="Second", body="Second body")
    mailbox_state = {
        b"1": {"uid": b"123", "raw": raw_first, "seen": False},
        b"2": {"uid": b"124", "raw": raw_second, "seen": False},
    }
    fail_once = {"pending": True}

    class FlakyIMAP:
        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"2"]

        def search(self, *_args):
            unseen_ids = [imap_id for imap_id, item in mailbox_state.items() if not item["seen"]]
            return "OK", [b" ".join(unseen_ids)]

        def fetch(self, imap_id: bytes, _parts: str):
            if imap_id == b"2" and fail_once["pending"]:
                fail_once["pending"] = False
                raise imaplib.IMAP4.abort("socket error")
            item = mailbox_state[imap_id]
            header = b"%s (UID %s BODY[] {200})" % (imap_id, item["uid"])
            return "OK", [(header, item["raw"]), b")"]

        def store(self, imap_id: bytes, _op: str, _flags: str):
            mailbox_state[imap_id]["seen"] = True
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: FlakyIMAP())

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    assert [item["subject"] for item in items] == ["First", "Second"]


def test_fetch_new_messages_skips_missing_mailbox(monkeypatch) -> None:
    class MissingMailboxIMAP:
        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            raise imaplib.IMAP4.error("Mailbox doesn't exist")

        def logout(self):
            return "BYE", [b""]

    monkeypatch.setattr(
        "nanobot.channels.email.imaplib.IMAP4_SSL",
        lambda _h, _p: MissingMailboxIMAP(),
    )

    channel = EmailChannel(_make_config(), MessageBus())

    assert channel._fetch_new_messages() == []


def test_extract_text_body_falls_back_to_html() -> None:
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "HTML only"
    msg.add_alternative("<p>Hello<br>world</p>", subtype="html")

    text = EmailChannel._extract_text_body(msg)
    assert "Hello" in text
    assert "world" in text


@pytest.mark.asyncio
async def test_start_returns_immediately_without_consent(monkeypatch) -> None:
    cfg = _make_config()
    cfg.consent_granted = False
    channel = EmailChannel(cfg, MessageBus())

    called = {"fetch": False}

    def _fake_fetch():
        called["fetch"] = True
        return []

    monkeypatch.setattr(channel, "_fetch_new_messages", _fake_fetch)
    await channel.start()
    assert channel.is_running is False
    assert called["fetch"] is False


@pytest.mark.asyncio
async def test_send_uses_smtp_and_reply_subject(monkeypatch) -> None:
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout
            self.started_tls = False
            self.logged_in = False
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            self.started_tls = True

        def login(self, _user: str, _pw: str):
            self.logged_in = True

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    channel = EmailChannel(_make_config(), MessageBus())
    channel._last_subject_by_chat["alice@example.com"] = "Invoice #42"
    channel._last_message_id_by_chat["alice@example.com"] = "<m1@example.com>"

    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Acknowledged.",
        )
    )

    assert len(fake_instances) == 1
    smtp = fake_instances[0]
    assert smtp.started_tls is True
    assert smtp.logged_in is True
    assert len(smtp.sent_messages) == 1
    sent = smtp.sent_messages[0]
    assert sent["Subject"] == "Re: Invoice #42"
    assert sent["To"] == "alice@example.com"
    assert sent["In-Reply-To"] == "<m1@example.com>"


@pytest.mark.asyncio
async def test_send_skips_reply_when_auto_reply_disabled(monkeypatch) -> None:
    """When auto_reply_enabled=False, replies should be skipped but proactive sends allowed."""
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.auto_reply_enabled = False
    channel = EmailChannel(cfg, MessageBus())

    # Mark alice as someone who sent us an email (making this a "reply")
    channel._last_subject_by_chat["alice@example.com"] = "Previous email"

    # Reply should be skipped (auto_reply_enabled=False)
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Should not send.",
        )
    )
    assert fake_instances == []

    # Reply with force_send=True should be sent
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Force send.",
            metadata={"force_send": True},
        )
    )
    assert len(fake_instances) == 1
    assert len(fake_instances[0].sent_messages) == 1


@pytest.mark.asyncio
async def test_send_proactive_email_when_auto_reply_disabled(monkeypatch) -> None:
    """Proactive emails (not replies) should be sent even when auto_reply_enabled=False."""
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.auto_reply_enabled = False
    channel = EmailChannel(cfg, MessageBus())

    # bob@example.com has never sent us an email (proactive send)
    # This should be sent even with auto_reply_enabled=False
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="bob@example.com",
            content="Hello, this is a proactive email.",
        )
    )
    assert len(fake_instances) == 1
    assert len(fake_instances[0].sent_messages) == 1
    sent = fake_instances[0].sent_messages[0]
    assert sent["To"] == "bob@example.com"


@pytest.mark.asyncio
async def test_send_skips_when_consent_not_granted(monkeypatch) -> None:
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    called = {"smtp": False}

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        called["smtp"] = True
        return FakeSMTP(host, port, timeout=timeout)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.consent_granted = False
    channel = EmailChannel(cfg, MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Should not send.",
            metadata={"force_send": True},
        )
    )
    assert called["smtp"] is False


def test_fetch_messages_between_dates_uses_imap_since_before_without_mark_seen(monkeypatch) -> None:
    raw = _make_raw_email(subject="Status", body="Yesterday update")

    class FakeIMAP:
        def __init__(self) -> None:
            self.search_args = None
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            self.search_args = _args
            return "OK", [b"5"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"5 (UID 999 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel.fetch_messages_between_dates(
        start_date=date(2026, 2, 6),
        end_date=date(2026, 2, 7),
        limit=10,
    )

    assert len(items) == 1
    assert items[0]["subject"] == "Status"
    # search(None, "SINCE", "06-Feb-2026", "BEFORE", "07-Feb-2026")
    assert fake.search_args is not None
    assert fake.search_args[1:] == ("SINCE", "06-Feb-2026", "BEFORE", "07-Feb-2026")
    assert fake.store_calls == []


# ---------------------------------------------------------------------------
# Security: Anti-spoofing tests for Authentication-Results verification
# ---------------------------------------------------------------------------

def _make_fake_imap(raw: bytes):
    """Return a FakeIMAP class pre-loaded with the given raw email."""
    class FakeIMAP:
        def __init__(self) -> None:
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"1 (UID 500 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    return FakeIMAP()


def test_spoofed_email_rejected_when_verify_enabled(monkeypatch) -> None:
    """An email without Authentication-Results should be rejected when verify_dkim=True."""
    raw = _make_raw_email(subject="Spoofed", body="Malicious payload")
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(verify_dkim=True, verify_spf=True)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 0, "Spoofed email without auth headers should be rejected"


def test_email_with_valid_auth_results_accepted(monkeypatch) -> None:
    """An email with spf=pass and dkim=pass should be accepted."""
    raw = _make_raw_email(
        subject="Legit",
        body="Hello from verified sender",
        auth_results="mx.example.com; spf=pass smtp.mailfrom=alice@example.com; dkim=pass header.d=example.com",
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(verify_dkim=True, verify_spf=True)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["sender"] == "alice@example.com"
    assert items[0]["subject"] == "Legit"


def test_email_with_partial_auth_rejected(monkeypatch) -> None:
    """An email with only spf=pass but no dkim=pass should be rejected when verify_dkim=True."""
    raw = _make_raw_email(
        subject="Partial",
        body="Only SPF passes",
        auth_results="mx.example.com; spf=pass smtp.mailfrom=alice@example.com; dkim=fail",
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(verify_dkim=True, verify_spf=True)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 0, "Email with dkim=fail should be rejected"


def test_backward_compat_verify_disabled(monkeypatch) -> None:
    """When verify_dkim=False and verify_spf=False, emails without auth headers are accepted."""
    raw = _make_raw_email(subject="NoAuth", body="No auth headers present")
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(verify_dkim=False, verify_spf=False)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1, "With verification disabled, emails should be accepted as before"


def test_email_content_tagged_with_email_context(monkeypatch) -> None:
    """Email content should be prefixed with [EMAIL-CONTEXT] for LLM isolation."""
    raw = _make_raw_email(subject="Tagged", body="Check the tag")
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(verify_dkim=False, verify_spf=False)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["content"].startswith("[EMAIL-CONTEXT]"), (
        "Email content must be tagged with [EMAIL-CONTEXT]"
    )


def test_check_authentication_results_method() -> None:
    """Unit test for the _check_authentication_results static method."""
    from email.parser import BytesParser
    from email import policy

    # No Authentication-Results header
    msg_no_auth = EmailMessage()
    msg_no_auth["From"] = "alice@example.com"
    msg_no_auth.set_content("test")
    parsed = BytesParser(policy=policy.default).parsebytes(msg_no_auth.as_bytes())
    spf, dkim = EmailChannel._check_authentication_results(parsed)
    assert spf is False
    assert dkim is False

    # Both pass
    msg_both = EmailMessage()
    msg_both["From"] = "alice@example.com"
    msg_both["Authentication-Results"] = (
        "mx.google.com; spf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com"
    )
    msg_both.set_content("test")
    parsed = BytesParser(policy=policy.default).parsebytes(msg_both.as_bytes())
    spf, dkim = EmailChannel._check_authentication_results(parsed)
    assert spf is True
    assert dkim is True

    # SPF pass, DKIM fail
    msg_spf_only = EmailMessage()
    msg_spf_only["From"] = "alice@example.com"
    msg_spf_only["Authentication-Results"] = (
        "mx.google.com; spf=pass smtp.mailfrom=example.com; dkim=fail"
    )
    msg_spf_only.set_content("test")
    parsed = BytesParser(policy=policy.default).parsebytes(msg_spf_only.as_bytes())
    spf, dkim = EmailChannel._check_authentication_results(parsed)
    assert spf is True
    assert dkim is False

    # DKIM pass, SPF fail
    msg_dkim_only = EmailMessage()
    msg_dkim_only["From"] = "alice@example.com"
    msg_dkim_only["Authentication-Results"] = (
        "mx.google.com; spf=fail smtp.mailfrom=example.com; dkim=pass header.d=example.com"
    )
    msg_dkim_only.set_content("test")
    parsed = BytesParser(policy=policy.default).parsebytes(msg_dkim_only.as_bytes())
    spf, dkim = EmailChannel._check_authentication_results(parsed)
    assert spf is False
    assert dkim is True


# ---------------------------------------------------------------------------
# Attachment extraction tests
# ---------------------------------------------------------------------------


def _make_raw_email_with_attachment(
    from_addr: str = "alice@example.com",
    subject: str = "With attachment",
    body: str = "See attached.",
    attachment_name: str = "doc.pdf",
    attachment_content: bytes = b"%PDF-1.4 fake pdf content",
    attachment_mime: str = "application/pdf",
    auth_results: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "bot@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<m1@example.com>"
    if auth_results:
        msg["Authentication-Results"] = auth_results
    msg.set_content(body)
    maintype, subtype = attachment_mime.split("/", 1)
    msg.add_attachment(
        attachment_content,
        maintype=maintype,
        subtype=subtype,
        filename=attachment_name,
    )
    return msg.as_bytes()


def test_extract_attachments_saves_pdf(tmp_path, monkeypatch) -> None:
    """PDF attachment is saved to media dir and path returned in media list."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    raw = _make_raw_email_with_attachment()
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(allowed_attachment_types=["application/pdf"], verify_dkim=False, verify_spf=False)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert len(items[0]["media"]) == 1
    saved_path = Path(items[0]["media"][0])
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"%PDF-1.4 fake pdf content"
    assert "500_doc.pdf" in saved_path.name
    assert "[attachment:" in items[0]["content"]


def test_extract_attachments_disabled_by_default(monkeypatch) -> None:
    """With no allowed_attachment_types (default), no attachments are extracted."""
    raw = _make_raw_email_with_attachment()
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(verify_dkim=False, verify_spf=False)
    assert cfg.allowed_attachment_types == []
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["media"] == []
    assert "[attachment:" not in items[0]["content"]


def test_extract_attachments_mime_type_filter(tmp_path, monkeypatch) -> None:
    """Non-allowed MIME types are skipped."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    raw = _make_raw_email_with_attachment(
        attachment_name="image.png",
        attachment_content=b"\x89PNG fake",
        attachment_mime="image/png",
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(
        allowed_attachment_types=["application/pdf"],
        verify_dkim=False,
        verify_spf=False,
    )
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["media"] == []


def test_extract_attachments_empty_allowed_types_rejects_all(tmp_path, monkeypatch) -> None:
    """Empty allowed_attachment_types means no types are accepted."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    raw = _make_raw_email_with_attachment(
        attachment_name="image.png",
        attachment_content=b"\x89PNG fake",
        attachment_mime="image/png",
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(
        allowed_attachment_types=[],
        verify_dkim=False,
        verify_spf=False,
    )
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["media"] == []


def test_extract_attachments_wildcard_pattern(tmp_path, monkeypatch) -> None:
    """Glob patterns like 'image/*' match attachment MIME types."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    raw = _make_raw_email_with_attachment(
        attachment_name="photo.jpg",
        attachment_content=b"\xff\xd8\xff fake jpeg",
        attachment_mime="image/jpeg",
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(
        allowed_attachment_types=["image/*"],
        verify_dkim=False,
        verify_spf=False,
    )
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert len(items[0]["media"]) == 1


def test_extract_attachments_size_limit(tmp_path, monkeypatch) -> None:
    """Attachments exceeding max_attachment_size are skipped."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    raw = _make_raw_email_with_attachment(
        attachment_content=b"x" * 1000,
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(
        allowed_attachment_types=["*"],
        max_attachment_size=500,
        verify_dkim=False,
        verify_spf=False,
    )
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert items[0]["media"] == []


def test_extract_attachments_max_count(tmp_path, monkeypatch) -> None:
    """Only max_attachments_per_email are saved."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    # Build email with 3 attachments
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "Many attachments"
    msg["Message-ID"] = "<m1@example.com>"
    msg.set_content("See attached.")
    for i in range(3):
        msg.add_attachment(
            f"content {i}".encode(),
            maintype="application",
            subtype="pdf",
            filename=f"doc{i}.pdf",
        )
    raw = msg.as_bytes()

    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(
        allowed_attachment_types=["*"],
        max_attachments_per_email=2,
        verify_dkim=False,
        verify_spf=False,
    )
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert len(items[0]["media"]) == 2


def test_extract_attachments_sanitizes_filename(tmp_path, monkeypatch) -> None:
    """Path traversal in filenames is neutralized."""
    monkeypatch.setattr("nanobot.channels.email.get_media_dir", lambda ch: tmp_path)

    raw = _make_raw_email_with_attachment(
        attachment_name="../../../etc/passwd",
    )
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    cfg = _make_config(allowed_attachment_types=["*"], verify_dkim=False, verify_spf=False)
    channel = EmailChannel(cfg, MessageBus())
    items = channel._fetch_new_messages()

    assert len(items) == 1
    assert len(items[0]["media"]) == 1
    saved_path = Path(items[0]["media"][0])
    # File must be inside the media dir, not escaped via path traversal
    assert saved_path.parent == tmp_path
