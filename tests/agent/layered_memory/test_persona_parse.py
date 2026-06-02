"""Additional coverage for L3 persona parsing and edge paths."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from filelock import Timeout

from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.persona.generator import (
    PersonaGenerator,
    _read_current_user,
    parse_l3_response,
)
from nanobot.agent.layered_memory.persona.lock import PersonaLock
from nanobot.agent.layered_memory.pipeline import L3TriggerReason
from nanobot.config.schema import (
    LayeredMemoryCaptureConfig,
    LayeredMemoryConfig,
    LayeredMemoryPersonaConfig,
)
from nanobot.providers.base import LLMProvider, LLMResponse


class DummyProvider(LLMProvider):
    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content='{"action": "skip"}')

    def get_default_model(self) -> str:
        return "test-model"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_parse_l3_response_list_and_proposals_key() -> None:
    payload = {"proposals": [{"action": "update", "content_md": "# U\n"}]}
    items = parse_l3_response(json.dumps(payload))
    assert items[0].action == "update"

    items2 = parse_l3_response(json.dumps([{"action": "skip"}]))
    assert items2[0].action == "skip"


def test_parse_l3_response_invalid_json() -> None:
    assert parse_l3_response("not json") == []
    assert parse_l3_response("") == []


def test_read_current_user_missing(workspace: Path) -> None:
    assert _read_current_user(workspace) == ""


@pytest.mark.asyncio
async def test_persona_skip_when_no_input(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
        persona=LayeredMemoryPersonaConfig(enable=True),
    )
    gen = PersonaGenerator(workspace, cfg, DummyProvider())
    await gen.run("sess", reason=L3TriggerReason.AFTER_L2)


@pytest.mark.asyncio
async def test_persona_llm_timeout(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
        persona=LayeredMemoryPersonaConfig(enable=True),
    )
    l1 = L1Store(workspace)
    l1.insert(
        session_key="s",
        memory_type="fact",
        content="fact",
        source_l0_ids=(1,),
        source_turn_ids=("t",),
    )

    class SlowProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            await asyncio.sleep(0.2)
            return LLMResponse(content='{"action": "skip"}')

    gen = PersonaGenerator(workspace, cfg, SlowProvider(), l1_store=l1)
    with patch("nanobot.agent.layered_memory.persona.generator._LLM_TIMEOUT_S", 0.05):
        await gen.run("s", reason=L3TriggerReason.AFTER_L2)


@pytest.mark.asyncio
async def test_persona_provider_error(workspace: Path) -> None:
    cfg = LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
        persona=LayeredMemoryPersonaConfig(enable=True),
    )
    l1 = L1Store(workspace)
    l1.insert(
        session_key="s",
        memory_type="fact",
        content="fact",
        source_l0_ids=(1,),
        source_turn_ids=("t",),
    )

    class ErrProvider(DummyProvider):
        async def chat(self, *args, **kwargs) -> LLMResponse:
            return LLMResponse(content="bad", finish_reason="error")

    gen = PersonaGenerator(workspace, cfg, ErrProvider(), l1_store=l1)
    await gen.run("s", reason=L3TriggerReason.AFTER_L2)


def test_persona_lock_timeout(workspace: Path) -> None:
    lock = PersonaLock(workspace, timeout_seconds=0.01)
    mock_lock = MagicMock()
    mock_lock.acquire.side_effect = Timeout("persona")
    lock._lock = mock_lock
    with pytest.raises(Timeout):
        with lock.hold():
            pass
