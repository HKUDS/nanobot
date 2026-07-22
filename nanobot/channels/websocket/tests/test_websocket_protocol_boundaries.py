"""Boundary tests for pure WebSocket protocol helpers."""

from __future__ import annotations

import pytest

from nanobot.channels.websocket.runtime import (
    _is_valid_chat_id,
    _parse_envelope,
)


def test_chat_id_validator_accepts_only_compact_capability_keys() -> None:
    valid = [
        "a",
        "A-Z_09:chat-id",
        "x" * 64,
    ]
    invalid = [
        "",
        "x" * 65,
        "../escape",
        "chat/id",
        "chat id",
        "chat\nid",
        None,
        123,
    ]

    for value in valid:
        assert _is_valid_chat_id(value), value
    for value in invalid:
        assert not _is_valid_chat_id(value), repr(value)


@pytest.mark.parametrize(
    ("raw", "expected_type"),
    [
        ("plain text", None),
        ("{not json", None),
        ("[]", None),
        ("{}", None),
        ('{"type": 42}', None),
        ('{"type": "message", "content": "hi"}', "message"),
        ('  {"type": "new_chat"}  ', "new_chat"),
    ],
)
def test_parse_envelope_only_accepts_typed_json_objects(
    raw: str,
    expected_type: str | None,
) -> None:
    parsed = _parse_envelope(raw)
    if expected_type is None:
        assert parsed is None
    else:
        assert parsed is not None
        assert parsed["type"] == expected_type
