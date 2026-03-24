"""Tests for Phase A — outbound recipient validation.

Covers:
- Email format validation (``_EMAIL_RE``)
- Outbound allowlist (``allow_to``)
- Proactive send policy (``known_only``, ``allowlist``, ``open``)
- ``known_recipients`` property
- Contacts injection in system prompt
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.email import EmailChannel
from nanobot.config.schema import EmailConfig
from nanobot.errors import DeliverySkippedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    )
    defaults.update(overrides)
    return EmailConfig(**defaults)


class FakeSMTP:
    """Minimal SMTP stub for send() tests."""

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


def _patch_smtp(monkeypatch) -> list[FakeSMTP]:
    instances: list[FakeSMTP] = []

    def factory(host: str, port: int, timeout: int = 30):
        inst = FakeSMTP(host, port, timeout=timeout)
        instances.append(inst)
        return inst

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", factory)
    return instances


# ---------------------------------------------------------------------------
# Email format validation
# ---------------------------------------------------------------------------


class TestEmailFormatValidation:
    async def test_valid_email_passes(self, monkeypatch) -> None:
        _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="open")
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(channel="email", chat_id="alice@example.com", content="hi")
        )

    @pytest.mark.parametrize(
        "addr",
        [
            "not-an-email",
            "@missing-local.com",
            "no-domain@",
            "spaces in@addr.com",
            "alice@no tld",
            "",
        ],
    )
    async def test_invalid_email_rejected(self, addr: str, monkeypatch) -> None:
        _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="open")
        channel = EmailChannel(cfg, MessageBus())
        with pytest.raises(DeliverySkippedError):
            await channel.send(OutboundMessage(channel="email", chat_id=addr, content="hi"))


# ---------------------------------------------------------------------------
# Outbound allowlist (allow_to)
# ---------------------------------------------------------------------------


class TestAllowlist:
    async def test_allowlist_permits_listed_address(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(allow_to=["alice@example.com"], proactive_send_policy="open")
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(channel="email", chat_id="alice@example.com", content="hi")
        )
        assert len(instances) == 1

    async def test_allowlist_blocks_unlisted_address(self, monkeypatch) -> None:
        _patch_smtp(monkeypatch)
        cfg = _make_config(allow_to=["alice@example.com"], proactive_send_policy="open")
        channel = EmailChannel(cfg, MessageBus())
        with pytest.raises(DeliverySkippedError, match="not in the allowed"):
            await channel.send(
                OutboundMessage(channel="email", chat_id="eve@example.com", content="hi")
            )

    async def test_empty_allowlist_permits_all(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(allow_to=[], proactive_send_policy="open")
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(channel="email", chat_id="anyone@example.com", content="hi")
        )
        assert len(instances) == 1


# ---------------------------------------------------------------------------
# Proactive send policy
# ---------------------------------------------------------------------------


class TestProactiveSendPolicy:
    """Policy only applies to non-reply, non-force_send outbound emails."""

    async def test_known_only_blocks_unknown(self, monkeypatch) -> None:
        _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="known_only")
        channel = EmailChannel(cfg, MessageBus())
        with pytest.raises(DeliverySkippedError, match="known_only"):
            await channel.send(
                OutboundMessage(channel="email", chat_id="stranger@example.com", content="hi")
            )

    async def test_known_only_allows_known_sender(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="known_only")
        channel = EmailChannel(cfg, MessageBus())
        channel._last_subject_by_chat["bob@example.com"] = "Previous thread"
        await channel.send(
            OutboundMessage(channel="email", chat_id="bob@example.com", content="hi")
        )
        assert len(instances) == 1

    async def test_known_only_allows_allowlisted(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="known_only", allow_to=["allowed@example.com"])
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(channel="email", chat_id="allowed@example.com", content="hi")
        )
        assert len(instances) == 1

    async def test_allowlist_policy_blocks_without_allowlist(self, monkeypatch) -> None:
        _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="allowlist", allow_to=[])
        channel = EmailChannel(cfg, MessageBus())
        with pytest.raises(DeliverySkippedError, match="allowlist"):
            await channel.send(
                OutboundMessage(channel="email", chat_id="bob@example.com", content="hi")
            )

    async def test_allowlist_policy_allows_listed(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="allowlist", allow_to=["bob@example.com"])
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(channel="email", chat_id="bob@example.com", content="hi")
        )
        assert len(instances) == 1

    async def test_open_policy_allows_anyone(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="open")
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(channel="email", chat_id="stranger@example.com", content="hi")
        )
        assert len(instances) == 1

    async def test_policy_skipped_for_replies(self, monkeypatch) -> None:
        """Replies bypass proactive policy — they're responses not initiations."""
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="known_only")
        channel = EmailChannel(cfg, MessageBus())
        # Mark as a known sender (reply scenario)
        channel._last_subject_by_chat["alice@example.com"] = "Hi"
        await channel.send(
            OutboundMessage(channel="email", chat_id="alice@example.com", content="reply")
        )
        assert len(instances) == 1

    async def test_force_send_bypasses_policy(self, monkeypatch) -> None:
        instances = _patch_smtp(monkeypatch)
        cfg = _make_config(proactive_send_policy="known_only")
        channel = EmailChannel(cfg, MessageBus())
        await channel.send(
            OutboundMessage(
                channel="email",
                chat_id="unknown@example.com",
                content="forced",
                metadata={"force_send": True},
            )
        )
        assert len(instances) == 1


