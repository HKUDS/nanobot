import imaplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.email import EmailChannel, EmailConfig


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
        allow_from=["*"],
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


@pytest.mark.parametrize(
    "config_override,from_header",
    [
        # Only smtp_username matches — simulates an SMTP relay where
        # outbound From gets rewritten to the SMTP login identity.
        (
            {"from_address": "", "smtp_username": "bot@example.com", "imap_username": "other@imap.com"},
            "bot@example.com",
        ),
        # Only imap_username matches — simulates mailbox-based identity
        # with no explicit from_address set.
        (
            {"from_address": "", "smtp_username": "other@smtp.com", "imap_username": "bot@example.com"},
            "bot@example.com",
        ),
        # Case-insensitive: inbound From arrives upper-cased.
        (
            {"from_address": "bot@example.com", "smtp_username": "other@smtp.com", "imap_username": "other@imap.com"},
            "BOT@EXAMPLE.COM",
        ),
    ],
    ids=["smtp_username_only", "imap_username_only", "case_insensitive"],
)
def test_fetch_new_messages_skips_self_sent_across_identity_sources(
    monkeypatch, config_override, from_header
) -> None:
    """Self-address detection must fire when any of from_address / smtp_username /
    imap_username matches, and must be case-insensitive."""
    raw = _make_raw_email(from_addr=from_header, subject="Loop test")

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

    channel = EmailChannel(_make_config(**config_override), MessageBus())
    items = channel._fetch_new_messages()

    assert items == []
    assert fake.store_calls == [(b"1", "+FLAGS", "\\Seen")]


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
async def test_send_skips_progress_messages_before_smtp(monkeypatch) -> None:
    called = {"smtp": False}

    def _smtp_factory(*_args, **_kwargs):
        called["smtp"] = True
        raise AssertionError("progress messages must not open an SMTP connection")

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    channel = EmailChannel(_make_config(), MessageBus())

    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="",
            metadata={
                "_progress": True,
                "_tool_events": [{"phase": "end", "name": "exec"}],
            },
        )
    )

    assert called["smtp"] is False


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
    from email import policy
    from email.parser import BytesParser

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


def test_fetch_new_messages_ignores_unauthorized_sender_before_attachments(monkeypatch) -> None:
    raw = _make_raw_email_with_attachment(from_addr="blocked@example.com")
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    called = {"attachments": False}

    def _extract_attachments(*_args, **_kwargs):
        called["attachments"] = True
        return []

    monkeypatch.setattr(EmailChannel, "_extract_attachments", _extract_attachments)

    cfg = _make_config(
        allow_from=["allowed@example.com"],
        allowed_attachment_types=["application/pdf"],
        verify_dkim=False,
        verify_spf=False,
    )
    channel = EmailChannel(cfg, MessageBus())

    assert channel._fetch_new_messages() == []
    assert called["attachments"] is False
    assert fake.store_calls == [(b"1", "+FLAGS", "\\Seen")]


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


