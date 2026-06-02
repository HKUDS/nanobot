"""Tests for L1 LLM extraction (LM2-C)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.layered_memory.l0_store import L0Store
from nanobot.agent.layered_memory.l1_extractor import (
    L1Extractor,
    format_dialogue,
    parse_l1_response,
)
from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.pipeline import MemoryPipelineManager, PipelineTriggerReason
from nanobot.agent.layered_memory.sanitize import L0CaptureRow
from nanobot.config.schema import LayeredMemoryCaptureConfig, LayeredMemoryConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content='{"atoms": []}')

    def get_default_model(self) -> str:
        return "test-model"


def _atom_response(content: str, *, memory_type: str = "preference") -> LLMResponse:
    payload = {
        "atoms": [
            {
                "type": memory_type,
                "content": content,
                "source_turn_ids": ["turn-1"],
            }
        ]
    }
    return LLMResponse(content=json.dumps(payload))


@pytest.fixture
def lm_cfg() -> LayeredMemoryConfig:
    return LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
    )


def test_parse_l1_response_json_fence() -> None:
    raw = '```json\n{"atoms": [{"type": "fact", "content": "Name is Alice"}]}\n```'
    atoms = parse_l1_response(raw)
    assert len(atoms) == 1
    assert atoms[0].memory_type == "fact"
    assert atoms[0].content == "Name is Alice"


def test_format_dialogue_groups_turns() -> None:
    from nanobot.agent.layered_memory.l0_store import L0MessageRecord

    records = [
        L0MessageRecord(
            id=1,
            session_key="s",
            turn_id="turn-1",
            role="user",
            name=None,
            tool_call_id=None,
            content="I prefer Python",
            timestamp_ms=1,
        ),
        L0MessageRecord(
            id=2,
            session_key="s",
            turn_id="turn-1",
            role="assistant",
            name=None,
            tool_call_id=None,
            content="Noted.",
            timestamp_ms=2,
        ),
    ]
    text = format_dialogue(records)
    assert "--- turn: turn-1 ---" in text
    assert "user: I prefer Python" in text


@pytest.mark.asyncio
async def test_extractor_inserts_atom_from_fixture(
    tmp_path: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    l0 = L0Store(tmp_path)
    l1 = L1Store(tmp_path)
    l0.append_messages(
        "cli:direct",
        "turn-1",
        [
            L0CaptureRow(role="user", content="Please always reply in Chinese.", timestamp_ms=1),
            L0CaptureRow(role="assistant", content="好的。", timestamp_ms=2),
        ],
    )
    provider = DummyProvider([_atom_response("User prefers replies in Chinese")])
    extractor = L1Extractor(tmp_path, lm_cfg, provider, l0_store=l0, l1_store=l1)

    await extractor.run(
        "cli:direct",
        reason=PipelineTriggerReason.THRESHOLD,
        turn_ids=("turn-1",),
        chunk=1,
    )

    assert provider.calls == 1
    assert l1.count_session("cli:direct") == 1
    hits = l1.search("Chinese", session_key="cli:direct")
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_extractor_dedup_on_second_run(
    tmp_path: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    l0 = L0Store(tmp_path)
    l1 = L1Store(tmp_path)
    l0.append_messages(
        "cli:direct",
        "turn-1",
        [L0CaptureRow(role="user", content="I like tea.", timestamp_ms=1)],
    )
    provider = DummyProvider(
        [
            _atom_response("User likes tea"),
            _atom_response("User likes tea"),
        ]
    )
    extractor = L1Extractor(tmp_path, lm_cfg, provider, l0_store=l0, l1_store=l1)

    await extractor.run(
        "cli:direct",
        reason=PipelineTriggerReason.THRESHOLD,
        turn_ids=("turn-1",),
        chunk=1,
    )
    await extractor.run(
        "cli:direct",
        reason=PipelineTriggerReason.IDLE,
        turn_ids=("turn-1",),
        chunk=1,
    )

    assert l1.count_session("cli:direct") == 1


@pytest.mark.asyncio
async def test_pipeline_with_real_extractor_triggers_l1(
    tmp_path: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    lm_cfg.pipeline.every_n_conversations = 1
    lm_cfg.pipeline.enable_warmup = False
    l0 = L0Store(tmp_path)
    l1 = L1Store(tmp_path)
    l0.append_messages(
        "cli:direct",
        "t1",
        [L0CaptureRow(role="user", content="My name is Bob.", timestamp_ms=1)],
    )
    provider = DummyProvider([_atom_response("User name is Bob", memory_type="fact")])
    extractor = L1Extractor(tmp_path, lm_cfg, provider, l0_store=l0, l1_store=l1)
    mgr = MemoryPipelineManager(lm_cfg, l1_handler=extractor.run)

    await mgr.notify_turn("cli:direct", turn_id="t1")

    assert l1.count_session("cli:direct") == 1
