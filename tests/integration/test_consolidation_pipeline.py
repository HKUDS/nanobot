"""IT-04: Consolidation pipeline with real LLM.

Verifies that the memory consolidation pipeline — extracting events from
conversation history, storing them, and surfacing them in memory context —
works end-to-end with a real LLM (gpt-4o-mini).

Assertions use fuzzy keyword checks; we never assert on exact LLM wording.

Requires: OPENAI_API_KEY or LITELLM_API_KEY.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from nanobot.memory.store import MemoryStore
from nanobot.providers.litellm_provider import LiteLLMProvider
from tests.integration.conftest import MODEL

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Minimal Session stub — mirrors the fields consolidate() accesses.
# Same pattern as tests/test_memory_roundtrip.py.
# ---------------------------------------------------------------------------


@dataclass
class _Session:
    """Lightweight stand-in for ``nanobot.session.manager.Session``."""

    key: str = "test:consolidation"
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_consolidated: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **kwargs,
            }
        )
        self.updated_at = datetime.now(timezone.utc)


def _make_session(*turns: tuple[str, str]) -> _Session:
    """Build a session from (role, content) pairs."""
    sess = _Session(key=f"test:{uuid.uuid4().hex[:8]}")
    for role, content in turns:
        sess.add_message(role, content)
    return sess


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConsolidationPipeline:
    async def test_preference_consolidation(
        self, store: MemoryStore, provider: LiteLLMProvider
    ) -> None:
        """Consolidating a preference conversation surfaces it in memory context."""
        session = _make_session(
            ("user", "I always want responses in bullet points"),
            ("assistant", "Got it! I'll format my responses using bullet points from now on."),
        )

        ok = await store.consolidate(
            session,
            provider,
            MODEL,
            archive_all=True,  # type: ignore[arg-type]
        )
        assert ok, "consolidation should succeed"

        context = await store.get_memory_context(query="How should I format responses?")
        assert "bullet" in context.lower(), f"Expected 'bullet' in memory context, got:\n{context}"

    async def test_fact_consolidation(self, store: MemoryStore, provider: LiteLLMProvider) -> None:
        """Consolidating a fact conversation surfaces it in memory context."""
        session = _make_session(
            ("user", "I work at Globex Corporation as a senior engineer"),
            (
                "assistant",
                "Nice! Globex Corporation — that's a great place to be a senior engineer.",
            ),
        )

        ok = await store.consolidate(
            session,
            provider,
            MODEL,
            archive_all=True,  # type: ignore[arg-type]
        )
        assert ok, "consolidation should succeed"

        context = await store.get_memory_context(query="Where does the user work?")
        assert "globex" in context.lower(), f"Expected 'globex' in memory context, got:\n{context}"

    async def test_consolidation_advances_pointer(
        self, store: MemoryStore, provider: LiteLLMProvider
    ) -> None:
        """After non-archive consolidation, last_consolidated advances."""
        # Need enough messages to exceed keep_count (memory_window // 2).
        # Default memory_window=50, keep_count=25, so we need >25 messages.
        # Use archive_all=False with a small memory_window to trigger advancement.
        session = _make_session(
            ("user", "I prefer Python"),
            ("assistant", "Great choice!"),
            ("user", "I also like Rust"),
            ("assistant", "Rust is fast!"),
            ("user", "And Go for microservices"),
            ("assistant", "Go is solid for that."),
        )
        original_pointer = session.last_consolidated
        assert original_pointer == 0

        ok = await store.consolidate(
            session,
            provider,
            MODEL,
            memory_window=2,  # small window so keep_count=1, old_messages=5
        )
        assert ok, "consolidation should succeed"
        assert session.last_consolidated > original_pointer, (
            f"Expected last_consolidated to advance past {original_pointer}, "
            f"got {session.last_consolidated}"
        )
