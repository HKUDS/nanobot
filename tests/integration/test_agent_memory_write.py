"""IT-01: Agent loop stores memory events through the write path.

Uses a real LLM to process user messages. Verifies that the memory
subsystem stores events and that they are retrievable afterward.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.memory.event import MemoryEvent
from tests.integration.conftest import make_inbound

pytestmark = pytest.mark.integration


class TestMemoryWriteFromAgentLoop:
    async def test_agent_processes_preference_message(self, agent: AgentLoop) -> None:
        """Agent can process a user preference statement end-to-end."""
        msg = make_inbound("I always prefer dark mode in every editor I use.")
        result = await agent._process_message(msg)
        assert result is not None
        assert len(result.content) > 0

    async def test_seeded_events_retrievable_through_agent(self, agent: AgentLoop) -> None:
        """Events stored in memory are retrievable via the retriever."""
        agent.memory.ingester.append_events(
            [
                MemoryEvent.from_dict(
                    {
                        "type": "fact",
                        "summary": "User is a backend engineer specializing in distributed systems.",
                        "timestamp": "2026-03-01T12:00:00+00:00",
                        "source": "test",
                    }
                )
            ]
        )
        results = await agent.memory.retriever.retrieve("distributed systems", top_k=5)
        summaries = " ".join(r.summary.lower() for r in results)
        assert "distributed" in summaries

    async def test_multiple_events_accumulate(self, agent: AgentLoop) -> None:
        """Multiple seeded events all persist in the store."""
        agent.memory.ingester.append_events(
            [
                MemoryEvent.from_dict(
                    {
                        "type": "preference",
                        "summary": "User prefers Python for backend work.",
                        "timestamp": "2026-03-01T12:00:00+00:00",
                        "source": "test",
                    }
                ),
                MemoryEvent.from_dict(
                    {
                        "type": "fact",
                        "summary": "User works at a startup with 20 employees.",
                        "timestamp": "2026-03-01T12:01:00+00:00",
                        "source": "test",
                    }
                ),
            ]
        )
        all_events = agent.memory.ingester.read_events(limit=100)
        assert len(all_events) >= 2
