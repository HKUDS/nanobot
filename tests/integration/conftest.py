"""Shared fixtures for integration tests.

These fixtures wire real subsystems together with a real LLM provider.
API key is resolved from nanobot config (primary) with env var fallback.
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
from nanobot.config.agent import AgentConfig
from nanobot.config.loader import load_config
from nanobot.config.memory import MemoryConfig, RerankerConfig
from nanobot.memory.store import MemoryStore
from nanobot.providers.litellm_provider import LiteLLMProvider

MODEL = "gpt-4o-mini"


def _resolve_api_key() -> str | None:
    """Resolve LLM API key: nanobot config (primary), env var (fallback)."""
    try:
        cfg = load_config()
        key = cfg.get_api_key(MODEL)
        if key:
            return key
    except Exception:  # crash-barrier: config load must not break test collection
        pass
    return os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY") or None


_api_key = _resolve_api_key()

_FAIL_REASON = (
    "No LLM API key found. Configure in ~/.nanobot/config.json "
    "or set OPENAI_API_KEY / LITELLM_API_KEY env var."
)

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
    if not _api_key:
        pytest.fail(_FAIL_REASON)
    return LiteLLMProvider(api_key=_api_key, default_model=MODEL)


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
        memory=MemoryConfig(window=10, reranker=RerankerConfig(mode="disabled")),
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
        memory_enabled=True,
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
