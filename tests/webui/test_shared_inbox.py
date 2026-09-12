"""Shared inbox auth, canonical-history, and delivery-receipt regressions (no network)."""
import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventContext, SessionTurnPersisted
from nanobot.channels.telegram.runtime import TelegramConfig
from nanobot.channels.telegram.technical_config import TelegramTechnicalConfig
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.session.manager import SessionManager
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.shared_inbox import MAIN_CHAT_ID, NOTIFICATIONS_CHAT_ID, SharedInbox


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path / "data")
    sessions = SessionManager(tmp_path / "workspace", sessions_root=tmp_path / "sessions")
    config = TelegramTechnicalConfig(enabled=True, chat_id="-1007", main_chat_id="7", shared_inbox=True)
    return SharedInbox(config, sessions, MessageBus())


def gateway(inbox, tmp_path):
    return build_gateway_services(
        config=WebSocketConfig(), bus=inbox.bus, session_manager=inbox.sessions,
        static_dist_path=None, workspace_path=tmp_path / "workspace",
        default_restrict_to_workspace=False, runtime_model_name=None,
        runtime_surface="browser", runtime_capabilities_overrides=None, shared_inbox=inbox,
    )


def test_main_is_one_existing_owner_conversation_not_global_unified(inbox):
    owner = inbox.sessions.get_or_create("telegram:7")
    owner.add_message("user", "hello")
    owner.add_message("assistant", "", tool_calls=[{"function": {"arguments": "SECRET"}}])
    owner.add_message("tool", "SECRET", name="exec")
    owner.add_message("assistant", "hello back")
    inbox.sessions.save(owner)
    for key in ("unified:default", "telegram:8", "websocket:other"):
        other = inbox.sessions.get_or_create(key)
        other.add_message("user", "OTHER_USER_SECRET")
        inbox.sessions.save(other)
    messages = inbox.messages(MAIN_CHAT_ID)
    assert [message["content"] for message in messages] == ["hello", "hello back"]
    assert inbox.session_key("websocket", MAIN_CHAT_ID) == "telegram:7"
    assert inbox.session_key("telegram", "7") == "telegram:7"
    assert inbox.session_key("websocket", "other") == "websocket:other"
    assert inbox.session_key("telegram", "8") == "telegram:8"
    assert inbox.sessions.read_session_file("websocket:shared-main") is None
    assert [row["title"] for row in inbox.rows()] == ["Powiadomienia", "Czat główny"]


async def test_receipts_are_deduplicated_durable_and_never_llm_messages(inbox):
    await inbox.delivered("Tool exec: start", 11)
    await inbox.delivered("Tool exec: start", 11)
    await inbox.delivered("Turn: completed", 12)
    reloaded = SharedInbox(inbox.config, inbox.sessions, inbox.bus)
    assert len(reloaded.messages(NOTIFICATIONS_CHAT_ID)) == 2
    assert inbox.sessions.read_session_file("websocket:shared-notifications") is None
    assert inbox.sessions.read_session_file("telegram:7") is None
    assert inbox._path.stat().st_mode & 0o777 == 0o600
    changed_owner = inbox.config.model_copy(update={"main_chat_id": "8"})
    assert SharedInbox(changed_owner, inbox.sessions, inbox.bus).messages(NOTIFICATIONS_CHAT_ID) == []


async def test_webui_final_answer_mirrors_once_without_rewriting_history(inbox):
    session = inbox.sessions.get_or_create("telegram:7")
    session.add_message("user", "hello from webui")
    session.add_message("assistant", "answer")
    inbox.sessions.save(session)
    context = RuntimeEventContext("websocket", MAIN_CHAT_ID, "telegram:7")
    event = SessionTurnPersisted(context, "turn-1", "owner")
    await inbox.observe_runtime(event)
    await inbox.observe_runtime(event)
    mirrored = await inbox.bus.consume_outbound()
    assert (mirrored.channel, mirrored.chat_id, mirrored.content) == ("telegram", "7", "answer")
    assert inbox.bus.outbound_size == 0
    assert len(inbox.messages(MAIN_CHAT_ID)) == 2
    await inbox.observe_runtime(SessionTurnPersisted(RuntimeEventContext("telegram", "7", "telegram:7"), "turn-2", "7"))
    assert inbox.bus.outbound_size == 0  # Already delivered in Telegram; do not send twice.


