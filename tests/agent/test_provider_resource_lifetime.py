"""Public executions release real HTTP clients without sacrificing connection reuse."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk

from nanobot.agent.loop import AgentLoop
from nanobot.agent.model_presets import load_model_preset_catalog
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.nanobot import STREAM_EVENT_TEXT_DELTA, Nanobot
from nanobot.providers.factory import load_provider_snapshot, provider_signature
from nanobot.providers.openai_compat_provider import OpenAICompatProvider


@dataclass
class Gate:
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class HTTPFixture:
    config: Config
    config_path: Path
    clients: list[AsyncOpenAI] = field(default_factory=list)
    closed: list[asyncio.Event] = field(default_factory=list)
    peers: list[tuple[str, int]] = field(default_factory=list)
    streams: list[AsyncStream[ChatCompletionChunk]] = field(default_factory=list)
    gates: dict[str, Gate] = field(default_factory=dict)

    def save(self):
        self.config_path.write_text(self.config.model_dump_json(), encoding="utf-8")

    def bot(self, *, reload=False):
        if not reload:
            return Nanobot.from_config(self.config_path)
        loop = AgentLoop.from_config(
            self.config,
            tool_registry=ToolRegistry(),
            provider_signature=provider_signature(self.config),
            provider_snapshot_loader=lambda **kwargs: load_provider_snapshot(self.config_path, **kwargs),
            preset_catalog_loader=lambda: load_model_preset_catalog(self.config_path),
        )
        return Nanobot(loop, config=self.config)


@pytest_asyncio.fixture
async def http_provider(tmp_path, monkeypatch):
    # Tool descriptions/skill aliases also read instance-wide CLI Apps metadata.
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    # Use real SDK/httpx clients, but never inherit an external proxy or real data.
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    state = HTTPFixture(Config(), tmp_path / "config.json")

    async def chat(request):
        body = await request.json()
        model = body["model"]
        content = str(body["messages"][-1]["content"])
        state.peers.append(request.transport.get_extra_info("peername"))
        routed_model = model if model.startswith("tenant/") else f"tenant/{model}"
        reply = f"{request.path}:{routed_model}"
        if not body.get("stream"):
            return web.json_response({
                "id": "fixture", "model": model, "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
            })
        def chunk(delta, finish=None):
            payload = {"id": "fixture", "model": model, "object": "chat.completion.chunk",
                       "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return f"data: {json.dumps(payload)}\n\n".encode()

        first = chunk({"role": "assistant", "content": reply})
        last = chunk({}, "stop") + b"data: [DONE]\n\n"
        gate = state.gates.get(routed_model) if "hold" in content else None
        if gate is None:
            return web.Response(body=first + last, content_type="text/event-stream")
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        try:
            await response.write(first)
            gate.started.set()
            await gate.release.wait()
            await response.write(last)
        except ConnectionResetError:
            pass  # The cancellation/close scenarios deliberately disconnect.
        return response

    app = web.Application()
    app.router.add_post("/{version}/chat/completions", chat)
    runner = web.AppRunner(app)
    await runner.setup()
    server = await asyncio.get_running_loop().create_server(runner.server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    state.config = Config.model_validate({
        "agents": {"defaults": {"workspace": str(tmp_path / "workspace"), "provider": "tenant",
                                 "model": "tenant/base", "maxConcurrentSubagents": 1}},
        # A loopback proxy serves the fixture directly; nothing is forwarded. This
        # exercises normal keep-alive pools rather than the intentionally disabled
        # keep-alive policy for direct local-model endpoints.
        "network": {"proxy": f"http://127.0.0.1:{port}"},
        "providers": {"tenant": {"apiKey": "synthetic-key-a", "apiBase": f"http://127.0.0.1:{port}/v1", "useProxy": True}},
    })
    state.save()
    build = OpenAICompatProvider._build_client

    def observe_client(provider):
        build(provider)
        client = provider._client
        closed = asyncio.Event()
        close = client.close

        async def observed_close():
            await close()
            closed.set()

        create = client.chat.completions.create

        async def observed_create(**kwargs):
            response = await create(**kwargs)
            if kwargs.get("stream"):
                state.streams.append(response)
            return response

        monkeypatch.setattr(client.chat.completions, "create", observed_create)
        monkeypatch.setattr(client, "close", observed_close)
        state.clients.append(client)
        state.closed.append(closed)

    monkeypatch.setattr(OpenAICompatProvider, "_build_client", observe_client)
    try:
        yield state
    finally:
        for gate in state.gates.values():
            gate.release.set()
        for client in state.clients:
            if not client.is_closed():
                await client.close()
        server.close()
        await server.wait_closed()
        await runner.cleanup()


@pytest.mark.asyncio
async def test_gateway_admission_reuses_unchanged_connection_and_drains_replaced_execution(http_provider):
    state = http_provider
    bot = state.bot(reload=True)
    gate = state.gates["tenant/base"] = Gate()
    pending = None
    try:
        for _ in range(3):
            assert (await bot.run("normal")).content == "/v1/chat/completions:tenant/base"
        assert len(state.clients) == 1
        assert len(set(state.peers)) == 1  # Actual TCP keep-alive, not just provider identity.
        bot._loop.refresh_runtime_config()
        await bot.run("unchanged reload")
        assert len(state.clients) == 1
        assert len(set(state.peers)) == 1

        pending = asyncio.create_task(bot.run("hold old", session_key="sdk:old"))
        await asyncio.wait_for(gate.started.wait(), 5)
        connection = state.config.get_provider(preset=state.config.resolve_preset())
        connection.api_key = "synthetic-key-b"
        connection.api_base = connection.api_base.replace("/v1", "/v2")
        state.save()
        bot._loop.refresh_runtime_config()
        assert (await bot.run("new", session_key="sdk:new")).content == "/v2/chat/completions:tenant/base"
        assert len(state.clients) == 2
        assert not state.clients[0].is_closed()
        gate.release.set()
        assert (await pending).content == "/v1/chat/completions:tenant/base"
        await asyncio.wait_for(state.closed[0].wait(), 5)
        assert not state.clients[1].is_closed()
    finally:
        gate.release.set()
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
        await bot.aclose()
    assert all(client.is_closed() for client in state.clients)


@pytest.mark.asyncio
async def test_sdk_override_cache_is_bounded_by_recent_and_inflight_clients(http_provider):
    state = http_provider
    bot = state.bot()
    gate = state.gates["tenant/first"] = Gate()
    stream = None
    try:
        for _ in range(4):
            await bot.run("reuse", model="tenant/first")
        assert len(state.clients) == 1
        assert len(set(state.peers)) == 1
        stream = await bot.run_streamed("hold stream", model="tenant/first", session_key="sdk:stream")
        await asyncio.wait_for(gate.started.wait(), 5)
        for number in range(12):
            result = await bot.run("replace", model=f"tenant/model-{number}", session_key="sdk:other")
            assert result.content.endswith(f":tenant/model-{number}")
            assert not state.clients[0].is_closed()
            assert sum(not client.is_closed() for client in state.clients) == 2
        gate.release.set()
        assert (await stream.wait()).content.endswith(":tenant/first")
        await asyncio.wait_for(state.closed[0].wait(), 5)
        assert sum(not client.is_closed() for client in state.clients) == 1
    finally:
        gate.release.set()
        if stream is not None:
            await stream.aclose()
        await bot.aclose()
    assert all(client.is_closed() for client in state.clients)


@pytest.mark.asyncio
async def test_sdk_cancellation_and_close_drain_active_and_not_started_runs(http_provider):
    state = http_provider
    bot = state.bot()
    old_gate = state.gates["tenant/old"] = Gate()
    active_gate = state.gates["tenant/active"] = Gate()
    active = None
    try:
        stream = await bot.run_streamed("hold", model="tenant/old")
        await asyncio.wait_for(old_gate.started.wait(), 5)
        async with aclosing(stream.stream_events()) as events:
            async for event in events:
                if event.type == STREAM_EVENT_TEXT_DELTA:
                    break  # Closing the public iterator cancels after the response is open.
        assert state.streams[-1].response.is_closed  # Request cleanup while its provider stays cached.
        assert not state.clients[0].is_closed()
        await bot.run("replacement", model="tenant/new", session_key="sdk:new")
        await asyncio.wait_for(state.closed[0].wait(), 5)
        active = asyncio.create_task(bot.run("hold", model="tenant/active", session_key="sdk:active"))
        await asyncio.wait_for(active_gate.started.wait(), 5)
        # Close before this newly returned task has had an event-loop turn.
        queued = await bot.run_streamed("not started", model="tenant/queued", session_key="sdk:queued")
        await asyncio.wait_for(bot.aclose(), 5)
        assert active.cancelled()
        assert queued.done
        assert all(client.is_closed() for client in state.clients)
        with pytest.raises(RuntimeError, match="closed"):
            await bot.run("after close", model="tenant/after-close")
    finally:
        old_gate.release.set()
        active_gate.release.set()
        await bot.aclose()
        if active is not None:
            await asyncio.gather(active, return_exceptions=True)


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.asyncio
async def test_injected_provider_remains_external_unless_ownership_is_transferred(http_provider, tmp_path, owned):
    state = http_provider
    connection = state.config.get_provider(preset=state.config.resolve_preset())
    provider = OpenAICompatProvider(api_key="synthetic-key", api_base=connection.api_base, default_model="tenant/base")
    loop = AgentLoop(MessageBus(), provider, tmp_path / "injected", tool_registry=ToolRegistry(), owns_provider=owned)
    bot = Nanobot(loop)
    try:
        assert (await bot.run("borrowed")).content.endswith(":tenant/base")
        client = state.clients[-1]
        await bot.aclose()
        assert client.is_closed() is owned
        if not owned:
            response = await provider.chat(messages=[{"role": "user", "content": "external still works"}])
            assert response.content.endswith(":tenant/base")
    finally:
        await bot.aclose()
        await provider.aclose()
    assert client.is_closed()


@pytest.mark.asyncio
async def test_child_queue_keeps_old_provider_until_running_and_queued_children_settle(http_provider):
    state = http_provider
    bot = state.bot(reload=True)
    gate = state.gates["tenant/base"] = Gate()
    manager = bot._loop.subagents
    owner = "sdk:parent"
    try:
        runtime = bot._loop.llm_runtime()
        await manager.spawn("hold child", label="running", session_key=owner, runtime=runtime)
        await asyncio.wait_for(gate.started.wait(), 5)
        await manager.spawn("queued child", label="queued", session_key=owner, runtime=runtime)
        statuses = await manager.read_statuses_for_session(owner)
        ids = {status.label: task_id for task_id, status in statuses.items()}
        state.config.get_provider(preset=state.config.resolve_preset()).api_key = "synthetic-new-key"
        state.save()
        bot._loop.refresh_runtime_config()
        await manager.cancel(ids["queued"], owner)
        assert not state.clients[0].is_closed()
        await manager.cancel(ids["running"], owner)
        await asyncio.wait_for(state.closed[0].wait(), 5)
    finally:
        gate.release.set()
        await bot.aclose()
    assert all(client.is_closed() for client in state.clients)


@pytest.mark.asyncio
async def test_preset_reload_reuses_unchanged_and_releases_changed_or_removed_entries(http_provider):
    state = http_provider
    state.config.model_presets["fast"] = ModelPresetConfig(model="tenant/fast", provider="tenant")
    state.save()
    bot = state.bot(reload=True)
    try:
        await bot.run("preset", model_preset="fast")
        bot._loop.refresh_runtime_config()
        await bot.run("unchanged preset", model_preset="fast")
        assert len(state.clients) == 1
        connection = state.config.get_provider(preset=state.config.resolve_preset())
        connection.api_base = connection.api_base.replace("/v1", "/v2")
        state.save()
        bot._loop.refresh_runtime_config()
        await asyncio.wait_for(state.closed[0].wait(), 5)
        assert (await bot.run("changed preset", model_preset="fast")).content == "/v2/chat/completions:tenant/fast"
        del state.config.model_presets["fast"]
        state.save()
        bot._loop.invalidate_runtime_config()
        assert "fast" not in bot._loop.model_presets
        await asyncio.wait_for(state.closed[1].wait(), 5)
        assert all(client.is_closed() for client in state.clients)
    finally:
        await bot.aclose()


@pytest.mark.asyncio
async def test_sdk_close_retains_unconsumed_events_of_a_completed_stream(http_provider):
    from nanobot.nanobot import STREAM_EVENT_RUN_COMPLETED, STREAM_EVENT_RUN_STARTED

    state = http_provider
    bot = state.bot()
    try:
        run = await bot.run_streamed("normal", session_key="sdk:completed")
        async with asyncio.timeout(5):
            while not run.done:
                await asyncio.sleep(0)
        # Closing the owner here may precede its task's registry-removal callback.
        # A completed stream is no longer work to cancel, but still owns its data.
        await bot.aclose()
        events = [event async for event in run.stream_events()]
        assert events[0].type == STREAM_EVENT_RUN_STARTED
        assert events[-1].type == STREAM_EVENT_RUN_COMPLETED
        assert any(event.type == STREAM_EVENT_TEXT_DELTA for event in events)
        assert (await run.wait()).content == "/v1/chat/completions:tenant/base"
        assert all(client.is_closed() for client in state.clients)
    finally:
        await bot.aclose()
