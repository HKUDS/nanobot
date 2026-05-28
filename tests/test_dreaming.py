"""Tests for the DreamingService (M3) — periodic LLM-driven promotion of
daily-note facts into MEMORY.md sections."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.dream.service import DreamingService


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def _provider_returning(promotions: list[dict] | None) -> MagicMock:
    """Build a mock provider whose chat() returns a tool call with these promotions."""
    response = MagicMock()
    if promotions is None:
        response.has_tool_calls = False
        response.tool_calls = []
    else:
        response.has_tool_calls = True
        tc = MagicMock()
        tc.arguments = {"promotions": promotions}
        response.tool_calls = [tc]
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=response)
    return provider


# ---- skip paths --------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_skips_when_no_daily_notes(workspace: Path) -> None:
    svc = DreamingService(workspace=workspace, provider=_provider_returning([]), model="m", enabled=True)
    result = await svc.tick()
    assert result == {"status": "skipped", "reason": "no_daily_notes"}


@pytest.mark.asyncio
async def test_tick_skips_when_all_notes_already_dreamed(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("entry")
    # Pre-populate sidecar with today's date marked dreamed
    today = datetime.now().strftime("%Y-%m-%d")
    (store.memory_dir / DreamingService.SIDECAR_NAME).write_text(
        json.dumps({"dreamed_dates": [today]}), encoding="utf-8",
    )
    provider = _provider_returning([])
    svc = DreamingService(workspace=workspace, provider=provider, model="m", enabled=True)
    result = await svc.tick()
    assert result["status"] == "skipped"
    assert result["reason"] == "nothing_new"
    provider.chat.assert_not_called()


@pytest.mark.asyncio
async def test_tick_skips_when_llm_omits_tool_call(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("entry")
    svc = DreamingService(workspace=workspace, provider=_provider_returning(None), model="m", enabled=True)
    result = await svc.tick()
    assert result == {"status": "skipped", "reason": "no_tool_call"}


# ---- promotion paths ---------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_promotes_facts_into_sections(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("Glyn disclosed an episode of voices on 2026-05-28")
    store.write_long_term("## Pinned (do not compress)\n- existing safety note\n")

    promotions = [
        {"section": "Pinned", "fact": "[2026-05-28] Voices recurred — grounding helped", "salience": "safety"},
        {"section": "Mental Health & Wellbeing", "fact": "[2026-05-28] Episode managed at home", "salience": "event"},
    ]
    svc = DreamingService(workspace=workspace, provider=_provider_returning(promotions), model="m", enabled=True)
    result = await svc.tick()

    assert result["status"] == "ok"
    assert result["promoted"] == 2

    pinned = store.get_pinned()
    assert "existing safety note" in pinned, "existing Pinned content must be preserved"
    assert "Voices recurred" in pinned

    mh = store.get_section("Mental Health & Wellbeing")
    assert "Episode managed at home" in mh


@pytest.mark.asyncio
async def test_pinned_section_uses_canonical_heading(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("e")
    svc = DreamingService(
        workspace=workspace, model="m", enabled=True,
        provider=_provider_returning([
            {"section": "pinned", "fact": "safety thing", "salience": "safety"},
        ]),
    )
    await svc.tick()
    assert "## Pinned (do not compress)" in store.read_long_term()


# ---- dedupe ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_skips_facts_already_in_section(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("e")
    store.write_long_term("## Pinned (do not compress)\n- already present\n")
    svc = DreamingService(
        workspace=workspace, model="m", enabled=True,
        provider=_provider_returning([
            {"section": "Pinned", "fact": "already present", "salience": "safety"},
            {"section": "Pinned", "fact": "new fact", "salience": "safety"},
        ]),
    )
    result = await svc.tick()
    assert result["promoted"] == 1
    assert result["skipped_existing"] == 1


# ---- sidecar / idempotency ---------------------------------------------------


@pytest.mark.asyncio
async def test_sidecar_marks_dreamed_dates(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("e")
    svc = DreamingService(workspace=workspace, provider=_provider_returning([]), model="m", enabled=True)
    await svc.tick()

    sidecar = json.loads(svc.sidecar_path.read_text(encoding="utf-8"))
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in sidecar["dreamed_dates"]
    assert "last_run" in sidecar
    assert sidecar.get("last_promoted") == 0


@pytest.mark.asyncio
async def test_second_run_only_considers_new_dates(workspace: Path) -> None:
    store = MemoryStore(workspace)
    yesterday = datetime.now() - timedelta(days=1)
    store.write_daily("old", when=yesterday)
    store.write_daily("today")

    provider = _provider_returning([])
    svc = DreamingService(workspace=workspace, provider=provider, model="m", enabled=True)
    await svc.tick()
    assert provider.chat.await_count == 1

    # Second tick: both dates are now in sidecar; nothing new
    result2 = await svc.tick()
    assert result2 == {"status": "skipped", "reason": "nothing_new"}
    assert provider.chat.await_count == 1, "should not have hit the LLM again"


# ---- malformed responses don't blow up ---------------------------------------


@pytest.mark.asyncio
async def test_handles_string_arguments_from_provider(workspace: Path) -> None:
    """Some providers return tool-call arguments as a JSON string instead of dict."""
    store = MemoryStore(workspace)
    store.write_daily("e")
    response = MagicMock()
    response.has_tool_calls = True
    tc = MagicMock()
    tc.arguments = json.dumps({
        "promotions": [{"section": "Pinned", "fact": "stringified", "salience": "safety"}]
    })
    response.tool_calls = [tc]
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=response)

    svc = DreamingService(workspace=workspace, provider=provider, model="m", enabled=True)
    result = await svc.tick()
    assert result["status"] == "ok"
    assert "stringified" in store.get_pinned()


@pytest.mark.asyncio
async def test_disabled_service_does_not_start(workspace: Path) -> None:
    svc = DreamingService(workspace=workspace, provider=MagicMock(), model="m", enabled=False)
    await svc.start()
    assert svc._task is None


@pytest.mark.asyncio
async def test_handles_provider_exception(workspace: Path) -> None:
    store = MemoryStore(workspace)
    store.write_daily("e")
    provider = MagicMock()
    provider.chat = AsyncMock(side_effect=RuntimeError("LLM down"))
    svc = DreamingService(workspace=workspace, provider=provider, model="m", enabled=True)
    result = await svc.tick()
    assert result == {"status": "error", "reason": "llm_failed"}