async def test_http_requires_operator_token_and_returns_same_receipts(inbox, tmp_path):
    services = gateway(inbox, tmp_path)
    await inbox.delivered("Turn: completed", 33)
    key = "websocket:shared-notifications"
    denied = services.http._handle_webui_thread_get(Request("/", Headers()), key)
    assert denied.status_code == 401
    token = services.tokens.issue_api_token(300)
    request = Request("/", Headers({"Authorization": f"Bearer {token}"}))
    result = services.http._handle_webui_thread_get(request, key)
    assert result.status_code == 200
    assert json.loads(result.body)["messages"] == inbox.messages(NOTIFICATIONS_CHAT_ID)
    listing = services.http._sessions_list_payload()
    assert [row["shared_stream"] for row in listing["sessions"]] == ["notifications", "main"]
    assert "-1007" not in json.dumps(listing)
    assert services.http._handle_session_delete(request, key).status_code == 403
    assert services.http._handle_webui_thread_get(request, "telegram:7").status_code == 404


async def test_reserved_chats_reject_client_audience_and_notifications_reject_writes(inbox, tmp_path):
    services = gateway(inbox, tmp_path)
    channel = WebSocketChannel(WebSocketConfig(), inbox.bus, gateway=services)
    sent = AsyncMock()
    channel.webui_send_event = sent
    client = object()
    router = channel._commands
    await router.dispatch(client, "untrusted", {"type": "attach", "chat_id": MAIN_CHAT_ID})
    assert sent.call_args.kwargs["detail"] == "access_denied"
    services.endpoint.webui_connections.add(client)
    await router.dispatch(client, "operator", {"type": "message", "chat_id": NOTIFICATIONS_CHAT_ID, "content": "run exec"})
    assert sent.call_args.kwargs["detail"] == "read_only_chat"
    assert inbox.bus.inbound_size == 0


@pytest.mark.parametrize("patch", [
    {"mainChatId": ""}, {"mainChatId": "-8"},
])
def test_shared_config_requires_explicit_private_owner(patch):
    with pytest.raises(ValidationError):
        TelegramTechnicalConfig.model_validate({"enabled": True, "chatId": "-1007", "mainChatId": "7", "sharedInbox": True, **patch})


def test_shared_config_rejects_multiuser_or_wildcard_allowlist():
    for allow_from in (["*"], ["7", "8"], []):
        with pytest.raises(ValidationError, match="allowFrom"):
            TelegramConfig(token="123:token", allow_from=allow_from, technical={
                "enabled": True, "chatId": "-1007", "mainChatId": "7", "sharedInbox": True,
            })


async def test_command_output_does_not_mirror_raw_results_or_repeat_previous_answer(inbox):
    session = inbox.sessions.get_or_create("telegram:7")
    session.add_message("user", "hello")
    session.add_message("assistant", "previous answer")
    session.add_message("assistant", "RAW_COMMAND_SECRET", _command=True)
    inbox.sessions.save(session)
    event = SessionTurnPersisted(RuntimeEventContext("websocket", MAIN_CHAT_ID, "telegram:7"), "command-turn", "owner")
    await inbox.observe_runtime(event)
    assert inbox.bus.outbound_size == 0
    assert "SECRET" not in json.dumps(inbox.thread(MAIN_CHAT_ID))


async def test_channel_manager_composes_shared_routing_without_global_unified_leak(inbox, tmp_path):
    from nanobot.channels.base import BaseChannel
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config

    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "unifiedSession": True}},
        "channels": {"telegram": {"enabled": True, "token": "123:token", "allowFrom": ["7"],
            "technical": {"enabled": True, "chatId": "-1007", "mainChatId": "7", "sharedInbox": True}}},
    })
    manager = ChannelManager(config, inbox.bus, session_manager=inbox.sessions, config_path=tmp_path / "config.json")
    telegram = manager.channels["telegram"]
    websocket = manager.channels["websocket"]
    assert websocket.gateway.shared_inbox is manager._shared_inbox
    assert telegram._technical.on_delivered is not None
    await BaseChannel._handle_message(telegram, "7", "7", "hello", is_dm=False)
    inbound = await inbox.bus.consume_inbound()
    assert inbound.session_key_override == "telegram:7"
    await BaseChannel._handle_message(websocket, "owner", MAIN_CHAT_ID, "hello", is_dm=False)
    inbound = await inbox.bus.consume_inbound()
    assert inbound.session_key_override == "telegram:7"
    await BaseChannel._handle_message(websocket, "owner", "ordinary", "hello", is_dm=False)
    inbound = await inbox.bus.consume_inbound()
    assert inbound.session_key_override == "websocket:ordinary"