# ---------------------------------------------------------------------------
# Agent-initiated file attachment tests (send with media)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_with_single_file_attachment(tmp_path, monkeypatch) -> None:
    """Agent sends an email with a single file attached."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    # Create a real temp file to attach
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"%PDF-1.4 fake pdf content")

    channel = EmailChannel(_make_config(), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Please find the report attached.",
            media=[str(attachment)],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    assert sent["To"] == "alice@example.com"
    assert sent.is_multipart(), "Email with attachment should be multipart"

    # Walk parts to find the attachment
    attachment_parts = []
    for part in sent.walk():
        if part.get_content_disposition() == "attachment":
            attachment_parts.append(part)
    assert len(attachment_parts) == 1
    att = attachment_parts[0]
    assert att.get_filename() == "report.pdf"
    assert att.get_content_type() == "application/pdf"
    assert att.get_payload(decode=True) == b"%PDF-1.4 fake pdf content"


@pytest.mark.asyncio
async def test_send_with_multiple_file_attachments(tmp_path, monkeypatch) -> None:
    """Agent sends an email with multiple files attached."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    file1 = tmp_path / "doc.pdf"
    file1.write_bytes(b"%PDF-1.4 doc")
    file2 = tmp_path / "image.png"
    file2.write_bytes(b"\x89PNG fake image")
    file3 = tmp_path / "notes.txt"
    file3.write_bytes(b"Hello, this is a text note.")

    channel = EmailChannel(_make_config(), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="bob@example.com",
            content="Multiple files attached.",
            media=[str(file1), str(file2), str(file3)],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    assert sent.is_multipart()

    attachment_parts = []
    for part in sent.walk():
        if part.get_content_disposition() == "attachment":
            attachment_parts.append(part)
    assert len(attachment_parts) == 3

    filenames = {p.get_filename() for p in attachment_parts}
    assert filenames == {"doc.pdf", "image.png", "notes.txt"}


@pytest.mark.asyncio
async def test_send_skips_missing_attachment_file(tmp_path, monkeypatch) -> None:
    """Non-existent attachment file is skipped without breaking the send."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    existing = tmp_path / "real.txt"
    existing.write_text("I exist")

    channel = EmailChannel(_make_config(), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="One attachment is missing.",
            media=[
                str(existing),
                str(tmp_path / "nonexistent.pdf"),
            ],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    assert sent.is_multipart()

    attachment_parts = []
    for part in sent.walk():
        if part.get_content_disposition() == "attachment":
            attachment_parts.append(part)
    # Only the existing file should be attached
    assert len(attachment_parts) == 1
    assert attachment_parts[0].get_filename() == "real.txt"
    body = sent.get_body(preferencelist=("plain",))
    assert body is not None
    assert "[attachment: nonexistent.pdf - send failed]" in body.get_content()


@pytest.mark.asyncio
async def test_send_skips_oversized_attachment_file(tmp_path, monkeypatch) -> None:
    """Attachment exceeding max_attachment_size is skipped with a visible note."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    attachment = tmp_path / "too-large.bin"
    attachment.write_bytes(b"1234")

    channel = EmailChannel(_make_config(max_attachment_size=3), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Attachment should be skipped.",
            media=[str(attachment)],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    assert not sent.is_multipart()
    assert "[attachment: too-large.bin - too large]" in sent.get_content()


@pytest.mark.asyncio
async def test_send_limits_outbound_attachment_count(tmp_path, monkeypatch) -> None:
    """Only max_attachments_per_email outbound attachments are included."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    file1 = tmp_path / "first.txt"
    file1.write_text("first")
    file2 = tmp_path / "second.txt"
    file2.write_text("second")

    channel = EmailChannel(_make_config(max_attachments_per_email=1), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Only one attachment should be sent.",
            media=[str(file1), str(file2)],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    attachment_parts = []
    for part in sent.walk():
        if part.get_content_disposition() == "attachment":
            attachment_parts.append(part)
    assert len(attachment_parts) == 1
    assert attachment_parts[0].get_filename() == "first.txt"
    body = sent.get_body(preferencelist=("plain",))
    assert body is not None
    assert "[attachment: second.txt - too many attachments]" in body.get_content()


@pytest.mark.asyncio
async def test_send_with_unknown_mime_type_attachment(tmp_path, monkeypatch) -> None:
    """File with unknown extension gets application/octet-stream MIME type."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    attachment = tmp_path / "data.unknown_ext_xyz"
    attachment.write_bytes(b"some binary data")

    channel = EmailChannel(_make_config(), MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Unknown MIME type.",
            media=[str(attachment)],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    assert sent.is_multipart()

    attachment_parts = []
    for part in sent.walk():
        if part.get_content_disposition() == "attachment":
            attachment_parts.append(part)
    assert len(attachment_parts) == 1
    att = attachment_parts[0]
    assert att.get_content_type() == "application/octet-stream"
    assert att.get_filename() == "data.unknown_ext_xyz"


@pytest.mark.asyncio
async def test_send_with_media_and_reply_subject_and_in_reply_to(tmp_path, monkeypatch) -> None:
    """Attachments work together with reply subject and In-Reply-To headers."""
    sent_messages: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            sent_messages.append(msg)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", lambda h, p, timeout=30: FakeSMTP(h, p, timeout=timeout))

    attachment = tmp_path / "summary.pdf"
    attachment.write_bytes(b"%PDF-1.4 summary")

    channel = EmailChannel(_make_config(), MessageBus())
    channel._last_subject_by_chat["alice@example.com"] = "Original subject"
    channel._last_message_id_by_chat["alice@example.com"] = "<orig@example.com>"

    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Reply with attachment.",
            media=[str(attachment)],
        )
    )

    assert len(sent_messages) == 1
    sent = sent_messages[0]
    assert sent["Subject"] == "Re: Original subject"
    assert sent["In-Reply-To"] == "<orig@example.com>"
    assert sent["References"] == "<orig@example.com>"

    attachment_parts = []
    for part in sent.walk():
        if part.get_content_disposition() == "attachment":
            attachment_parts.append(part)
    assert len(attachment_parts) == 1
    assert attachment_parts[0].get_filename() == "summary.pdf"
