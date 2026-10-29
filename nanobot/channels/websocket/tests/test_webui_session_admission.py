"""WebUI admission binds the generation of the session that executes the turn."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.manager import ChannelManager
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.keys import UNIFIED_SESSION_KEY, session_key_for_channel
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import model_preset_from_metadata
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.utils.restart import RestartController


class _Provider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(provider_name="test")
        self.calls = 0
        self.models: list[str | None] = []

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        self.models.append(kwargs.get("model"))
        return LLMResponse(content="hello back", finish_reason="stop")


class _Connection:
    remote_address = None

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


@dataclass
class _Runtime:
    bus: MessageBus
    sessions: SessionManager
    loop: AgentLoop
    channel: WebSocketChannel
    connection: _Connection
    provider: _Provider
    restart: RestartController

    async def message(self, chat_id: str, text: str = "hello", **fields: Any) -> InboundMessage:
        await self.channel._dispatch_envelope(
            self.connection,
            "webui-client",
            {"type": "message", "chat_id": chat_id, "content": text, "webui": True, **fields},
        )
        message = await asyncio.wait_for(self.bus.consume_inbound(), 3)
        assert isinstance(message, InboundMessage)
        return message

    async def execute(self, message: InboundMessage) -> None:
        await self.loop._dispatch_inbound(message)
        tasks = self.loop._active_tasks.get(self.loop._effective_session_key(message), ())
        await asyncio.wait_for(asyncio.gather(*tuple(tasks)), 3)

    async def request(
        self, request_id: str, action: str, payload: dict[str, Any],
        *, connection: _Connection | None = None,
    ) -> None:
        await self.channel._dispatch_envelope(
            connection or self.connection, "webui-client", {
                "type": "webui_request", "request_id": request_id, "action": action,
                "payload": {"expected_gateway_id": self.channel.gateway.tokens.instance_id, **payload},
            },
        )

    async def response(
        self, request_id: str, *, connection: _Connection | None = None,
    ) -> dict[str, Any]:
        connection = connection or self.connection
        task = self.channel._webui_request_tasks.get((connection, request_id))
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), 3)
        await self.channel.webui_flush(connection)
        return next(frame for frame in reversed(connection.sent)
                    if frame.get("request_id") == request_id)


@pytest.fixture(params=[False, True], ids=["separate", "shared"])
async def runtime(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[_Runtime]:
    unified = request.param
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = Config.model_validate({"agents": {"defaults": {
        "workspace": str(workspace), "unifiedSession": unified,
    }}})
    bus = MessageBus()
    sessions = SessionManager(workspace)
    provider = _Provider()
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=workspace,
        session_manager=sessions, unified_session=unified,
        model_presets={
            "default": ModelPresetConfig(model="test-model"),
            "fast": ModelPresetConfig(model="fast-model", context_window_tokens=131_072),
        },
    )
    restart = RestartController()
    manager = ChannelManager(
        config, bus, session_manager=sessions, webui_static_dist=False,
        config_path=tmp_path / "config.json", webui_model_runtime=loop.runtime_resolver,
        webui_restart=restart.request,
    )
    channel = manager.channels["websocket"]
    assert isinstance(channel, WebSocketChannel)
    connection = _Connection()
    channel._webui_connections.add(connection)
    try:
        yield _Runtime(bus, sessions, loop, channel, connection, provider, restart)
    finally:
        chat_ids = tuple(channel._subs)
        await channel._cleanup_connection(connection)
        await channel._commands.close()
        for chat_id in chat_ids:
            clear_websocket_turns(chat_id)
        await loop.aclose()


async def test_webui_admission_executes_with_the_routed_session(runtime: _Runtime) -> None:
    for chat_id in ("chat-a", "chat-b"):
        message = await runtime.message(chat_id)
        await runtime.execute(message)

        key = session_key_for_channel(
            "websocket", chat_id, unified_session=runtime.channel.gateway.unified_session,
        )
        session = await runtime.sessions.state.read(key)
        assert session is not None
        assert [public_history_message(record)["content"] for record in session.messages
                if record["role"] == "user"] == (
            ["hello", "hello"] if key == UNIFIED_SESSION_KEY and chat_id == "chat-b"
            else ["hello"]
        )
        display = await runtime.sessions.state.read_metadata(f"websocket:{chat_id}")
        assert display is not None and display["metadata"]["webui"] is True
    assert runtime.provider.calls == 2


@pytest.mark.parametrize("operation", ["reset", "delete"])
async def test_replaced_execution_session_rejects_accepted_input(
    runtime: _Runtime, operation: str,
) -> None:
    message = await runtime.message("chat-stale")
    key = runtime.loop._effective_session_key(message)
    if operation == "reset":
        await runtime.sessions.state.reset(key)
    else:
        await runtime.sessions.state.delete(key)

    await runtime.execute(message)

    assert runtime.provider.calls == 0
    remaining = await runtime.sessions.state.read(key)
    assert remaining is None or remaining.messages == []


async def test_failed_transport_admission_removes_new_sessions(
    runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject(message: InboundMessage) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(runtime.bus, "publish_inbound", reject)
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await runtime.message("chat-rejected")
    assert await runtime.sessions.state.list_sessions() == []


async def test_temporary_chat_retains_its_own_generation(history, runtime: _Runtime) -> None:
    await runtime.channel._dispatch_envelope(
        runtime.connection, "webui-client", {"type": "new_temporary_chat"},
    )
    chat_id = next(event["chat_id"] for event in runtime.connection.sent
                   if event["event"] == "attached")
    first = await runtime.message(chat_id)
    await runtime.execute(first)
    assert runtime.provider.calls == 1
    assert runtime.loop._effective_session_key(first) == f"websocket:{chat_id}"
    assert await runtime.sessions.state.list_sessions() == []
    assert history.read(f"websocket:{chat_id}") == []

    queued = await runtime.message(chat_id, "discarded input")
    await runtime.channel.gateway.temporary_chats.discard(runtime.connection, chat_id)
    await runtime.execute(queued)

    assert runtime.provider.calls == 1
    assert await runtime.sessions.state.read(first.session_key) is None
    assert await runtime.sessions.state.list_sessions() == []


async def test_invalid_initial_model_does_not_admit_or_lock_project(
    runtime: _Runtime, tmp_path: Path,
) -> None:
    rejected_project = tmp_path / "rejected-project"
    accepted_project = tmp_path / "accepted-project"
    rejected_project.mkdir()
    accepted_project.mkdir()
    await runtime.channel._dispatch_envelope(runtime.connection, "webui-client", {
        "type": "message", "chat_id": "first-model", "content": "hello", "webui": True,
        "initial_model_preset": "missing", "turn_id": "first-attempt",
        "workspace_scope": {"project_path": str(rejected_project), "access_mode": "restricted"},
    })
    await runtime.channel.webui_flush(runtime.connection)

    assert runtime.bus.inbound_size == 0
    assert await runtime.sessions.state.list_sessions() == []
    assert any(frame.get("detail") == "model_selection_rejected" for frame in runtime.connection.sent)

    first = await runtime.message(
        "first-model", turn_id="first-attempt", initial_model_preset="fast",
        workspace_scope={"project_path": str(accepted_project), "access_mode": "restricted"},
    )
    await runtime.execute(first)
    display = await runtime.sessions.state.read_metadata("websocket:first-model")
    assert display is not None
    assert Path(display["metadata"][WORKSPACE_SCOPE_METADATA_KEY]["project_path"]) == accepted_project
    assert runtime.provider.models == ["fast-model"]


@pytest.mark.parametrize("temporary", [False, True], ids=["saved", "temporary"])
async def test_initial_model_applies_to_first_turn_without_overwriting_later_selection(
    runtime: _Runtime, temporary: bool,
) -> None:
    chat_id = "selected"
    if temporary:
        await runtime.channel._dispatch_envelope(runtime.connection, "webui-client", {"type": "new_temporary_chat"})
        chat_id = next(frame["chat_id"] for frame in runtime.connection.sent if frame["event"] == "attached")
    first = await runtime.message(chat_id, initial_model_preset="fast")
    await runtime.execute(first)
    key = runtime.loop._effective_session_key(first)
    selected = await runtime.sessions.state.read_metadata(key)
    assert selected is not None
    assert model_preset_from_metadata(selected["metadata"]) == "fast"

    later = await runtime.message(chat_id, "follow up", initial_model_preset="default")
    await runtime.execute(later)
    selected = await runtime.sessions.state.read_metadata(key)
    assert selected is not None
    assert model_preset_from_metadata(selected["metadata"]) == "fast"
    assert runtime.provider.models == ["fast-model", "fast-model"]
