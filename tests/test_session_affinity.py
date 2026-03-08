from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider


def _fake_litellm_response(content: str = "ok"):
    message = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.asyncio
async def test_litellm_vllm_injects_stable_session_affinity_header():
    provider = LiteLLMProvider(
        api_key="dummy",
        api_base="http://localhost:8000/v1",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        provider_name="vllm",
    )
    messages = [{"role": "user", "content": "hello"}]
    fake_resp = _fake_litellm_response()

    with patch("nanobot.providers.litellm_provider.acompletion", new=AsyncMock(return_value=fake_resp)) as mock_complete:
        await provider.chat(messages, session_id="cli:room-a")
        await provider.chat(messages, session_id="cli:room-a")
        await provider.chat(messages, session_id="cli:room-b")

    h1 = mock_complete.call_args_list[0].kwargs["extra_headers"]["x-session-affinity"]
    h2 = mock_complete.call_args_list[1].kwargs["extra_headers"]["x-session-affinity"]
    h3 = mock_complete.call_args_list[2].kwargs["extra_headers"]["x-session-affinity"]

    assert h1 == h2
    assert h1 != h3


@pytest.mark.asyncio
async def test_litellm_vllm_merges_user_headers_with_session_affinity():
    provider = LiteLLMProvider(
        api_key="dummy",
        api_base="http://localhost:8000/v1",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        provider_name="vllm",
        extra_headers={"X-App-Code": "abc123"},
    )
    messages = [{"role": "user", "content": "hello"}]
    fake_resp = _fake_litellm_response()

    with patch("nanobot.providers.litellm_provider.acompletion", new=AsyncMock(return_value=fake_resp)) as mock_complete:
        await provider.chat(messages, session_id="cli:room-a")

    headers = mock_complete.call_args.kwargs["extra_headers"]
    assert headers["X-App-Code"] == "abc123"
    assert "x-session-affinity" in headers


@pytest.mark.asyncio
async def test_agent_loop_passes_session_key_to_provider(tmp_path):
    provider = Mock()
    provider.get_default_model.return_value = "test-model"
    provider.chat = AsyncMock(return_value=LLMResponse(content="ok"))

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        memory_window=10,
    )

    result = await loop.process_direct("hello", session_key="cli:room-a")

    assert result == "ok"
    assert provider.chat.call_args.kwargs["session_id"] == "cli:room-a"