# ---------------------------------------------------------------------------
# known_recipients property
# ---------------------------------------------------------------------------


class TestKnownRecipients:
    def test_empty_by_default(self) -> None:
        channel = EmailChannel(_make_config(), MessageBus())
        assert channel.known_recipients == []

    def test_includes_allow_to(self) -> None:
        cfg = _make_config(allow_to=["a@x.com", "b@x.com"])
        channel = EmailChannel(cfg, MessageBus())
        assert channel.known_recipients == ["a@x.com", "b@x.com"]

    def test_includes_known_senders(self) -> None:
        channel = EmailChannel(_make_config(), MessageBus())
        channel._last_subject_by_chat["sender@x.com"] = "Thread"
        assert channel.known_recipients == ["sender@x.com"]

    def test_deduplicates_and_sorts(self) -> None:
        cfg = _make_config(allow_to=["z@x.com", "a@x.com"])
        channel = EmailChannel(cfg, MessageBus())
        channel._last_subject_by_chat["a@x.com"] = "Thread"
        channel._last_subject_by_chat["m@x.com"] = "Thread"
        assert channel.known_recipients == ["a@x.com", "m@x.com", "z@x.com"]


# ---------------------------------------------------------------------------
# Contacts injection in system prompt
# ---------------------------------------------------------------------------


class TestContactsContext:
    def test_set_contacts_populates_prompt_section(self) -> None:
        from pathlib import Path

        from nanobot.context.context import ContextBuilder

        cb = ContextBuilder(workspace=Path("/tmp/test"))
        cb.set_contacts_context(["alice@x.com", "bob@x.com"])
        prompt = cb.build_system_prompt()
        assert "Known Contacts" in prompt
        assert "alice@x.com" in prompt
        assert "bob@x.com" in prompt
        assert "Do NOT invent" in prompt

    def test_empty_contacts_not_in_prompt(self) -> None:
        from pathlib import Path

        from nanobot.context.context import ContextBuilder

        cb = ContextBuilder(workspace=Path("/tmp/test"))
        cb.set_contacts_context([])
        prompt = cb.build_system_prompt()
        assert "Known Contacts" not in prompt

    def test_set_contacts_clears_previous(self) -> None:
        from pathlib import Path

        from nanobot.context.context import ContextBuilder

        cb = ContextBuilder(workspace=Path("/tmp/test"))
        cb.set_contacts_context(["old@x.com"])
        cb.set_contacts_context([])
        prompt = cb.build_system_prompt()
        assert "old@x.com" not in prompt
