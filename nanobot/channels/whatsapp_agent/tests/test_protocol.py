"""Wire parsing and error-classification contracts for the Agent Platform.

These tests pin the documented protocol facts that the runtime depends on but
cannot verify against the live API in CI.
"""

from __future__ import annotations

import pytest

from nanobot.channels.whatsapp_agent.protocol import (
    classify_error,
    media_limit_for,
    normalize_mime,
    outbound_kind_for_mime,
    parse_message,
    parse_poll_batch,
    parse_status,
    quote_safe_url,
)


def _poll_body(messages=None, statuses=None, next_offset=1287):
    return {
        "object": "whatsapp_agent_platform",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [{"wa_id": "user:55", "profile": {"name": "Alex"}}],
                            "messages": messages or [],
                            "statuses": statuses or [],
                        },
                    }
                ],
            }
        ],
        "next_offset": next_offset,
    }


def test_parses_text_message_with_quote_context():
    batch = parse_poll_batch(
        _poll_body(
            messages=[
                {
                    "from": "user:55",
                    "id": "wamid.1",
                    "timestamp": "1736844652",
                    "type": "text",
                    "text": {"body": "Hello agent"},
                    "context": {"id": "wamid.q", "from": "agent:9"},
                }
            ]
        )
    )

    assert batch.next_offset == 1287
    message = batch.messages[0]
    assert message.wamid == "wamid.1"
    assert message.sender == "user:55"
    assert message.timestamp == 1736844652
    assert message.text == "Hello agent"
    # Inbound quoting names the field ``id``; outbound uses ``message_id``.
    assert message.context_id == "wamid.q"
    assert message.context_from == "agent:9"
    assert message.is_user_authored is True


@pytest.mark.parametrize(
    ("kind", "payload", "attribute"),
    [
        ("image", {"id": "m1", "mime_type": "image/jpeg", "caption": "look"}, "caption"),
        ("video", {"id": "m2", "mime_type": "video/mp4"}, None),
        ("document", {"id": "m3", "mime_type": "application/pdf", "filename": "r.pdf"}, "filename"),
        ("sticker", {"id": "m4", "mime_type": "image/webp", "animated": False}, None),
    ],
)
def test_parses_media_kinds(kind, payload, attribute):
    message = parse_message(
        {"from": "user:55", "id": "w", "timestamp": "1", "type": kind, kind: payload}
    )

    assert message is not None
    assert message.kind == kind
    assert message.media is not None
    assert message.media.media_id == payload["id"]
    if attribute:
        assert getattr(message.media, attribute) == payload[attribute]


def test_voice_key_marks_only_audio_notes():
    voice_note = parse_message(
        {
            "from": "user:55",
            "id": "w1",
            "timestamp": "1",
            "type": "audio",
            "audio": {"id": "m1", "mime_type": "audio/ogg", "voice": True},
        }
    )
    audio_file = parse_message(
        {
            "from": "user:55",
            "id": "w2",
            "timestamp": "1",
            "type": "audio",
            "audio": {"id": "m2", "mime_type": "audio/mpeg"},
        }
    )

    assert voice_note is not None and voice_note.media is not None
    assert voice_note.media.voice is True
    assert audio_file is not None and audio_file.media is not None
    assert audio_file.media.voice is False


def test_empty_reaction_emoji_means_removed():
    message = parse_message(
        {
            "from": "user:55",
            "id": "w1",
            "timestamp": "1",
            "type": "reaction",
            "reaction": {"message_id": "wamid.x", "emoji": ""},
        }
    )

    assert message is not None
    assert message.kind == "reaction"
    assert message.reaction_to == "wamid.x"
    assert message.reaction_emoji == ""


def test_poll_can_return_statuses_without_messages():
    batch = parse_poll_batch(
        _poll_body(
            statuses=[
                {
                    "id": "wamid.s",
                    "status": "delivered",
                    "recipient_id": "user:55",
                    "timestamp": "1736844655",
                }
            ]
        )
    )

    assert batch.messages == []
    assert [status.status for status in batch.statuses] == ["delivered"]
    assert batch.next_offset == 1287


