from nanobot.session.session_messages import (
    SESSION_MESSAGE_METADATA_KEY,
    SessionMessageEnvelope,
    session_message_envelope,
)


def _envelope() -> SessionMessageEnvelope:
    return {
        "message_id": "message-1",
        "created_at_ms": 123,
        "expect_reply": True,
        "source_handle": "luma",
        "source_session_key": "websocket:source",
        "target_session_key": "telegram:target",
    }


def test_envelope_round_trips_tool_metadata() -> None:
    envelope = _envelope()

    assert session_message_envelope({SESSION_MESSAGE_METADATA_KEY: envelope}) == envelope


def test_envelope_rejects_invalid_session_key() -> None:
    envelope = _envelope()
    envelope["source_session_key"] = " "

    assert session_message_envelope({SESSION_MESSAGE_METADATA_KEY: envelope}) is None


def test_envelope_rejects_missing_fields() -> None:
    envelope = dict(_envelope())
    envelope.pop("target_session_key")

    assert session_message_envelope({SESSION_MESSAGE_METADATA_KEY: envelope}) is None
    assert session_message_envelope(None) is None
