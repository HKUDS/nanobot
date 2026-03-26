"""Integration test for micro-extraction with real LLM."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from nanobot.memory.store import MemoryStore
from nanobot.memory.write.micro_extractor import MicroExtractor


@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping LLM integration test",
)
@pytest.mark.asyncio
async def test_micro_extraction_real_llm(tmp_path: Path) -> None:
    """Micro-extraction produces valid events from a realistic exchange."""
    from nanobot.providers.openai import OpenAIProvider

    provider = OpenAIProvider(api_key=os.environ["OPENAI_API_KEY"])
    store = MemoryStore(tmp_path)

    extractor = MicroExtractor(
        provider=provider,
        ingester=store.ingester,
        model="gpt-4o-mini",
        enabled=True,
    )

    await extractor.submit(
        user_message="I always work on the DS10540 project with Alice. We use PostgreSQL for the database.",
        assistant_message="Got it! I'll remember that you work on DS10540 with Alice and that the project uses PostgreSQL.",
    )

    # Wait for background task to complete deterministically
    if extractor._pending_tasks:
        await asyncio.gather(*extractor._pending_tasks, return_exceptions=True)

    # Verify events were ingested into the database
    events = store.ingester.read_events(limit=20)
    assert len(events) > 0, "Expected at least one event to be extracted"

    # Check that extracted events contain relevant content
    summaries = " ".join(e.get("summary", "") for e in events).lower()
    assert any(term in summaries for term in ["ds10540", "alice", "postgresql"]), (
        f"Expected relevant entities in summaries, got: {summaries}"
    )
