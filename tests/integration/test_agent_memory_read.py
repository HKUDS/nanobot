"""IT-02: Stored memory appears in the LLM's system prompt.

Verifies that previously stored events are retrieved by ContextBuilder
and injected into the messages sent to the real LLM. The LLM's response
should reflect knowledge of the stored facts.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

import pytest

from nanobot.agent.loop import AgentLoop
from tests.integration.conftest import make_inbound

pytestmark = pytest.mark.integration


class TestMemoryContextInjection:
    async def test_stored_fact_influences_response(self, agent: AgentLoop) -> None:
        """When memory contains a fact, the LLM's response should reflect it."""
        agent.memory.ingester.append_events(
            [
                {
                    "type": "fact",
                    "summary": "User works at Globex Corporation as a senior engineer.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                }
            ]
        )
        msg = make_inbound("Where do I work?")
        result = await agent._process_message(msg)
        assert result is not None
        assert "globex" in result.content.lower(), (
            f"Expected 'globex' in response, got: {result.content}"
        )

    async def test_stored_preference_influences_response(self, agent: AgentLoop) -> None:
        """Stored preference should be reflected when asked about it."""
        agent.memory.ingester.append_events(
            [
                {
                    "type": "preference",
                    "summary": "User strongly prefers dark mode in all editors and IDEs.",
                    "timestamp": "2026-03-01T12:00:00+00:00",
                    "source": "test",
                }
            ]
        )
        msg = make_inbound("What are my editor preferences?")
        result = await agent._process_message(msg)
        assert result is not None
        assert "dark" in result.content.lower(), (
            f"Expected 'dark' in response, got: {result.content}"
        )

    async def test_empty_memory_no_crash(self, agent: AgentLoop) -> None:
        """Agent with empty memory should still produce a response."""
        msg = make_inbound("What do you know about me?")
        result = await agent._process_message(msg)
        assert result is not None
        assert len(result.content) > 0