def test_missing_profile_name_is_not_treated_as_empty_string():
    body = _poll_body()
    body["entry"][0]["changes"][0]["value"]["contacts"] = [{"wa_id": "user:55"}]

    # The absent ``profile`` key must not raise; names are optional per poll.
    assert parse_poll_batch(body).messages == []


def test_next_offset_beyond_float_precision_is_preserved():
    offset = 9007199254740993
    assert parse_poll_batch(_poll_body(next_offset=offset)).next_offset == offset


def test_malformed_payloads_degrade_to_empty_batch():
    assert parse_poll_batch(None).messages == []
    assert parse_poll_batch({"entry": "nope"}).next_offset is None
    assert parse_message({"type": "text"}) is None
    assert parse_status({"id": "w", "status": "unknown"}) is None


@pytest.mark.parametrize(
    ("mime_type", "expected"),
    [
        ("audio/ogg; codecs=opus", "audio/ogg"),
        ("audio/x-m4a", "audio/mp4"),
        ("IMAGE/JPEG", "image/jpeg"),
    ],
)
def test_mime_normalization(mime_type, expected):
    assert normalize_mime(mime_type) == expected


@pytest.mark.parametrize(
    ("mime_type", "kind"),
    [
        ("image/jpeg", "image"),
        ("image/webp", "sticker"),
        ("video/mp4", "video"),
        ("audio/ogg", "audio"),
        ("application/pdf", "document"),
        ("application/octet-stream", "document"),
    ],
)
def test_outbound_kind_mapping(mime_type, kind):
    assert outbound_kind_for_mime(mime_type) == kind


def test_media_limits_match_the_documented_caps():
    assert media_limit_for("image/jpeg", "image") == 5 * 1024 * 1024
    assert media_limit_for("image/webp", "sticker") == 500 * 1024
    assert media_limit_for("video/mp4", "video") == 16 * 1024 * 1024
    # An undeclared type still receives the generic 16 MB cap.
    assert media_limit_for("audio/ogg", "unknown") == 16 * 1024 * 1024


def test_media_url_must_pass_the_ssrf_guard():
    # A malformed or internal target must be refused before any request is made.
    assert quote_safe_url("http://127.0.0.1/media")[0] is False
    assert quote_safe_url("file:///etc/passwd")[0] is False
    assert quote_safe_url("")[0] is False
    assert quote_safe_url("https://lookaside.fbsbx.com/x")[0] is True


def test_missing_authorization_header_is_auth_failure():
    error = classify_error(401, {"error": {"code": 190}})

    assert error.invalid_token is True


def test_invalid_token_uses_400_not_401():
    error = classify_error(400, {"error": {"code": 100, "message": "(#100) Invalid token"}})

    assert error.invalid_token is True


def test_length_rejection_on_400_is_not_an_auth_failure():
    # 400/100 is shared between an invalid token and an over-length field; the
    # over-length case sets ``message`` to the bare field name.
    error = classify_error(400, {"error": {"code": 100, "message": "text.body"}})

    assert error.invalid_token is False


def test_only_confirmed_non_delivery_is_retryable():
    assert classify_error(429, {"error": {"code": 130429}}).retryable is True
    assert classify_error(503, {"error": {"code": 131016}}).retryable is True
    # A 500 may have been delivered, so it is ambiguous rather than retryable.
    ambiguous = classify_error(500, {"error": {"code": 2}})
    assert ambiguous.retryable is False
    assert ambiguous.ambiguous is True
    # A plain 4xx fails identically until the request changes.
    fatal = classify_error(400, {"error": {"code": 131009}})
    assert fatal.retryable is False
    assert fatal.ambiguous is False


def test_duplicate_poller_is_reported_as_poll_replaced():
    error = classify_error(409, {"error": {"code": 1752041}})

    assert error.poll_replaced is True
    assert error.retryable is False


def test_error_string_carries_code_and_trace_id():
    error = classify_error(
        500,
        {"error": {"code": 2, "message": "oops", "fbtrace_id": "AW7bqWj4"}},
    )

    text = str(error)
    assert "code=2" in text
    assert "fbtrace_id=AW7bqWj4" in text
