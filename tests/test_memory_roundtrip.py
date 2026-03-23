"""LLM round-trip tests for the full memory lifecycle.

These tests verify the core user-facing promise: "does the agent remember
what I told it?"  Each scenario runs a real conversation through the
consolidation pipeline with a real LLM (gpt-4o-mini), then checks that the
extracted information surfaces in ``get_memory_context()``.

Assertions are fuzzy keyword checks -- we never assert on exact LLM wording.

Requires: OPENAI_API_KEY or LITELLM_API_KEY in environment.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Skip entire module when no LLM API key is available.
_has_api_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LITELLM_API_KEY"))
if not _has_api_key:
    pytest.skip(
        "No LLM API key available (OPENAI_API_KEY / LITELLM_API_KEY)", allow_module_level=True
    )

from nanobot.agent.memory.store import MemoryStore  # noqa: E402
from nanobot.providers.litellm_provider import LiteLLMProvider  # noqa: E402

pytestmark = pytest.mark.llm

_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Minimal Session stub -- mirrors the fields consolidate() accesses.
# ---------------------------------------------------------------------------


@dataclass
class _Session:
    """Lightweight stand-in for ``nanobot.session.manager.Session``."""

    key: str = "test:roundtrip"
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_consolidated: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider() -> LiteLLMProvider:
    return LiteLLMProvider(default_model=_MODEL)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def store(workspace: Path) -> MemoryStore:
    return MemoryStore(workspace, embedding_provider="hash")


def _make_session(*turns: tuple[str, str]) -> _Session:
    """Build a session from (role, content) pairs."""
    sess = _Session(key=f"test:{uuid.uuid4().hex[:8]}")
    for role, content in turns:
        sess.add_message(role, content)
    return sess


# ---------------------------------------------------------------------------
# Scenario 1: preference consolidation
# ---------------------------------------------------------------------------


async def test_preference_consolidation(store: MemoryStore, provider: LiteLLMProvider) -> None:
    session = _make_session(
        ("user", "I always want responses in bullet points"),
        ("assistant", "Got it! I'll format my responses using bullet points from now on."),
    )

    ok = await store.consolidate(
        session,
        provider,
        _MODEL,
        archive_all=True,  # type: ignore[arg-type]
    )
    assert ok, "consolidation should succeed"

    context = store.get_memory_context(query="How should I format responses?")
    assert "bullet" in context.lower(), f"Expected 'bullet' in memory context, got:\n{context}"


# ---------------------------------------------------------------------------
# Scenario 2: fact storage
# ---------------------------------------------------------------------------


async def test_fact_storage(store: MemoryStore, provider: LiteLLMProvider) -> None:
    session = _make_session(
        ("user", "I work at Globex Corporation as a senior engineer"),
        ("assistant", "Nice! Globex Corporation — that's a great place to be a senior engineer."),
    )

    ok = await store.consolidate(
        session,
        provider,
        _MODEL,
        archive_all=True,  # type: ignore[arg-type]
    )
    assert ok, "consolidation should succeed"

    context = store.get_memory_context(query="Where does the user work?")
    assert "globex" in context.lower(), f"Expected 'globex' in memory context, got:\n{context}"


# ---------------------------------------------------------------------------
# Scenario 3: multi-turn accumulation
# ---------------------------------------------------------------------------


async def test_multi_turn_accumulation(store: MemoryStore, provider: LiteLLMProvider) -> None:
    conversations = [
        [("user", "I prefer dark mode"), ("assistant", "Noted, dark mode preference saved.")],
        [
            ("user", "My main project is Phoenix, a web app"),
            ("assistant", "Got it — Phoenix is your main web app project."),
        ],
        [
            ("user", "The deadline for Phoenix is April 15th"),
            ("assistant", "Understood, April 15th deadline for Phoenix."),
        ],
    ]

    for turns in conversations:
        session = _make_session(*turns)
        ok = await store.consolidate(
            session,
            provider,
            _MODEL,
            archive_all=True,  # type: ignore[arg-type]
        )
        assert ok, "consolidation should succeed"

    context = store.get_memory_context(query="Tell me about the user").lower()

    hits = sum(
        [
            "dark" in context,
            "phoenix" in context,
            "april" in context or "15" in context,
        ]
    )
    assert hits >= 2, f"Expected at least 2 of 3 facts in context (got {hits}):\n{context}"


# ---------------------------------------------------------------------------
# Scenario 4: context assembly after consolidation
# ---------------------------------------------------------------------------


async def test_context_assembly_after_consolidation(
    store: MemoryStore, provider: LiteLLMProvider
) -> None:
    # Seed profile with an existing fact.
    profile = store.profile_mgr.read_profile()
    profile.setdefault("stable_facts", []).append(
        {
            "text": "User's favorite language is Python",
            "confidence": 0.95,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }
    )
    store.profile_mgr.write_profile(profile)

    # Consolidate a new conversation mentioning an additional fact.
    session = _make_session(
        ("user", "I just started learning Rust for systems programming"),
        ("assistant", "That's exciting! Rust is great for systems work."),
    )
    ok = await store.consolidate(
        session,
        provider,
        _MODEL,
        archive_all=True,  # type: ignore[arg-type]
    )
    assert ok, "consolidation should succeed"

    context = store.get_memory_context(query="What programming languages does the user know?")
    assert len(context) > 100, (
        f"Expected substantial context (>100 chars), got {len(context)} chars:\n{context}"
    )
    assert "python" in context.lower(), f"Expected seeded 'python' fact in context, got:\n{context}"


# ---------------------------------------------------------------------------
# Scenario 5: fact correction
# ---------------------------------------------------------------------------


async def test_fact_correction(store: MemoryStore, provider: LiteLLMProvider) -> None:
    # Seed an old fact via a first consolidation round.
    old_session = _make_session(
        ("user", "I work at Acme Corp as a developer"),
        ("assistant", "Got it, you're a developer at Acme Corp."),
    )
    ok = await store.consolidate(
        old_session,
        provider,
        _MODEL,
        archive_all=True,  # type: ignore[arg-type]
    )
    assert ok, "initial consolidation should succeed"

    # Now correct the fact.
    new_session = _make_session(
        ("user", "I left Acme, I'm at Globex now"),
        ("assistant", "Congratulations on the move to Globex!"),
    )
    ok = await store.consolidate(
        new_session,
        provider,
        _MODEL,
        archive_all=True,  # type: ignore[arg-type]
    )
    assert ok, "correction consolidation should succeed"

    context = store.get_memory_context(query="Where does the user work?")
    assert "globex" in context.lower(), (
        f"Expected 'globex' in memory context after correction, got:\n{context}"
    )
