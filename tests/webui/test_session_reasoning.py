"""Reasoning controls exercise the authenticated gateway without starting a listener."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode

import httpx
import pytest
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.loop import AgentLoop
from nanobot.agent.model_presets import configured_model_presets
from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.factory import ProviderSnapshot, provider_signature
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.providers.oauth_catalog_cache import OAuthModelCatalogSnapshot
from nanobot.session.manager import SessionManager
from nanobot.session.model_selection import (
    SESSION_REASONING_EFFORT_METADATA_KEY,
    reasoning_effort_scope,
)
from nanobot.webui import session_reasoning, settings_models
from nanobot.webui.gateway_services import GatewayServices, build_gateway_services


@dataclass
class Gateway:
    path: Path
    sessions: SessionManager
    bus: MessageBus
    services: GatewayServices
    channel: WebSocketChannel
    headers: Headers
    request_id: int = 0

    @property
    def config(self):
        return load_config(self.path)

    async def get(self, *, preset="default", key=None, authenticated=True):
        query = {"model_preset": preset}
        if key is not None:
            query["session_key"] = key
        return await self.services.http.dispatch(
            SimpleNamespace(remote_address=("127.0.0.1", 12345)),
            Request("/api/webui/reasoning-effort?" + urlencode(query),
                    self.headers if authenticated else Headers()),
        )

    async def mutate(self, view, *, key="websocket:chat", value="low", audience="webui"):
        self.request_id += 1
        connection = MagicMock()
        connection.send = AsyncMock()
        connection.request = Request("/", Headers())
        if audience is not None:
            token = self.services.tokens.issue_token(60, audience=audience)
            assert self.channel._authorize_websocket_handshake(connection, {"token": [token]}) is None
        await self.channel._dispatch_envelope(connection, "test-client", {
            "type": "webui_request", "request_id": f"effort-{self.request_id}",
            "action": "session.reasoning-effort",
            "payload": {"session_key": key, "preset": view["preset"], "scope": view["scope"], "value": value},
        })
        if self.channel._webui_request_tasks:
            await asyncio.gather(*tuple(self.channel._webui_request_tasks.values()))
        return json.loads(connection.send.await_args.args[0])

    def loop(self, provider):
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
            bus=self.bus, provider=provider, workspace=config.workspace_path, session_manager=self.sessions,
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
    monkeypatch.setattr(session_reasoning.httpx, "get", lambda url, **kwargs:
                        httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url)))
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
    yield Gateway(path, sessions, bus, services, channel, Headers({"Authorization": f"Bearer {token}"}))
    await channel._commands.close()
    await sessions.state.aclose()


async def test_public_get_authentication_capability_and_read_only_draft(gateway):
    before = gateway.path.read_bytes()
    denied = await gateway.get(authenticated=False)
    assert denied.status_code == 401
    response = await gateway.get()
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    view = json.loads(response.body)
    assert view == {
        "preset": "default", "scope": reasoning_effort_scope(provider_signature(gateway.config)),
        "options": ["none", "low", "high", "max"], "value": None, "preset_value": "high",
    }
    assert gateway.path.read_bytes() == before
    assert await gateway.sessions.state.list_sessions() == []
    terminal = await gateway.services.http.dispatch(
        SimpleNamespace(remote_address=("127.0.0.1", 12345)),
        Request("/webui/terminal", Headers({"Authorization": "Bearer test-bootstrap"})),
    )
    contract = json.loads(terminal.body)["webui"]
    assert contract["min_protocol"] == contract["max_protocol"] == 1
    assert "webui.reasoning-effort.v1" in contract["capabilities"]


async def test_websocket_only_mutation_and_private_session_boundary(gateway):
    view = json.loads((await gateway.get()).body)
    http = await gateway.services.http.dispatch(
        SimpleNamespace(remote_address=("127.0.0.1", 12345)),
        Request("/api/webui/reasoning-effort/update", gateway.headers),
    )
    assert http.status_code == 405
    for audience in (None, "client"):
        denied = await gateway.mutate(view, audience=audience)
        assert denied["error"]["status"] == 403
    assert await gateway.sessions.state.list_sessions() == []
    await gateway.sessions.state.update_metadata("sdk:private", {"private": "not exposed"}, create_if_missing=True)
    for key in ("sdk:private", "sdk:missing"):
        assert (await gateway.get(key=key)).status_code == 404
        denied = await gateway.mutate(view, key=key)
        assert denied["error"]["status"] == 404


async def test_persist_before_first_turn_refresh_isolation_and_follow_preset(gateway):
    view = json.loads((await gateway.get(key="websocket:chat")).body)
    before = gateway.path.read_bytes()
    changed = await gateway.mutate(view, value="none")
    assert changed["ok"] is True
    assert changed["result"]["value"] == "none"
    fresh = SessionManager(gateway.config.workspace_path, sessions_root=gateway.path.parent / "sessions")
    try:
        restored = session_reasoning.WebUISessionReasoning(gateway.path, fresh)
        assert (await restored.get("default", "websocket:chat"))["value"] == "none"
        assert (await restored.get("default", "websocket:other"))["value"] is None
        assert await fresh.state.read_header("websocket:other") is None
    finally:
        await fresh.state.aclose()
    bad = await gateway.mutate(view, value="medium")
    assert bad["error"]["status"] == 400
    assert json.loads((await gateway.get(key="websocket:chat")).body)["value"] == "none"
    cleared = await gateway.mutate(view, value=None)
    assert cleared["result"]["value"] is None
    header = await gateway.sessions.state.read_header("websocket:chat")
    assert SESSION_REASONING_EFFORT_METADATA_KEY not in header.metadata
    assert header.messages == []
    assert gateway.path.read_bytes() == before


async def test_draft_selected_preset_applies_after_model_selection_and_switch_clears(gateway):
    loop = gateway.loop(RecordingProvider())
    draft = json.loads((await gateway.get(preset="deep")).body)
    denied = await gateway.mutate(draft)
    assert denied["error"]["status"] == 409
    assert await gateway.sessions.state.read_header("websocket:chat") is None
    await loop.set_session_model_preset("websocket:chat", "deep")
    selected = await gateway.mutate(draft, value="max")
    assert selected["result"]["value"] == "max"
    connection = MagicMock()
    connection.send = AsyncMock()
    token = gateway.services.tokens.issue_token(60, audience="webui")
    assert gateway.channel._authorize_websocket_handshake(connection, {"token": [token]}) is None
    await gateway.channel._dispatch_envelope(connection, "webui-client", {
        "type": "message", "chat_id": "chat", "content": "/model default",
    })
    inbound = await asyncio.wait_for(gateway.bus.consume_inbound(), 3)
    assert inbound.content == "/model default"
    reply = await loop._process_message(inbound)
    assert "Switched model preset to `default`" in reply.content
    assert (await gateway.get(preset="deep", key="websocket:chat")).status_code == 409
    assert (await gateway.mutate(draft, value="high"))["error"]["status"] == 409
    await loop.set_session_model_preset("websocket:chat", "deep")
    refreshed = json.loads((await gateway.get(preset="deep", key="websocket:chat")).body)
    assert refreshed["value"] is None
    assert SESSION_REASONING_EFFORT_METADATA_KEY not in (await gateway.sessions.state.read_header("websocket:chat")).metadata


async def test_stale_config_scope_is_rejected_and_not_applied_to_new_runtime(gateway):
    provider = RecordingProvider()
    loop = gateway.loop(provider)
    view = json.loads((await gateway.get()).body)
    assert (await gateway.mutate(view, value="max"))["ok"]
    captured = await loop.runtime_for_session(await gateway.sessions.state.get("websocket:chat"))
    assert captured.generation.reasoning_effort == "max"
    config = gateway.config
    config.providers.deepseek.extra_headers = {"X-Configured-Header": "new"}
    save_config(config, gateway.path)
    rejected = await gateway.mutate(view, value="low")
    assert rejected["error"]["status"] == 409
    loop.refresh_runtime_config()
    refreshed = await loop.runtime_for_session(await gateway.sessions.state.get("websocket:chat"))
    assert refreshed.generation.reasoning_effort == "high"
    assert captured.generation.reasoning_effort == "max"
    assert json.loads((await gateway.get(key="websocket:chat")).body)["value"] is None


@pytest.mark.parametrize("change", ["model", "delete", "recreate", "config"])
async def test_inflight_mutation_rechecks_session_and_configuration(gateway, monkeypatch, change):
    loop = gateway.loop(RecordingProvider())
    await gateway.sessions.state.get_header("websocket:chat")
    view = json.loads((await gateway.get()).body)
    entered, release = Event(), Event()
    original = session_reasoning.reasoning_effort_options

    def blocked(config, preset):
        entered.set()
        assert release.wait(3)
        return original(config, preset)

    monkeypatch.setattr(session_reasoning, "reasoning_effort_options", blocked)
    mutation = asyncio.create_task(gateway.mutate(view, value="max"))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if change == "model":
            await loop.set_session_model_preset("websocket:chat", "deep")
        elif change == "config":
            config = gateway.config
            config.providers.deepseek.extra_body = {"thinking": {"type": "disabled"}}
            save_config(config, gateway.path)
        else:
            await gateway.sessions.state.delete("websocket:chat")
            if change == "recreate":
                await gateway.sessions.state.get_header("websocket:chat")
    finally:
        release.set()
    rejected = await mutation
    assert rejected["error"]["status"] == 409
    header = await gateway.sessions.state.read_header("websocket:chat")
    assert header is None or SESSION_REASONING_EFFORT_METADATA_KEY not in header.metadata


@pytest.mark.parametrize("provider,model,api_base,body,preset_body", [
    ("deepseek", "unlisted-reasoner", None, None, None),
    ("deepseek", "deepseek-flash", "https://example.invalid/v1", None, None),
    ("deepseek", "deepseek-flash", None, {"reasoning_effort": "high"}, None),
    ("deepseek", "deepseek-flash", None, None, {"thinking": {"type": "disabled"}}),
    ("deepseek", "deepseek-flash", None, {"reasoning": {"effort": "max"}}, None),
    ("anthropic", "claude-sonnet-4-5", None, None, None),
    ("openai", "future-o-reasoner", None, None, None),
])
async def test_session_fallback_matches_preset_recommendations(
    gateway, provider, model, api_base, body, preset_body,
):
    config = gateway.config
    preset = config.model_presets["deep"]
    preset.provider, preset.model, preset.extra_body = provider, model, preset_body
    connection = getattr(config.providers, provider)
    connection.api_key, connection.api_base, connection.extra_body = "test-key", api_base, body
    save_config(config, gateway.path)
    response = await gateway.get(preset="deep")
    assert response.status_code == 200
    settings = await gateway.services.http.dispatch(
        SimpleNamespace(remote_address=("127.0.0.1", 12345)),
        Request("/api/settings", gateway.headers),
    )
    assert settings.status_code == 200
    saved_preset = next(row for row in json.loads(settings.body)["model_presets"] if row["name"] == "deep")
    assert json.loads(response.body)["options"] == [value for value in saved_preset["reasoning_effort_values"] if value]
    assert json.loads(response.body)["value"] is None


@pytest.mark.parametrize("provider,efforts,expected", [
    ("openai_codex", [{"effort": "low"}, {"effort": "ultra"}, {"effort": "none"}], ["low", "ultra", "none"]),
    ("github_copilot", ["low", "xhigh"], ["low", "xhigh"]),
    ("github_copilot", True, []),
])
async def test_oauth_recommendations_match_preset_catalog(gateway, monkeypatch, provider, efforts, expected):
    if provider == "openai_codex":
        from nanobot.providers.openai_codex_provider import _parse_openai_codex_models
        models = _parse_openai_codex_models({"models": [{"slug": "new-model", "supported_reasoning_levels": efforts}]})
    else:
        from nanobot.providers.github_copilot_provider import _parse_github_copilot_models
        models = _parse_github_copilot_models({"data": [{
            "id": "new-model", "model_picker_enabled": True, "supported_endpoints": ["/responses"],
            "capabilities": {"supports": {"reasoning_effort": efforts}},
        }]})
    monkeypatch.setattr(settings_models, "get_oauth_model_catalog", lambda *args, **kwargs:
                        OAuthModelCatalogSnapshot(models=models, source="remote", fetched_at=1))
    config = gateway.config
    config.model_presets["deep"].provider = provider
    config.model_presets["deep"].model = provider.replace("_", "-") + "/new-model"
    save_config(config, gateway.path)
    response = await gateway.get(preset="deep")
    assert response.status_code == 200
    assert json.loads(response.body)["options"] == expected


@pytest.mark.parametrize("provider,base", [
    ("custom", "http://127.0.0.1:19191/v1"),
    ("deepseek", "https://example.invalid/v1"),
    ("openai", None),
])
async def test_explicit_online_levels_work_at_custom_and_standard_endpoints(gateway, monkeypatch, provider, base):
    config = gateway.config
    config.agents.defaults.provider = provider
    config.agents.defaults.model = "sample-reasoner"
    config.agents.defaults.reasoning_effort = None
    getattr(config.providers, provider).api_key = "test-key"
    getattr(config.providers, provider).api_base = base
    save_config(config, gateway.path)
    calls = []

    def models(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{
            "id": "sample-reasoner", "effort": {"supported_levels": ["low", "xhigh"]},
        }]})

    monkeypatch.setattr(session_reasoning.httpx, "get", models)
    view = json.loads((await gateway.get()).body)
    assert view["options"] == ["low", "xhigh"]
    assert view["value"] is view["preset_value"] is None
    changed = await gateway.mutate(view, value="xhigh")
    assert changed["result"]["value"] == "xhigh"
    runtime = await gateway.loop(RecordingProvider()).runtime_for_session(
        await gateway.sessions.state.get("websocket:chat"),
    )
    assert runtime.generation.reasoning_effort == "xhigh"
    assert calls and all(url == (base or "https://api.openai.com/v1") + "/models" for url in calls)
    config.agents.defaults.model = "unknown"
    save_config(config, gateway.path)
    unknown = json.loads((await gateway.get()).body)
    assert unknown["options"] == ["low", "medium", "high"]


@pytest.mark.parametrize("model,declared,expected", [
    ("kimi-k2.5", ["low", "high"], ["low", "high"]),
    ("kimi-k3.1-pro", ["low", "medium", "high", "max"], ["low", "medium", "high", "max"]),
])
async def test_online_recommendations_match_preset_without_separate_adapter_filter(
    gateway, monkeypatch, model, declared, expected,
):
    config = gateway.config
    config.agents.defaults.provider = "custom"
    config.agents.defaults.model = model
    config.providers.custom.api_base = "http://127.0.0.1:19191/v1"
    save_config(config, gateway.path)
    monkeypatch.setattr(session_reasoning.httpx, "get", lambda url, **kwargs:
                        httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{
                            "id": model, "effort": {"supported_levels": declared},
                        }]}))
    view = json.loads((await gateway.get()).body)
    assert view["options"] == expected
    if expected:
        assert (await gateway.mutate(view, value=expected[0]))["result"]["value"] == expected[0]


@pytest.mark.parametrize("model,expected", [("deepseek-flash", ["none"]), ("unlisted-reasoner", [])])
async def test_catalog_empty_levels_and_metadata_match_preset_picker(gateway, monkeypatch, model, expected):
    config = gateway.config
    config.agents.defaults.model = model
    save_config(config, gateway.path)
    monkeypatch.setattr(session_reasoning.httpx, "get", lambda url, **kwargs:
                        httpx.Response(200, request=httpx.Request("GET", url), json={"data": [{
                            "id": model, "effort": {"supported_levels": []},
                        }]}))
    view = json.loads((await gateway.get()).body)
    assert view["options"] == expected
    assert (await gateway.mutate(view, value="high"))["error"]["status"] == 400


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
            return LLMResponse(content="busy", finish_reason="error", error_kind="server_error")
        return LLMResponse(content="done", finish_reason="stop")


async def test_next_execution_uses_snapshot_not_later_session_or_global_changes(gateway):
    provider = RecordingProvider(tool_first=True)
    loop = gateway.loop(provider)
    (gateway.config.workspace_path / "answer.py").write_text("answer = 42", encoding="utf-8")
    view = json.loads((await gateway.get()).body)
    await gateway.mutate(view, value="low")
    provider.entered, provider.release = asyncio.Event(), asyncio.Event()
    running = asyncio.create_task(loop.process_direct("hello", session_key="websocket:chat"))
    try:
        await asyncio.wait_for(provider.entered.wait(), 3)
        assert provider.calls == ["low"]
        await gateway.mutate(view, value="max")
        assert provider.generation.reasoning_effort == "high"
    finally:
        provider.release.set()
    assert (await running).content == "done"
    await loop.process_direct("next", session_key="websocket:chat")
    await loop.process_direct("other", session_key="websocket:other")
    assert provider.calls == ["low", "low", "max", "high"]
    assert provider.generation.reasoning_effort == gateway.config.agents.defaults.reasoning_effort == "high"


async def test_primary_override_does_not_replace_fallback_effort(gateway):
    primary, fallback = RecordingProvider(error=True), RecordingProvider()
    config = gateway.config
    config.agents.defaults.fallback_models = ["deep"]
    save_config(config, gateway.path)
    fallback_preset = config.model_presets["deep"]
    wrapped = FallbackProvider(primary, [fallback_preset], lambda _: fallback)
    loop = gateway.loop(wrapped)
    view = json.loads((await gateway.get()).body)
    await gateway.mutate(view, value="max")
    result = await loop.process_direct("hello", session_key="websocket:chat")
    assert result.content == "done"
    assert primary.calls == ["max"]
    assert fallback.calls == ["low"]
    assert primary.generation.reasoning_effort == "high"
