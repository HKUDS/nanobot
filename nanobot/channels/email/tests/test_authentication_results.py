"""Ingress regressions for the receiving-service authentication boundary."""

import base64
from datetime import date

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.email.runtime import EmailChannel
from nanobot.channels.email.tests.test_email_channel import (
    _make_config,
    _make_fake_imap,
    _make_raw_email,
)

_PASS = "mx.receiver.example; spf=pass smtp.mailfrom=alice@example.com; dkim=pass header.d=example.com"


def _channel(monkeypatch, headers: list[str], *, extra_headers: bytes = b"", **config):
    # Insert wire bytes directly: EmailMessage may otherwise refold/decode them.
    raw = b"".join(b"Authentication-Results: " + value.encode() + b"\r\n" for value in headers)
    raw += extra_headers + _make_raw_email()
    fake = _make_fake_imap(raw, uid=b"1")
    monkeypatch.setattr("nanobot.channels.email.runtime.imaplib.IMAP4_SSL", lambda *_: fake)
    values = dict(
        allow_from=["alice@example.com"], verify_spf=True, verify_dkim=True,
        trusted_authserv_ids=["mx.receiver.example"],
    )
    values.update(config)
    return EmailChannel(_make_config(**values), MessageBus()), fake


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("headers", [
    [_PASS.replace("mx.receiver.example", "mx.attacker.example")],
    ["mx.receiver.example; none", _PASS],
    [_PASS, "mx.receiver.example; none"],
    [_PASS, "mx.receiver.example; spf=fail (unterminated"],
    ["mx.receiver.example; dkim=fail reason=\"unterminated", _PASS],
    ["mx.receiver.example; malformed", _PASS],
    ["mx.receiver.example", _PASS],
    [_PASS.replace("smtp.mailfrom=alice@example.com", "smtp.mailfrom=attacker.example smtp.mailfrom=example.com")],
    [_PASS + " header.d=attacker.example"],
    ["=?utf-8?b?" + base64.b64encode(_PASS.encode()).decode() + "?="],
    [_PASS.replace("mx.receiver.example", "=?utf-8?q?mx.receiver.example?=")],
    ["mx.receiver.example; spf=fail (spf=pass); dkim=fail reason=\"dkim=pass\""],
    [_PASS.replace("spf=pass", "spf=pass reason=\"comment\"smtp.mailfrom=attacker.example")],
    [_PASS.replace("header.d=example.com", "header.d=attacker.example header.i=@example.com")],
    [_PASS.replace("header.d=example.com", "header.d=attacker@example.com")],
])
def test_untrusted_or_ambiguous_results_never_fetch_body(monkeypatch, headers, historical):
    channel, fake = _channel(monkeypatch, headers)
    if historical:
        items = channel.fetch_messages_between_dates(date(2026, 1, 1), date(2026, 1, 2))
    else:
        items, skipped = channel._fetch_new_messages()
        assert skipped == {"1"}
    assert items == []
    assert [call for call in fake.uid_calls if call[0] == "FETCH"] == [
        ("FETCH", "1", "(BODY.PEEK[HEADER])"),
    ]
    assert not any(call[0] == "STORE" for call in fake.uid_calls)


@pytest.mark.parametrize("extra_headers", [
    b"From: alice@example.com\r\n",
    b"From: Mallory <mallory@attacker.example>\r\n",
])
def test_repeated_from_identity_is_not_authenticated(monkeypatch, extra_headers):
    channel, fake = _channel(monkeypatch, [_PASS], extra_headers=extra_headers)
    items, _ = channel._fetch_new_messages()
    assert items == []
    assert not any("(BODY.PEEK[])" in call for call in fake.uid_calls)


