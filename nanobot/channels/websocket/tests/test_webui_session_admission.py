from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.runtime_context import public_history_message
from nanobot.session.manager import SessionManager
from nanobot.session.webui_turns import (
    WebuiTurnCoordinator,
    WebuiTurnRoutePolicy,
    clear_websocket_turns,
)
from nanobot.webui.session_identity import channel_session_chat_id, webui_session_key


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

    async def frame(self, kind: str, chat_id: str, **fields: Any) -> None:
        await self.channel._dispatch_envelope(
            self.connection, "webui-client", {"type": kind, "chat_id": chat_id, **fields},
        )

    async def message(self, chat_id: str, text: str = "hello", **fields: Any) -> InboundMessage:
        await self.frame("message", chat_id, content=text, webui=True, **fields)
        return await asyncio.wait_for(self.bus.consume_inbound(), timeout=3)

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
    routing = WebuiTurnRoutePolicy(sessions)
    loop = AgentLoop(
        bus=bus, provider=provider, workspace=workspace, session_manager=sessions,
        turn_delivery_factory=TurnDeliveryFactory(bus, route_policy=routing, route_admission=routing.admit),
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


_TELEGRAM_CHAT = "-100123"
_TOPIC = f"telegram:{_TELEGRAM_CHAT}:topic:17"


class _TelegramIngress(BaseChannel):
    """Use the adapter admission seam with an actual topic key and no platform credentials."""

    name = "telegram"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send(self, msg: OutboundMessage) -> None:
        pass

    async def input(self, text: str) -> InboundMessage:
        assert await self._handle_message(
            "user", _TELEGRAM_CHAT, text, session_key=_TOPIC, metadata={"message_thread_id": 17},
        )
        return await self.bus.consume_inbound()


@pytest.fixture
async def channel_runtime(runtime: _Runtime) -> AsyncIterator[_Runtime]:
    coordinator = WebuiTurnCoordinator(runtime.bus, runtime.sessions, runtime.loop.schedule_background)
    with coordinator.connected():
        yield runtime


@pytest.mark.parametrize("first_origin", ["telegram", "websocket"])
async def test_shared_channel_turns_share_context_but_keep_reply_routes(
    channel_runtime: _Runtime, monkeypatch: pytest.MonkeyPatch, first_origin: str,
) -> None:
    runtime = channel_runtime
    state = runtime.sessions.state
    original = await state.get(_TOPIC)
    original.add_message("user", "Earlier channel context")
    original.add_message("assistant", "Earlier reply")
    original.metadata["_compaction_route"] = {
        "channel": "telegram", "chat_id": _TELEGRAM_CHAT, "metadata": {"message_thread_id": 17},
    }
    await state.finish_turn(original)
    sibling = await state.get(f"telegram:{_TELEGRAM_CHAT}:topic:18")
    sibling.add_message("user", "Other topic context")
    await state.finish_turn(sibling)
    alias = channel_session_chat_id(_TOPIC)
    assert alias is not None
    await runtime.frame("attach", alias)
    assert any(frame["event"] == "attached" and frame["chat_id"] == alias for frame in runtime.connection.sent)

    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []
    web_text, external_text = "Web question", "Telegram question"

    async def generate(messages, **_kwargs):
        calls.append("\n".join(str(row["content"]) for row in messages if row["role"] == "user"))
        if len(calls) == 1:
            entered.set()
            await release.wait()
        text = web_text if web_text in str(messages[-1]["content"]) else external_text
        return LLMResponse(content=f"Answer: {text}", finish_reason="stop")

    monkeypatch.setattr(runtime.provider, "chat", generate)
    telegram = _TelegramIngress({"allowFrom": ["user"]}, runtime.bus)
    prompts = {
        "websocket": lambda: runtime.message(alias, web_text, turn_id="browser-turn"),
        "telegram": lambda: telegram.input(external_text),
    }
    second_origin = "websocket" if first_origin == "telegram" else "telegram"
    await runtime.loop._dispatch_inbound(await prompts[first_origin]())
    await asyncio.wait_for(entered.wait(), timeout=3)
    queued = await prompts[second_origin]()
    assert queued.session_key == _TOPIC
    await runtime.loop._dispatch_inbound(queued)
    tasks = tuple(runtime.loop._active_tasks[_TOPIC])
    release.set()
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

    assert len(calls) == 2
    first_text, second_text = (external_text, web_text) if first_origin == "telegram" else (web_text, external_text)
    assert "Earlier channel context" in calls[0] and second_text not in calls[0]
    assert first_text in calls[1] and second_text in calls[1] and "Other topic context" not in calls[1]
    answers: dict[str, tuple[str, str]] = {}
    while runtime.bus.outbound_size:
        reply = await runtime.bus.consume_outbound()
        if reply.content.startswith("Answer:"):
            answers[reply.content] = (reply.channel, reply.chat_id)
        if reply.channel == "websocket":
            await runtime.channel.send(reply)
    assert answers == {
        f"Answer: {web_text}": ("websocket", alias), f"Answer: {external_text}": ("telegram", _TELEGRAM_CHAT),
    }
    assert any(frame["event"] == "session_updated" and frame.get("scope") == "thread"
               and frame["chat_id"] == alias for frame in runtime.connection.sent)

    snapshot = await state.read(_TOPIC)
    assert snapshot is not None
    assert snapshot.metadata["_compaction_route"]["channel"] == "telegram"
    user, assistant, next_user, next_assistant = snapshot.messages[-4:]
    first_label = "telegram" if first_origin == "telegram" else "webui"
    assert (user["entry_channel"], next_user["entry_channel"]) == (
        first_label, "webui" if first_label == "telegram" else "telegram",
    )
    assert assistant["response_input_ids"] == [user["input_id"]]
    assert next_assistant["response_input_ids"] == [next_user["input_id"]]
    assert await state.read(webui_session_key(alias)) is None
    assert await state.project_history(_TOPIC, lambda reader: reader.all_facts()) == []


async def test_shared_channel_web_stop_cancels_external_turn_without_reset(
    channel_runtime: _Runtime, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = channel_runtime
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def generate(*_args, **_kwargs):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    monkeypatch.setattr(runtime.provider, "chat", generate)
    telegram = _TelegramIngress({"allowFrom": ["user"]}, runtime.bus)
    await runtime.loop._dispatch_inbound(await telegram.input("Keep this input"))
    await asyncio.wait_for(entered.wait(), timeout=3)
    alias = channel_session_chat_id(_TOPIC)
    assert alias is not None
    non_webui = _Connection()
    try:
        await runtime.channel._dispatch_envelope(non_webui, "tui", {"type": "attach", "chat_id": alias})
        assert non_webui.sent[-1]["detail"] == "session_unavailable"
    finally:
        await runtime.channel._cleanup_connection(non_webui)
    await runtime.frame("message", alias, content="/new@bot", webui=True)
    assert runtime.connection.sent[-1]["detail"] == "command_unavailable"
    await asyncio.wait_for(runtime.loop._dispatch_inbound(await runtime.message(alias, "/stop")), timeout=5)
    assert cancelled.is_set()
    snapshot = await runtime.sessions.state.read(_TOPIC)
    assert snapshot is not None
    assert "Keep this input" in public_history_message(snapshot.messages[0])["content"]