async def test_owner_mapping_change_deactivates_existing_views_and_callbacks(inbox, tmp_path):
    services = gateway(inbox, tmp_path)
    await inbox.delivered("Turn: completed", 1)
    changed = inbox.config.model_copy(update={"main_chat_id": "8"})
    assert not inbox.matches_config(changed)
    inbox.active = False
    await inbox.delivered("Tool exec: start", 2)
    assert len(inbox._receipts()) == 1
    assert inbox.rows() == [] and inbox.messages(MAIN_CHAT_ID) == []
    token = services.tokens.issue_api_token(300)
    request = Request("/", Headers({"Authorization": f"Bearer {token}"}))
    assert services.http._handle_webui_thread_get(request, "websocket:shared-notifications").status_code == 404


async def test_shared_inbox_works_without_optional_technical_destination(inbox, tmp_path):
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.schema import Config

    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "unifiedSession": True}},
        "channels": {"telegram": {"enabled": True, "token": "123:token", "allowFrom": ["7"],
            "technical": {"enabled": False, "mainChatId": "7", "sharedInbox": True}}},
    })
    manager = ChannelManager(config, inbox.bus, session_manager=inbox.sessions, config_path=tmp_path / "config.json")
    shared = manager._shared_inbox
    assert shared is not None and shared.active
    assert len(shared.rows()) == 2
    telegram = manager.channels["telegram"]
    assert telegram.on_notification_delivered is not None
    await telegram.on_notification_delivered("Calendar changed", "user-123")
    assert shared.messages(NOTIFICATIONS_CHAT_ID)[0]["content"] == "Calendar changed"
    assert shared.sessions.read_session_file(shared.main_session_key) is None


@pytest.mark.parametrize(("technical_token", "main_token", "new_technical_token", "new_main_token", "matches"), [
    ("", "123:before", "", "456:after", False),
    ("", "123:before", "", "123:rotated", True),
    ("987:before", "123:main", "654:after", "123:main", False),
    ("987:before", "123:main", "987:rotated", "123:main", True),
    ("987:before", "123:main", "987:before", "456:changed-main", True),
    ("123:explicit", "123:main", "", "123:rotated", True),
    ("", "123:main", "123:explicit", "123:main", True),
    ("987:explicit", "123:main", "", "123:main", False),
])
@pytest.mark.parametrize("technical_enabled", [False, True])
async def test_rebuild_checks_effective_notification_bot_identity(
    inbox, tmp_path, technical_token, main_token, new_technical_token, new_main_token,
    matches, technical_enabled,
):
    from nanobot.channels.manager import ChannelManager
    from nanobot.channels.telegram.runtime import TelegramChannel
    from nanobot.config.schema import Config

    section = {"enabled": True, "token": main_token, "allowFrom": ["7"], "technical": {
        "enabled": technical_enabled, "chatId": "-1007", "mainChatId": "7",
        "sharedInbox": True, "token": technical_token,
    }}
    config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path / "workspace")}},
        "channels": {"telegram": section},
    })
    manager = ChannelManager(config, inbox.bus, session_manager=inbox.sessions, config_path=tmp_path / "config.json")
    shared = manager._shared_inbox
    assert shared is not None and shared.active
    old_callback = manager.channels["telegram"].on_notification_delivered
    await old_callback("Already delivered", "before-rebuild")
    changed = {**section, "token": new_main_token, "technical": {
        **section["technical"], "token": new_technical_token,
    }}
    # Same adapter-construction path as reload, but no channel start or network.
    rebuilt = manager._build_channel("telegram", TelegramChannel, changed, runtime_name="telegram")
    assert shared.active is matches
    assert (rebuilt.on_notification_delivered is not None) is matches
    assert (rebuilt.technical_notifier.on_delivered is not None) is matches
    if matches:
        assert len(shared.rows()) == 2
        assert shared.messages(NOTIFICATIONS_CHAT_ID)[0]["content"] == "Already delivered"
    else:
        assert shared.rows() == []
        assert shared.messages(NOTIFICATIONS_CHAT_ID) == []
        assert shared.messages(MAIN_CHAT_ID) == []
        assert shared.session_key("websocket", MAIN_CHAT_ID) == "websocket:shared-main"
        await old_callback("Stale callback", "after-rebuild")
        assert len(shared._receipts()) == 1
        reverted = manager._build_channel("telegram", TelegramChannel, section, runtime_name="telegram")
        assert not shared.active  # Recomposition, not another hot reload, is required.
        assert reverted.on_notification_delivered is None
        assert reverted.technical_notifier.on_delivered is None
    # The inbox retains only the public bot ID, never either credential.
    assert shared.config.token == ""
    stored = shared._path.read_text()
    for token in (technical_token, main_token, new_technical_token, new_main_token):
        if token:
            assert token not in stored
