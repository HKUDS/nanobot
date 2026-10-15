"""Dream triggers must serialize the complete shared-memory update."""

import asyncio
from unittest.mock import MagicMock

import pytest

from nanobot.agent.dream import run_dream
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus


@pytest.fixture
def dream_loop(tmp_path):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    return AgentLoop(
        bus=MessageBus(), provider=provider, workspace=tmp_path,
        model="test-model", context_window_tokens=128_000,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("second_kind", ["manual", "scheduled"])
async def test_dream_waiter_uses_fresh_history_and_preserves_corrections(
    dream_loop, monkeypatch, second_kind,
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
    tasks = []
    try:
        tasks.append(asyncio.create_task(run_dream(loop, kind="manual")))
        await asyncio.wait_for(started.wait(), timeout=5)
        store.append_history("[correction] Service endpoint is now CURRENT_ENDPOINT.")
        tasks.append(asyncio.create_task(run_dream(loop, kind=second_kind)))
        # Let the second run reach the shared lock while the first is paused.
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
        first = asyncio.create_task(run_dream(loop, kind="manual"))
        tasks.append(first)
        if failure == "cancelled":
            await asyncio.wait_for(started.wait(), timeout=5)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            result = await asyncio.wait_for(first, timeout=5)
            assert result.status == "failed"
            assert str(result.error) == "provider unavailable"
        assert store.get_last_dream_cursor() == 0
        second = asyncio.create_task(run_dream(loop, kind="manual"))
        tasks.append(second)
        result = await asyncio.wait_for(second, timeout=5)
        assert result.status == "completed"
        assert attempts == 2
        assert store.get_last_dream_cursor() == 1
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await loop.aclose()
