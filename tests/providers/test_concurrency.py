import asyncio
import os

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse


class MockProvider(LLMProvider):
    async def chat(self, messages, **kwargs):
        # Simulate some work
        await asyncio.sleep(0.1)
        return LLMResponse(content="ok")

    def get_default_model(self):
        return "mock"

@pytest.mark.asyncio
async def test_llm_provider_concurrency_gate():
    # Set MAX_CONCURRENT_REQUESTS to 1 for testing
    from unittest.mock import patch
    with patch.dict(os.environ, {"NANOBOT_MAX_CONCURRENT_REQUESTS": "1"}):
        provider = MockProvider()

        start_time = asyncio.get_event_loop().time()

        # Run 3 requests concurrently
        responses = await asyncio.gather(
            provider.chat_with_retry(messages=[{"role": "user", "content": "1"}]),
            provider.chat_with_retry(messages=[{"role": "user", "content": "2"}]),
            provider.chat_with_retry(messages=[{"role": "user", "content": "3"}]),
        )

        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time

        # With gate=1 and each taking 0.1s, total should be at least 0.3s
        assert duration >= 0.3
        assert all(r.content == "ok" for r in responses)

@pytest.mark.asyncio
async def test_llm_provider_no_gate():
    # Set MAX_CONCURRENT_REQUESTS to 0 (unlimited)
    from unittest.mock import patch
    with patch.dict(os.environ, {"NANOBOT_MAX_CONCURRENT_REQUESTS": "0"}):
        provider = MockProvider()

        start_time = asyncio.get_event_loop().time()

        # Run 3 requests concurrently
        responses = await asyncio.gather(
            provider.chat_with_retry(messages=[{"role": "user", "content": "1"}]),
            provider.chat_with_retry(messages=[{"role": "user", "content": "2"}]),
            provider.chat_with_retry(messages=[{"role": "user", "content": "3"}]),
        )

        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time

        # With gate=0, they should run in parallel, total ~0.1s
        assert duration < 0.2
        assert all(r.content == "ok" for r in responses)
