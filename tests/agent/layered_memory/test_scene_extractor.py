"""Tests for L2 scene extraction (LM3-A)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.pipeline import L2TriggerReason
from nanobot.agent.layered_memory.scene.extractor import (
    SceneExtractor,
    parse_l2_response,
)
from nanobot.agent.layered_memory.scene.index import SceneIndex
from nanobot.config.schema import LayeredMemoryCaptureConfig, LayeredMemoryConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content='{"scenes": [{"action": "skip"}]}')

    def get_default_model(self) -> str:
        return "test-model"


def _scene_response() -> LLMResponse:
    payload = {
        "scenes": [
            {
                "action": "create",
                "slug": "git-workflow",
                "title": "Git 工作流",
                "summary": "No auto commit",
                "content_md": "# Git 工作流\n\n## Rules\n- Never auto commit",
                "source_atom_ids": ["l1_test123"],
            }
        ]
    }
    return LLMResponse(content=json.dumps(payload))


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def lm_cfg() -> LayeredMemoryConfig:
    return LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
    )


def test_parse_l2_response_json_fence() -> None:
    raw = '```json\n{"scenes": [{"action": "skip"}]}\n```'
    scenes = parse_l2_response(raw)
    assert len(scenes) == 1
    assert scenes[0].action == "skip"


@pytest.mark.asyncio
async def test_scene_extractor_writes_file(
    workspace: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    l1 = L1Store(workspace)
    l1.insert(
        session_key="cli:direct",
        memory_type="rule",
        content='Only commit when user says "commit"',
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    provider = DummyProvider([_scene_response()])
    extractor = SceneExtractor(
        workspace,
        lm_cfg,
        provider,
        l1_store=l1,
        scene_index=SceneIndex(workspace),
    )
    await extractor.run("cli:direct", reason=L2TriggerReason.AFTER_L1)

    scene_path = workspace / "memory" / "scenes" / "git-workflow.md"
    assert scene_path.is_file()
    assert "Never auto commit" in scene_path.read_text(encoding="utf-8")
    entries = SceneIndex(workspace).load()
    assert entries[0].slug == "git-workflow"
    assert "cli:direct" in entries[0].session_keys
