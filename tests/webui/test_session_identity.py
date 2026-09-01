from nanobot.webui.session_identity import (
    WEBUI_SESSION_STORAGE_PREFIX,
    is_valid_webui_chat_id,
    is_webui_session_key,
    webui_chat_id,
    webui_session_key,
)


def test_webui_session_identity_preserves_persisted_wire_compatibility() -> None:
    assert WEBUI_SESSION_STORAGE_PREFIX == "websocket:"
    assert webui_session_key("chat-1") == "websocket:chat-1"
    assert is_webui_session_key("websocket:chat-1")
    assert webui_chat_id("websocket:chat-1") == "chat-1"
    assert webui_chat_id("websocket: chat-1") == " chat-1"
    assert webui_chat_id("websocket:") is None
    assert webui_chat_id("telegram:chat-1") is None


def test_webui_chat_id_validation_is_protocol_scoped() -> None:
    assert is_valid_webui_chat_id("unified:default")
    assert is_valid_webui_chat_id("x" * 64)
    assert not is_valid_webui_chat_id("x" * 65)
    assert not is_valid_webui_chat_id("../escape")
