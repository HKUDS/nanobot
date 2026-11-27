"""Session choices travel through authenticated ordinary messages."""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent.session_helpers import make_agent_loop
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.model_presets import configured_model_presets
from nanobot.bus.events import INBOUND_META_MODEL_OPTIONS
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse
from nanobot.providers.factory import ProviderSnapshot, provider_signature
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.model_options import ModelOptions
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import SESSION_LOCAL_PRESET_KEY, SessionModelPreset
from nanobot.session.webui_turns import clear_websocket_turns
from nanobot.webui.gateway_services import GatewayServices, build_gateway_services
from nanobot.webui.session_projection import WebUISessionProjection
from nanobot.webui.settings_models import model_settings_payload


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
        loop = make_agent_loop(
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
    config = Config.model_validate({
        "agents": {"defaults": {
            "workspace": str(tmp_path / "workspace"), "model": "deepseek-flash", "provider": "deepseek",
            "reasoning_effort": "high", "max_tokens": 256, "context_window_tokens": 128000,
        }},
        "providers": {"deepseek": {"api_key": "synthetic-key"}},
        "model_presets": {"deep": {
            "model": "deepseek-v4-pro", "provider": "deepseek", "reasoning_effort": "low",
            "max_tokens": 256, "context_window_tokens": 128000,
        }},
    })
    path = tmp_path / "config.json"
    save_config(config, path)
    sessions = SessionManager(config.workspace_path, sessions_root=tmp_path / "sessions")
    bus = MessageBus()
    ws_config = WebSocketConfig(token="synthetic-bootstrap", allow_from=["*"])
    services = build_gateway_services(
        config=ws_config, bus=bus, session_manager=sessions, static_dist_path=None,
        workspace_path=config.workspace_path, default_restrict_to_workspace=True, config_path=path,
        runtime_model_name=None, runtime_surface="gateway", runtime_capabilities_overrides=None,
    )
    channel = WebSocketChannel(ws_config, bus, gateway=services)
    token = services.tokens.issue_api_token(60)
    instance = Gateway(path, sessions, bus, services, channel, Headers({"Authorization": f"Bearer {token}"}))
    yield instance
    await channel._commands.close()
    await sessions.state.aclose()
    for chat_id in instance.chats:
        clear_websocket_turns(chat_id)


class RecordingProvider(LLMProvider):
    def __init__(self, *, error=False):
        super().__init__(provider_name="deepseek")
        self.generation = GenerationSettings(max_tokens=256, reasoning_effort="high")
        self.calls = []
        self.error = error

    def get_default_model(self):
        return "deepseek-flash"

    def estimate_prompt_tokens(self, messages, tools=None, model=None):
        return 100, "test"

    async def chat(self, messages, **kwargs):
        return LLMResponse(content="done")

    async def chat_stream_with_context(self, messages, *, provider_context=None, **kwargs):
        self.calls.append((kwargs.get("reasoning_effort"), provider_context.model_options))
        if self.error:
            return LLMResponse(content=None, finish_reason="error", error_kind="server_error")
        return LLMResponse(content="done")


async def test_draft_then_ordinary_send_persists_and_projects_choices(gateway):
    before = gateway.path.read_bytes()
    connection = gateway.connection()
    await gateway.channel._dispatch_envelope(connection, "test-client", {"type": "new_chat"})
    attached = next(event for event in gateway.events(connection) if event["event"] == "attached")
    assert attached["model_options"] == ModelOptions().to_dict()
    assert await gateway.sessions.state.read_metadata(f"websocket:{attached['chat_id']}") is None
    terminal = await gateway.services.http.dispatch(
        SimpleNamespace(remote_address=("127.0.0.1", 12345)),
        Request("/webui/terminal", Headers({"Authorization": "Bearer synthetic-bootstrap"})),
    )
    assert "webui.model-options.v1" in json.loads(terminal.body)["webui"]["capabilities"]
    provider = RecordingProvider()
    options = ModelOptions("none", False)
    await gateway.run(gateway.loop(provider), model_options=options.to_dict())
    saved = await gateway.sessions.state.read("websocket:chat")
    assert saved.metadata[SESSION_LOCAL_PRESET_KEY] == {
        "base_preset": None, "overrides": options.to_dict(),
    }
    assert [message["role"] for message in saved.messages] == ["user", "assistant"]
    assert provider.calls == [("none", options)]
    response = await gateway.services.http.dispatch(
        SimpleNamespace(remote_address=("127.0.0.1", 12345)), Request("/api/sessions", gateway.headers),
    )
    row = next(row for row in json.loads(response.body)["sessions"] if row["key"] == saved.key)
    assert row["model_options"] == options.to_dict()
    await gateway.channel._dispatch_envelope(connection, "test-client", {"type": "attach", "chat_id": "chat"})
    attached = next(event for event in reversed(gateway.events(connection)) if event["event"] == "attached")
    assert attached["model_options"] == options.to_dict()
    assert gateway.path.read_bytes() == before
    assert provider.generation.reasoning_effort == "high"


@pytest.mark.parametrize("value", [None, [], False, {"extra_body": {}}, {"codex_fast_mode": 1},
                                   {"reasoning_effort": " high"}, {"reasoning_effort": "high\nlow"}])
async def test_invalid_options_reject_before_admitting_session(gateway, value):
    connection = await gateway.send(model_options=value)
    assert gateway.events(connection)[-1]["event"] == "error"
    assert gateway.bus.inbound_size == 0
    assert await gateway.sessions.state.read_metadata("websocket:chat") is None


@pytest.mark.parametrize("audience,fields", [(None, {}), ("client", {}), ("webui", {"webui": False})])
async def test_only_trusted_webui_can_select_options(gateway, audience, fields):
    connection = await gateway.send(connection=gateway.connection(audience), model_options={}, **fields)
    assert gateway.events(connection)[-1]["event"] == "error"
    assert gateway.bus.inbound_size == 0
    assert await gateway.sessions.state.read_metadata("websocket:chat") is None


async def test_missing_preserves_selection_null_inherits_and_sessions_are_isolated(gateway):
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    choice = ModelOptions("future-effort", True)
    await gateway.run(loop, model_options=choice.to_dict())
    await gateway.run(loop)
    await gateway.run(loop, chat_id="other")
    await gateway.run(loop, model_options={"codex_fast_mode": False})
    await gateway.run(loop, model_options={})
    assert provider.calls == [
        ("future-effort", choice), ("future-effort", choice), ("high", ModelOptions()),
        ("high", ModelOptions(codex_fast_mode=False)), ("high", ModelOptions()),
    ]


async def test_each_admitted_input_keeps_its_own_choices_before_runtime_capture(gateway):
    first = await gateway.incoming(model_options=ModelOptions("low", True).to_dict())
    second = await gateway.incoming(model_options=ModelOptions("high", False).to_dict())
    loop = gateway.loop(RecordingProvider())
    session = await gateway.sessions.state.read("websocket:chat")
    earlier = await loop.runtime_for_session(session, input_metadata=first.metadata)
    later = await loop.runtime_for_session(session, input_metadata=second.metadata)
    assert (earlier.generation.reasoning_effort, earlier.model_options.codex_fast_mode) == ("low", True)
    assert (later.generation.reasoning_effort, later.model_options.codex_fast_mode) == ("high", False)
    assert loop.llm_runtime().generation.reasoning_effort == "high"
    assert loop.llm_runtime().model_options == ModelOptions()


@pytest.mark.parametrize("switch_first", [True, False])
async def test_pending_preset_switch_and_messages_save_choices_in_execution_order(gateway, switch_first):
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    await gateway.run(loop, model_options=ModelOptions("max", True).to_dict())
    choice = ModelOptions("high", False)
    fields = [{"content": "/model deep"}, {"model_options": choice.to_dict()}]
    if not switch_first:
        fields.reverse()
    pending = [await gateway.incoming(**item) for item in fields]
    for message in pending:
        await loop._dispatch_one(message, asyncio.Queue())
    assert provider.calls[-1] == ("high", choice)
    saved = await gateway.sessions.state.read("websocket:chat")
    assert SessionModelPreset.from_metadata(saved.metadata) == SessionModelPreset(
        "deep", choice if switch_first else ModelOptions(),
    )


async def test_reload_recovers_last_used_choices_and_preset_switch_clears_both(gateway, tmp_path):
    options = ModelOptions("max", "ultrafast")
    await gateway.run(gateway.loop(RecordingProvider()), model_options=options.to_dict())
    fresh = SessionManager(gateway.config.workspace_path, sessions_root=tmp_path / "sessions")
    other = SessionManager(tmp_path / "other-workspace", sessions_root=tmp_path / "other-sessions")
    try:
        assert (await WebUISessionProjection(fresh).attach_fields("websocket:chat"))["model_options"] == options.to_dict()
        assert (await WebUISessionProjection(other).attach_fields("websocket:chat"))["model_options"] == ModelOptions().to_dict()
        provider = RecordingProvider()
        loop = gateway.loop(provider, sessions=fresh)
        await loop.process_direct("after restart", session_key="websocket:chat")
        assert provider.calls == [("max", options)]
        await loop.set_session_model_preset("websocket:chat", "deep")
        await loop.process_direct("after switch", session_key="websocket:chat")
        assert provider.calls[-1] == ("low", ModelOptions())
        saved = await fresh.state.read("websocket:chat")
        assert SessionModelPreset.from_metadata(saved.metadata) == SessionModelPreset("deep")
    finally:
        await fresh.state.aclose()
        await other.state.aclose()


@pytest.mark.parametrize("content,fields", [("!echo synthetic", {"user_shell": True}), ("/status", {}), ("/restart", {})])
async def test_shell_and_commands_do_not_consume_composer_choices(gateway, content, fields):
    options = ModelOptions("max", True)
    await gateway.run(gateway.loop(RecordingProvider()), model_options=options.to_dict())
    message = await gateway.incoming(content=content, model_options=ModelOptions("low", False).to_dict(), **fields)
    assert INBOUND_META_MODEL_OPTIONS not in message.metadata
    saved = await gateway.sessions.state.read("websocket:chat")
    assert SessionModelPreset.from_metadata(saved.metadata).overrides == options


async def test_fallback_uses_its_own_settings_not_primary_options(gateway):
    primary, fallback = RecordingProvider(error=True), RecordingProvider()
    wrapped = FallbackProvider(primary, [gateway.config.model_presets["deep"]], lambda _: fallback)
    options = ModelOptions("max", True)
    await gateway.run(gateway.loop(wrapped), model_options=options.to_dict())
    assert primary.calls == [("max", options)]
    assert fallback.calls == [("low", ModelOptions())]


def test_settings_describe_codex_fast_mode_and_resolved_preset_default():
    config = Config.model_validate({
        "agents": {"defaults": {"model": "gpt-5.6-sol", "provider": "openai_codex"}},
        "providers": {"openai_codex": {"extra_body": {"service_tier": "priority"}}},
        "model_presets": {
            "standard": {"model": "gpt-5.6-sol", "provider": "openai_codex", "extra_body": {"service_tier": "auto"}},
            "other": {"model": "gpt-5.6", "provider": "openai"},
        },
    })
    payload = model_settings_payload(config, oauth_status=lambda _: {
        "configured": False, "account": None, "expires_at": None, "login_supported": True,
    })
    presets = {row["name"]: row["model_options"] for row in payload["model_presets"]}
    assert presets["default"]["codex_fast_mode"] == {"default": True}
    assert presets["standard"]["codex_fast_mode"] == {"default": False}
    assert "codex_fast_mode" not in presets["other"]
    assert presets["default"]["reasoning_effort"]["values"]


async def test_temporary_choices_stay_with_owner_and_do_not_recreate_discarded_chat(gateway):
    owner, intruder = gateway.connection(), gateway.connection()
    await gateway.channel._dispatch_envelope(owner, "test-client", {"type": "new_temporary_chat"})
    chat_id = next(event["chat_id"] for event in gateway.events(owner) if event["event"] == "attached")
    options = ModelOptions("low", False)
    denied = await gateway.send(connection=intruder, chat_id=chat_id, model_options=options.to_dict())
    assert gateway.events(denied)[-1]["detail"] == "temporary_chat_unavailable"
    assert gateway.bus.inbound_size == 0
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    await gateway.run(loop, connection=owner, chat_id=chat_id, model_options=options.to_dict())
    assert provider.calls == [("low", options)]
    transient = await gateway.sessions.state.read(f"websocket:{chat_id}")
    assert transient.policy.persist is False
    assert await gateway.sessions.state.list_sessions() == []
    late = await gateway.incoming(connection=owner, chat_id=chat_id, model_options={})
    await gateway.channel._dispatch_envelope(owner, "test-client", {"type": "discard_temporary_chat", "chat_id": chat_id})
    with pytest.raises(RuntimeError, match="required session is not active"):
        await loop._process_message(late)
    assert await gateway.sessions.state.read(f"websocket:{chat_id}") is None
    assert await gateway.sessions.state.list_sessions() == []