@pytest.mark.parametrize("header", [
    _PASS,
    _PASS.replace("header.d=example.com", "header.i=@example.com header.s=selector header.b=abc"),
    _PASS.replace("mx.receiver.example", '"MX.Receiver.Example." 1'),
    _PASS.replace("; ", ";\r\n\t"),
    _PASS.replace("spf=pass", 'spf/1 = PASS reason="" (nested (comment))'),
    _PASS.replace("header.d=example.com", 'header (comment) . d = "EXAMPLE.COM."'),
    _PASS + "; dkim=fail header.d=attacker.example",
    _PASS.replace("smtp.mailfrom=alice@example.com", 'smtp.mailfrom="bounce token"@example.com'),
    _PASS.replace("header.d=example.com", 'header.i="alice smith"@example.com'),
])
def test_legitimate_receiver_results_remain_accepted(monkeypatch, header):
    channel, fake = _channel(monkeypatch, [header])
    items, skipped = channel._fetch_new_messages()
    assert len(items) == 1
    assert items[0]["sender"] == "alice@example.com"
    assert skipped == set()
    assert any("(BODY.PEEK[])" in call for call in fake.uid_calls)


@pytest.mark.parametrize(("spf", "dkim", "headers"), [
    (False, False, []),
    (True, False, ["mx.receiver.example; spf=pass smtp.mailfrom=example.com"]),
    (False, True, ["mx.receiver.example; dkim=pass header.i=@example.com"]),
])
def test_explicit_verification_modes_preserved(monkeypatch, spf, dkim, headers):
    channel, _ = _channel(monkeypatch, headers, verify_spf=spf, verify_dkim=dkim)
    items, _ = channel._fetch_new_messages()
    assert len(items) == 1


def test_historical_fetch_fails_closed_without_trust_anchor(monkeypatch):
    channel, fake = _channel(monkeypatch, [_PASS], trusted_authserv_ids=[])
    assert channel.fetch_messages_between_dates(date(2026, 1, 1), date(2026, 1, 2)) == []
    assert not any("(BODY.PEEK[])" in call for call in fake.uid_calls)


@pytest.mark.parametrize("sender", [
    "José <alice@example.com>",
    '"张三" <alice@example.com>',
    "=?utf-8?b?5byg5LiJ?= <alice@example.com>",
])
def test_international_display_name_remains_accepted(monkeypatch, sender):
    raw = ("From: " + sender + "\r\nAuthentication-Results: " + _PASS + "\r\n\r\nHello").encode()
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.runtime.imaplib.IMAP4_SSL", lambda *_: fake)
    channel = EmailChannel(_make_config(
        allow_from=["alice@example.com"], verify_spf=True, verify_dkim=True,
        trusted_authserv_ids=["mx.receiver.example"],
    ), MessageBus())
    items, _ = channel._fetch_new_messages()
    assert len(items) == 1
    assert items[0]["sender"] == "alice@example.com"


@pytest.mark.parametrize("sender", [
    "alice@example.com, mallory@attacker.example",
    "alice@example.com <mallory@attacker.example>",
])
def test_malformed_or_multiple_visible_mailboxes_are_rejected(monkeypatch, sender):
    raw = ("From: " + sender + "\r\nAuthentication-Results: " + _PASS + "\r\n\r\nHello").encode()
    fake = _make_fake_imap(raw)
    monkeypatch.setattr("nanobot.channels.email.runtime.imaplib.IMAP4_SSL", lambda *_: fake)
    channel = EmailChannel(_make_config(
        allow_from=["alice@example.com"], verify_spf=True, verify_dkim=True,
        trusted_authserv_ids=["mx.receiver.example"],
    ), MessageBus())
    items, _ = channel._fetch_new_messages()
    assert items == []
    assert not any("(BODY.PEEK[])" in call for call in fake.uid_calls)


def test_international_domain_normalization_does_not_merge_distinct_domains():
    assert EmailChannel._address_domain("alice@faß.de") == ""
    assert EmailChannel._address_domain("alice@xn--fa-hia.de") == "xn--fa-hia.de"
    assert EmailChannel._address_domain("alice@bücher.example") == "xn--bcher-kva.example"
