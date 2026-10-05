"""Dream triggers must serialize the complete shared-memory update."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.cli import gateway_runtime
from nanobot.command import CommandContext
from nanobot.command.builtin import cmd_dream
from nanobot.config.schema import Config
from nanobot.cron.types import CronJob


@pytest.fixture
def dream_loop(tmp_path):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model="test-model", context_window_tokens=128_000,
    )


async def _start_manual(loop):
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="manual", content="/dream")
    ctx = CommandContext(msg=msg, session=None, key=msg.session_key, raw="/dream", loop=loop)
    before = asyncio.all_tasks()
    await cmd_dream(ctx)
    # The command returns immediately; retain its background task for cleanup.
    task, = asyncio.all_tasks() - before
    return task


def _cron_callback(loop, tmp_path, monkeypatch):
    """Capture the real gateway callback before network services start."""
    config = Config()
    config.agents.defaults.workspace = str(tmp_path)
    cron = SimpleNamespace(on_job=None)
    snapshot = SimpleNamespace(
        provider=loop.provider, model=loop.model,
        context_window_tokens=128_000, signature=(),
    )
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", lambda _: snapshot)
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda _: cron)
    monkeypatch.setattr(gateway_runtime.AgentLoop, "from_config", lambda *_args, **_kwargs: loop)
    monkeypatch.setattr(gateway_runtime.MCPProvider, "from_config", lambda *_: AsyncMock())
    monkeypatch.setattr(gateway_runtime, "_prepare_webui_bundle_for_gateway", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(gateway_runtime, "sync_workspace_templates", lambda _: None)

    class GatewayAssembledError(Exception):
        pass

    def stop_before_channels(*_args, **_kwargs):
        raise GatewayAssembledError

    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", stop_before_channels)
    with pytest.raises(GatewayAssembledError):
        gateway_runtime._run_gateway(config, health_server_enabled=False)
    return cron.on_job


@pytest.mark.asyncio
@pytest.mark.parametrize("second_trigger", ["manual", "cron"])
async def test_dream_waiter_uses_fresh_history_and_preserves_corrections(
    dream_loop, tmp_path, monkeypatch, second_trigger,
):
    loop = dream_loop
    store = loop.context.memory
    store.write_memory("Initial memory.\n")
    store.append_history("[durable] Service endpoint is OLD_ENDPOINT.")
    started = asyncio.Event()
    release = asyncio.Event()
    prompts = []

    async def process_direct(prompt, **kwargs):
        prompts.append(prompt)
        tools = kwargs["tools"]
        await tools.execute("read_file", {"path": "memory/MEMORY.md"})
        if len(prompts) == 1:
            started.set()
            await release.wait()
        endpoint = "CURRENT_ENDPOINT" if "CURRENT_ENDPOINT" in prompt else "OLD_ENDPOINT"
        result = await tools.execute("write_file", {
            "path": "memory/MEMORY.md", "content": f"Service endpoint: {endpoint}\n",
        })
        assert "Successfully wrote" in result
        return OutboundMessage(
            channel="cli", chat_id="direct", content="Memory updated.",
            metadata={"_stop_reason": "completed"},
        )

    monkeypatch.setattr(loop, "process_direct", process_direct)
    callback = _cron_callback(loop, tmp_path, monkeypatch) if second_trigger == "cron" else None
    tasks = []
    try:
        tasks.append(await _start_manual(loop))
        await asyncio.wait_for(started.wait(), timeout=5)
        store.append_history("[correction] Service endpoint is now CURRENT_ENDPOINT.")
        tasks.append(
            await _start_manual(loop) if callback is None
            else asyncio.create_task(callback(CronJob(id="dream", name="dream")))
        )
        # Each trigger runs to its first blocking await: either the shared lock,
        # or (before the fix) a complete second run with the stale first batch.
        await asyncio.sleep(0)
        assert len(prompts) == 1
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        assert len(prompts) == 2
        assert "OLD_ENDPOINT" not in prompts[1]
        assert "CURRENT_ENDPOINT" in prompts[1]
        assert store.get_last_dream_cursor() == 2
        assert store.read_memory() == "Service endpoint: CURRENT_ENDPOINT\n"
        assert store.build_dream_prompt() is None
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await loop.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancelled"])
async def test_dream_retries_pending_history_after_interrupted_run(
    dream_loop, monkeypatch, failure,
):
    loop = dream_loop
    store = loop.context.memory
    store.append_history("[permanent] Prefer concise answers.")
    started = asyncio.Event()
    attempts = 0

    async def process_direct(prompt, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure == "error":
                raise RuntimeError("provider unavailable")
            started.set()
            await asyncio.Event().wait()
        assert "Prefer concise answers" in prompt
        return OutboundMessage(
            channel="cli", chat_id="direct", content="Done.",
            metadata={"_stop_reason": "completed"},
        )

    monkeypatch.setattr(loop, "process_direct", process_direct)
    tasks = []
    try:
        first = await _start_manual(loop)
        tasks.append(first)
        if failure == "cancelled":
            await asyncio.wait_for(started.wait(), timeout=5)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            await first
        assert store.get_last_dream_cursor() == 0
        second = await _start_manual(loop)
        tasks.append(second)
        await asyncio.wait_for(second, timeout=5)
        assert attempts == 2
        assert store.get_last_dream_cursor() == 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await loop.aclose()
