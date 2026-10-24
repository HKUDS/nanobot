"""Session effort travels through authenticated messages, not a settings service."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.loop import AgentLoop
from nanobot.agent.model_presets import configured_model_presets
from nanobot.bus.events import INBOUND_META_REASONING_EFFORT, INBOUND_META_USER_SHELL
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.factory import ProviderSnapshot, provider_signature
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import SESSION_REASONING_EFFORT_METADATA_KEY
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.webui.gateway_services import GatewayServices, build_gateway_services
from nanobot.webui.session_projection import WebUISessionProjection


@dataclass
class Gateway:
    path: Path
    sessions: SessionManager
    bus: MessageBus
    services: GatewayServices
    channel: WebSocketChannel
    headers: Headers
    sequence: int = 0
    chats: set[str] = field(default_factory=set)

    @property
    def config(self):
        return load_config(self.path)

    def connection(self, audience="webui"):
        connection = MagicMock()
        connection.send = AsyncMock()
        connection.request = Request("/", Headers())
        if audience is not None:
            token = self.services.tokens.issue_token(60, audience=audience)
            assert self.channel._authorize_websocket_handshake(connection, {"token": [token]}) is None
        return connection

    @staticmethod
    def events(connection):
        return [json.loads(call.args[0]) for call in connection.send.await_args_list]

    async def get_sessions(self, *, authenticated=True):
        return await self.services.http.dispatch(
            SimpleNamespace(remote_address=("127.0.0.1", 12345)),
            Request("/api/sessions", self.headers if authenticated else Headers()),
        )

    async def send(self, *, connection=None, chat_id="chat", content="hello", **fields):
        connection = connection if connection is not None else self.connection()
        self.sequence += 1
        self.chats.add(chat_id)
        await self.channel._dispatch_envelope(connection, "test-client", {
            "type": "message", "chat_id": chat_id, "content": content,
            "webui": True, "turn_id": f"turn-{self.sequence}", **fields,
        })
        return connection

    async def incoming(self, **fields):
        connection = await self.send(**fields)
        assert not any(event["event"] == "error" for event in self.events(connection))
        assert self.bus.inbound_size > 0
        return await asyncio.wait_for(self.bus.consume_inbound(), 3)

    async def run(self, loop, **fields):
        message = await self.incoming(**fields)
        await loop._dispatch_one(message, asyncio.Queue())
        return message

    def loop(self, provider, *, sessions=None):
        def snapshot(preset_name=None):
            config = self.config
            preset = config.resolve_preset(preset_name)
            return ProviderSnapshot(
                provider=provider, model=preset.model, generation=preset.to_generation_settings(),
                context_window_tokens=preset.context_window_tokens,
                signature=provider_signature(config, preset=preset), model_preset=preset_name,
            )

        config = self.config
        loop = AgentLoop(
            bus=self.bus, provider=provider, workspace=config.workspace_path,
            session_manager=self.sessions if sessions is None else sessions,
            model=config.resolve_preset().model, context_window_tokens=128000,
            provider_signature=snapshot().signature,
            provider_snapshot_loader=snapshot, preset_snapshot_loader=snapshot,
            model_presets=configured_model_presets(config),
        )
        loop.schedule_background = lambda coro: coro.close()
        return loop


@pytest.fixture
async def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.paths.get_data_dir", lambda: tmp_path)

    def no_catalog(*args, **kwargs):
        raise AssertionError("normal message admission must not fetch model catalogs")

    monkeypatch.setattr(httpx, "get", no_catalog)
    config = Config.model_validate({
        "agents": {"defaults": {
            "workspace": str(tmp_path / "workspace"), "model": "deepseek-flash", "provider": "deepseek",
            "reasoning_effort": "high", "max_tokens": 256, "context_window_tokens": 128000,
        }},
        "providers": {"deepseek": {"api_key": "test-key-not-a-credential"}},
        "model_presets": {"deep": {
            "model": "deepseek-v4-pro", "provider": "deepseek", "reasoning_effort": "low",
            "max_tokens": 256, "context_window_tokens": 128000,
        }},
    })
    path = tmp_path / "config.json"
    save_config(config, path)
    sessions = SessionManager(config.workspace_path, sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    ws_config = WebSocketConfig(token="test-bootstrap", allow_from=["*"])
    services = build_gateway_services(
        config=ws_config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=config.workspace_path, default_restrict_to_workspace=True, config_path=path,
        runtime_model_name=None, runtime_surface="gateway", runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(ws_config, bus, gateway=services)
    token = services.tokens.issue_api_token(60)
    gateway = Gateway(path, sessions, bus, services, channel, Headers({"Authorization": f"Bearer {token}"}))
    yield gateway
    await channel._commands.close()
    await sessions.state.aclose()
    for chat_id in gateway.chats:
        clear_websocket_turns(chat_id)


class RecordingProvider(LLMProvider):
    def __init__(self, *, error=False, tool_first=False):
        super().__init__(provider_name="deepseek")
        self.generation = GenerationSettings(max_tokens=256, reasoning_effort="high")
        self.calls = []
        self.entered = None
        self.release = None
        self.error = error
        self.tool_first = tool_first

    def get_default_model(self):
        return "deepseek-flash"

    def estimate_prompt_tokens(self, messages, tools=None, model=None):
        return 100, "test"

    async def chat(self, messages, tools=None, model=None, **kwargs):
        self.calls.append(kwargs.get("reasoning_effort"))
        if self.entered is not None:
            self.entered.set()
            await self.release.wait()
        if self.tool_first and len(self.calls) == 1:
            return LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[
                ToolCallRequest(id="read", name="read_file", arguments={"path": "answer.py"}),
            ])
        if self.error:
            return LLMResponse(content=None, finish_reason="error", error_kind="server_error")
        return LLMResponse(content="done", finish_reason="stop")


async def test_draft_reads_do_not_save_until_normal_message_and_project_last_used_value(gateway):
    before = gateway.path.read_bytes()
    assert (await gateway.get_sessions(authenticated=False)).status_code == 401
    assert json.loads((await gateway.get_sessions()).body) == {"sessions": []}
    terminal = await gateway.services.http.dispatch(
        SimpleNamespace(remote_address=("127.0.0.1", 12345)),
        Request("/webui/terminal", Headers({"Authorization": "Bearer test-bootstrap"})),
    )
    assert "webui.reasoning-effort.v1" in json.loads(terminal.body)["webui"]["capabilities"]
    connection = gateway.connection()
    await gateway.channel._dispatch_envelope(connection, "test-client", {"type": "new_chat"})
    attached = next(event for event in gateway.events(connection) if event["event"] == "attached")
    chat_id = attached["chat_id"]
    assert attached["reasoning_effort"] is None
    assert await gateway.sessions.state.read_metadata(f"websocket:{chat_id}") is None
    assert json.loads((await gateway.get_sessions()).body) == {"sessions": []}

    provider = RecordingProvider()
    await gateway.run(gateway.loop(provider), connection=connection, chat_id=chat_id, reasoning_effort="none")
    saved = await gateway.sessions.state.read(f"websocket:{chat_id}")
    assert saved.metadata[SESSION_REASONING_EFFORT_METADATA_KEY] == "none"
    assert [message["role"] for message in saved.messages] == ["user", "assistant"]
    assert provider.calls == ["none"]
    rows = json.loads((await gateway.get_sessions()).body)["sessions"]
    assert [(row["key"], row["reasoning_effort"]) for row in rows] == [(saved.key, "none")]
    await gateway.channel._dispatch_envelope(connection, "test-client", {"type": "attach", "chat_id": chat_id})
    attached = next(event for event in reversed(gateway.events(connection)) if event["event"] == "attached")
    assert attached["reasoning_effort"] == "none"
    assert gateway.path.read_bytes() == before
    assert provider.generation.reasoning_effort == "high"


@pytest.mark.parametrize("value", [False, 0, {}, [], "", " ", " high", "high ", "high\nlow"])
async def test_invalid_effort_rejects_normal_message_without_session_input(gateway, value):
    connection = await gateway.send(reasoning_effort=value)
    assert gateway.events(connection)[-1]["event"] == "error"
    assert "reasoning_effort" in gateway.events(connection)[-1]["detail"]
    assert gateway.bus.inbound_size == 0
    assert await gateway.sessions.state.read_metadata("websocket:chat") is None


@pytest.mark.parametrize("audience,fields", [
    (None, {}), ("client", {}), ("webui", {"webui": False}),
])
async def test_only_trusted_webui_can_select_effort(gateway, audience, fields):
    connection = await gateway.send(connection=gateway.connection(audience), reasoning_effort="low", **fields)
    assert gateway.events(connection)[-1]["event"] == "error"
    assert gateway.bus.inbound_size == 0
    assert await gateway.sessions.state.read_metadata("websocket:chat") is None


@pytest.mark.parametrize("content,fields,effort,dispatched", [
    ("!echo harmless", {"user_shell": True}, None, "/__shell echo harmless"),
    ("/restart", {}, "low", "/restart"),
    ("/restart", {"turn_id": "webui-system:restart-effort"}, None, "/restart"),
    ("/status", {}, "low", "/status"),
])
async def test_trusted_shell_and_side_channels_ignore_composer_effort(
    gateway, content, fields, effort, dispatched,
):
    await gateway.run(gateway.loop(RecordingProvider()), reasoning_effort="max")
    message = await gateway.incoming(content=content, reasoning_effort=effort, **fields)
    assert message.content == dispatched
    assert INBOUND_META_REASONING_EFFORT not in message.metadata
    assert (message.metadata.get(INBOUND_META_USER_SHELL) is True) == ("user_shell" in fields)
    assert (await gateway.sessions.state.read("websocket:chat")).metadata[SESSION_REASONING_EFFORT_METADATA_KEY] == "max"


async def test_non_webui_metadata_cannot_spoof_selection_and_legacy_input_still_works(gateway):
    provider = RecordingProvider()
    message = await gateway.run(
        gateway.loop(provider), connection=gateway.connection("client"), webui=False,
        metadata={INBOUND_META_REASONING_EFFORT: "low"}, _reasoning_effort="low",
    )
    assert INBOUND_META_REASONING_EFFORT not in message.metadata
    assert provider.calls == ["high"]
    assert SESSION_REASONING_EFFORT_METADATA_KEY not in (await gateway.sessions.state.read("websocket:chat")).metadata


async def test_missing_inherits_null_follows_preset_unknown_string_is_not_catalog_validated(gateway):
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    await gateway.run(loop, reasoning_effort="future-effort")
    await gateway.run(loop)
    await gateway.run(loop, chat_id="other")
    await gateway.run(loop, reasoning_effort=None)
    await gateway.run(loop)
    assert provider.calls == ["future-effort", "future-effort", "high", "high", "high"]
    assert (await gateway.sessions.state.read("websocket:chat")).metadata.get(SESSION_REASONING_EFFORT_METADATA_KEY) is None
    assert (await gateway.services.session_projection.attach_fields("websocket:chat"))["reasoning_effort"] is None


async def test_reload_recovers_last_used_effort_without_changing_another_host_or_session(gateway, tmp_path):
    await gateway.run(gateway.loop(RecordingProvider()), reasoning_effort="low")
    fresh = SessionManager(gateway.config.workspace_path, sessions_root=gateway.path.parent / "sessions")
    other_host = SessionManager(tmp_path / "other-workspace", sessions_root=tmp_path / "other-sessions")
    try:
        assert (await WebUISessionProjection(fresh).attach_fields("websocket:chat"))["reasoning_effort"] == "low"
        assert (await WebUISessionProjection(fresh).attach_fields("websocket:other"))["reasoning_effort"] is None
        assert (await WebUISessionProjection(other_host).attach_fields("websocket:chat"))["reasoning_effort"] is None
        provider = RecordingProvider()
        await gateway.loop(provider, sessions=fresh).process_direct("after restart", session_key="websocket:chat")
        assert provider.calls == ["low"]
        assert await other_host.state.list_sessions() == []
    finally:
        await fresh.state.aclose()
        await other_host.state.aclose()


async def test_normal_model_command_clears_override_before_next_preset_execution(gateway):
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    await gateway.run(loop, reasoning_effort="max")
    await gateway.run(loop, content="/model deep", reasoning_effort="none")
    assert SESSION_REASONING_EFFORT_METADATA_KEY not in (await gateway.sessions.state.read("websocket:chat")).metadata
    await gateway.run(loop)
    await gateway.run(loop, reasoning_effort="max")
    await gateway.run(loop, content="/model default")
    await gateway.run(loop)
    assert provider.calls == ["max", "low", "max", "high"]
    assert gateway.config.model_presets["deep"].reasoning_effort == "low"


async def test_running_followup_saves_next_effort_without_mutating_active_snapshot(gateway):
    provider = RecordingProvider(tool_first=True)
    loop = gateway.loop(provider)
    (gateway.config.workspace_path / "answer.py").write_text("answer = 42", encoding="utf-8")
    before = gateway.path.read_bytes()
    provider.entered, provider.release = asyncio.Event(), asyncio.Event()
    await loop._dispatch_inbound(await gateway.incoming(reasoning_effort="low"))
    try:
        await asyncio.wait_for(provider.entered.wait(), 3)
        assert provider.calls == ["low"]
        assert (await gateway.sessions.state.read("websocket:chat")).metadata[SESSION_REASONING_EFFORT_METADATA_KEY] == "low"
        await loop._dispatch_inbound(await gateway.incoming(reasoning_effort="max", content="follow up"))
        assert (await gateway.sessions.state.read("websocket:chat")).metadata[SESSION_REASONING_EFFORT_METADATA_KEY] == "max"
        assert provider.generation.reasoning_effort == "high"
    finally:
        provider.release.set()
        await asyncio.gather(*tuple(loop._active_tasks.get("websocket:chat", ())))
    await gateway.run(loop)
    await gateway.run(loop, chat_id="other")
    assert provider.calls == ["low", "low", "max", "high"]
    assert gateway.path.read_bytes() == before
    assert provider.generation.reasoning_effort == "high"


@pytest.mark.parametrize("first,expected", [("low", "low"), (None, "high")])
async def test_later_admission_before_root_save_keeps_own_snapshot_and_latest_metadata(
    gateway, monkeypatch, first, expected,
):
    provider = RecordingProvider(tool_first=True)
    loop = gateway.loop(provider)
    (gateway.config.workspace_path / "answer.py").write_text("answer = 42", encoding="utf-8")
    root = await gateway.incoming(reasoning_effort=first)
    following = await gateway.incoming(reasoning_effort="max", content="follow up")
    entered, release = asyncio.Event(), asyncio.Event()
    prepare_prompt = loop.runner.prepare_prompt

    async def paused_prepare(*args, **kwargs):
        if not entered.is_set():
            entered.set()
            await release.wait()
        return await prepare_prompt(*args, **kwargs)

    monkeypatch.setattr(loop.runner, "prepare_prompt", paused_prepare)
    await loop._dispatch_inbound(root)
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await loop._dispatch_inbound(following)
    finally:
        release.set()
        await asyncio.gather(*tuple(loop._active_tasks.get("websocket:chat", ())))
    assert provider.calls == [expected, expected]
    assert (await gateway.sessions.state.read("websocket:chat")).metadata[SESSION_REASONING_EFFORT_METADATA_KEY] == "max"
    await gateway.run(loop)
    assert provider.calls == [expected, expected, "max"]


async def test_temporary_selection_stays_in_owner_memory_and_never_recreates_after_discard(gateway):
    owner, intruder = gateway.connection(), gateway.connection()
    await gateway.channel._dispatch_envelope(owner, "test-client", {"type": "new_temporary_chat"})
    chat_id = next(event["chat_id"] for event in gateway.events(owner) if event["event"] == "attached")
    key = f"websocket:{chat_id}"
    denied = await gateway.send(connection=intruder, chat_id=chat_id, reasoning_effort="max")
    assert gateway.events(denied)[-1]["detail"] == "temporary_chat_unavailable"
    assert gateway.bus.inbound_size == 0
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    await gateway.run(loop, connection=owner, chat_id=chat_id, reasoning_effort="low")
    await gateway.run(loop, connection=owner, chat_id=chat_id)
    transient = await gateway.sessions.state.read(key)
    assert transient.policy.persist is False
    assert transient.metadata[SESSION_REASONING_EFFORT_METADATA_KEY] == "low"
    assert provider.calls == ["low", "low"]
    assert await gateway.sessions.state.list_sessions() == []
    assert gateway.sessions.read_session_file(key) is None
    late = await gateway.incoming(connection=owner, chat_id=chat_id, reasoning_effort="max")
    await gateway.channel._dispatch_envelope(owner, "test-client", {"type": "discard_temporary_chat", "chat_id": chat_id})
    with pytest.raises(RuntimeError, match="required session is not active"):
        await loop._process_message(late)
    assert await gateway.sessions.state.read(key) is None
    assert await gateway.sessions.state.list_sessions() == []


async def test_primary_override_does_not_replace_fallback_effort(gateway):
    primary, fallback = RecordingProvider(error=True), RecordingProvider()
    config = gateway.config
    config.agents.defaults.fallback_models = ["deep"]
    save_config(config, gateway.path)
    wrapped = FallbackProvider(primary, [config.model_presets["deep"]], lambda _: fallback)
    await gateway.run(gateway.loop(wrapped), reasoning_effort="max")
    assert primary.calls == ["max"]
    assert fallback.calls == ["low"]
    assert primary.generation.reasoning_effort == "high"
