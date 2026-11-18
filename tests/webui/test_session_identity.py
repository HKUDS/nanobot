from nanobot.webui.session_identity import (
    WEBUI_SESSION_STORAGE_PREFIX,
    channel_session_chat_id,
    channel_session_key,
    channel_session_title,
    entry_channel_title,
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
    assert is_valid_webui_chat_id("chat:branch-2")
    assert is_valid_webui_chat_id("x" * 64)
    assert not is_valid_webui_chat_id("x" * 65)
    assert not is_valid_webui_chat_id("../escape")


def test_channel_alias_preserves_distinct_topics_and_named_instances() -> None:
    keys = (
        "telegram:-100123:topic:17",
        "telegram:-100123:topic:18",
        "discord:-100123:thread:17",
        "feishu.bot-2:g:研发/一组",
        "feishu:g:研发/一组",
    )
    aliases = {channel_session_chat_id(key) for key in keys}
    assert None not in aliases and len(aliases) == len(keys)
    for key in keys:
        alias = channel_session_chat_id(key)
        assert alias is not None and not is_valid_webui_chat_id(alias)
        assert channel_session_key(alias) == key
    assert channel_session_title(keys[-2]) == channel_session_title(keys[-1]) == "Feishu"
    assert entry_channel_title("feishu.bot-2") == "Feishu"
    assert channel_session_chat_id("websocket:default") is None
    assert channel_session_chat_id("telegram.unknown:-100123") is None
