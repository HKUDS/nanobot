"""Shared fixtures for integration tests.

These fixtures wire real subsystems together with a real LLM provider.
Tests fail when no API key is available.

Pattern follows tests/test_memory_roundtrip.py.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentConfig
from nanobot.memory.store import MemoryStore
from nanobot.providers.litellm_provider import LiteLLMProvider

_has_api_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY"))

_FAIL_REASON = "No LLM API key (OPENAI_API_KEY / LITELLM_API_KEY)"

MODEL = "gpt-4o-mini"

SAMPLE_EVENTS: list[dict[str, Any]] = [
    {
        "type": "preference",
        "summary": "User prefers dark mode in all editors.",
        "timestamp": "2026-03-01T12:00:00+00:00",
        "source": "test",
    },
    {
        "type": "fact",
        "summary": "User's primary programming language is Python.",
        "timestamp": "2026-03-01T12:01:00+00:00",
        "source": "test",
    },
    {
        "type": "task",
        "summary": "Migrate database to PostgreSQL by end of quarter.",
        "timestamp": "2026-03-01T12:02:00+00:00",
        "source": "test",
        "metadata": {"status": "active"},
    },
    {
        "type": "decision",
        "summary": "Chose FastAPI over Flask for the new API project.",
        "timestamp": "2026-03-01T12:03:00+00:00",
        "source": "test",
    },
    {
        "type": "constraint",
        "summary": "Budget limit is $5000 per month for cloud infrastructure.",
        "timestamp": "2026-03-01T12:04:00+00:00",
        "source": "test",
    },
]


@pytest.fixture()
def provider() -> LiteLLMProvider:
    """Real LLM provider using gpt-4o-mini. Fails test if no API key."""
    if not _has_api_key:
        pytest.fail(_FAIL_REASON)
    return LiteLLMProvider(default_model=MODEL)


@pytest.fixture()
def store(tmp_path: Path) -> MemoryStore:
    """Real MemoryStore with HashEmbedder for deterministic vector search."""
    return MemoryStore(tmp_path, embedding_provider="hash")


@pytest.fixture()
def config(tmp_path: Path) -> AgentConfig:
    """Minimal AgentConfig with memory enabled."""
    return AgentConfig(
        workspace=str(tmp_path),
        model=MODEL,
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
        memory_enabled=True,
        graph_enabled=False,
        reranker_mode="disabled",
    )


@pytest.fixture()
def agent(tmp_path: Path, provider: LiteLLMProvider, config: AgentConfig) -> AgentLoop:
    """Fully wired agent with real LLM, real memory, real tools."""
    bus = MessageBus()
    return build_agent(bus=bus, provider=provider, config=config)


def make_inbound(
    text: str,
    *,
    channel: str = "cli",
    chat_id: str = "integration-test",
    sender_id: str = "user-1",
) -> InboundMessage:
    """Create an InboundMessage for test input."""
    return InboundMessage(
        channel=channel,
        chat_id=chat_id,
        sender_id=sender_id,
        content=text,
    )
