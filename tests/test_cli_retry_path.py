"""Integration tests for the LLM error/retry path (4c).

Closes the layer-mocking gap: CLI tests mocked process_direct entirely,
so _cli_progress was never called, and the retry StatusEvent path was
never exercised. These tests use a real AgentLoop + ScriptedProvider.
"""

from __future__ import annotations

from nanobot.agent.callbacks import ProgressEvent, StatusEvent
from nanobot.providers.base import LLMResponse
from tests.helpers import ScriptedProvider, error_response, make_agent_loop


async def test_llm_error_emits_retrying_status_event() -> None:
    """A single LLM error emits exactly one StatusEvent(retrying) then succeeds."""
    provider = ScriptedProvider(
        [
            error_response(),
            LLMResponse(content="Hello, I can help!"),
        ]
    )
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = make_agent_loop(provider)
    result = await loop.process_direct("hello", on_progress=tracking)

    retry_signals = [
        e for e in received if isinstance(e, StatusEvent) and e.status_code == "retrying"
    ]
    assert len(retry_signals) == 1
    assert "Hello" in result


async def test_llm_error_three_times_returns_fallback_message() -> None:
    """Three consecutive errors return the fallback message without crashing."""
    provider = ScriptedProvider([error_response(), error_response(), error_response()])
    received: list[ProgressEvent] = []

    async def tracking(event: ProgressEvent) -> None:
        received.append(event)

    loop = make_agent_loop(provider)
    result = await loop.process_direct("hello", on_progress=tracking)

    assert "trouble reaching the language model" in result
    retry_signals = [
        e for e in received if isinstance(e, StatusEvent) and e.status_code == "retrying"
    ]
    # Signals on attempt 1 and 2; attempt 3 breaks the loop
    assert len(retry_signals) == 2
