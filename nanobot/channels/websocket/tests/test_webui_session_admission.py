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
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.webui.session_list_index import list_webui_sessions


class _Provider(LLMProvider):
    def __init__(self) -> None:
        super().__init__(provider_name="test")
        self.calls = 0

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> LLMResponse:
        self.calls += 1
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

    async def message(self, chat_id: str, text: str = "hello", *, turn_id: str | None = None) -> InboundMessage:
        await self.channel._dispatch_envelope(
            self.connection,
            "webui-client",
            {"type": "message", "chat_id": chat_id, "content": text, "webui": True, "turn_id": turn_id},
        )
        return await self.bus.consume_inbound()

    async def execute(self, message: InboundMessage) -> None:
        await self.loop._enqueue_session_message(message)
        tasks = self.loop._active_tasks[message.session_key]
        await asyncio.gather(*tuple(tasks))


@pytest.fixture
async def runtime(tmp_path: Path) -> AsyncIterator[_Runtime]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = Config.model_validate({"agents": {"defaults": {
        "workspace": str(workspace), "unifiedSession": True,
    }}})
    bus = MessageBus()
    sessions = SessionManager(workspace)
    provider = _Provider()
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=workspace,
        session_manager=sessions, model_presets={"default": ModelPresetConfig(model=provider.get_default_model())},
    )
    manager = ChannelManager(
        config, bus, session_manager=sessions, webui_static_dist=False,
        config_path=tmp_path / "config.json",
    )
    channel = manager.channels["websocket"]
    assert isinstance(channel, WebSocketChannel)
    connection = _Connection()
    channel._webui_connections.add(connection)
    try:
        yield _Runtime(bus, sessions, loop, channel, connection, provider)
    finally:
        chat_ids = tuple(channel._subs)
        await channel._cleanup_connection(connection)
        channel.gateway.temporary_chats.close()
        for chat_id in chat_ids:
            clear_websocket_turns(chat_id)
        await loop.aclose()


async def test_webui_admission_executes_with_the_routed_session(runtime: _Runtime) -> None:
    for chat_id in ("chat-a", "chat-b"):
        message = await runtime.message(chat_id)
        await runtime.execute(message)

        key = f"websocket:{chat_id}"
        session = await runtime.sessions.state.read(key)
        assert session is not None
        assert [public_history_message(record)["content"] for record in session.messages
                if record["role"] == "user"] == ["hello"]
        assert session.metadata["webui"] is True
    assert runtime.provider.calls == 2


async def test_preset_draft_appears_in_history_only_after_the_first_prompt(runtime: _Runtime) -> None:
    async def send(text: str, turn_id: str) -> list[str]:
        message = await runtime.message("draft", text, turn_id=turn_id)
        await runtime.execute(message)
        return [row["key"] for row in list_webui_sessions(runtime.sessions)]

    assert await send("/model missing", "webui-system:attempt") == []
    assert await send("/model default", "webui-system:retry") == []
    assert runtime.provider.calls == 0
    assert await send("hello", "first-prompt") == ["websocket:draft"]
    assert runtime.provider.calls == 1
    assert await send("/model missing", "webui-system:existing") == ["websocket:draft"]


async def test_existing_session_preview_ignores_picker_but_includes_typed_model_command(runtime: _Runtime) -> None:
    chat = "existing"
    key = f"websocket:{chat}"
    await runtime.sessions.state.get(key)

    async def switch(turn_id: str) -> str:
        msg = await runtime.message(chat, "/model default", turn_id=turn_id)
        await runtime.execute(msg)
        while runtime.bus.outbound_size:
            await runtime.channel.send(await runtime.bus.consume_outbound())
        assert any(event.get("turn_id") == turn_id and event.get("command_result") == {
            "command": "/model", "switched_preset": "default",
        } for event in runtime.connection.sent), runtime.connection.sent
        row, = list_webui_sessions(runtime.sessions)
        return row["preview"]

    assert await switch("webui-system:picker") == ""
    assert await switch("typed") == "/model default"


@pytest.mark.parametrize("operation", ["reset", "delete"])
async def test_replaced_execution_session_rejects_accepted_input(
    runtime: _Runtime, operation: str,
) -> None:
    message = await runtime.message("chat-stale")
    key = message.session_key
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
    state = runtime.sessions.state
    retired = await state.get("unified:default")
    retired.add_message("user", "Old shared history")
    await state.finish_turn(retired)

    await runtime.channel._dispatch_envelope(
        runtime.connection, "webui-client", {"type": "new_temporary_chat"},
    )
    chat_id = next(event["chat_id"] for event in runtime.connection.sent
                   if event["event"] == "attached")
    first = await runtime.message(chat_id)
    await runtime.execute(first)
    assert runtime.provider.calls == 1
    assert first.session_key == f"websocket:{chat_id}"
    assert {row["key"] for row in await state.list_sessions()} == {retired.key}
    assert history.read(f"websocket:{chat_id}") == []

    queued = await runtime.message(chat_id, "discarded input")
    await runtime.channel.gateway.temporary_chats.discard(runtime.connection, chat_id)
    await runtime.execute(queued)

    assert runtime.provider.calls == 1
    assert await state.read(first.session_key) is None
    assert {row["key"] for row in await state.list_sessions()} == {retired.key}
    saved = runtime.sessions.read_session_snapshot(retired.key)
    assert saved is not None and saved.messages == retired.messages
