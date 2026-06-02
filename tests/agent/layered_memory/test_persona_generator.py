"""Tests for L3 persona generation (LM3-B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.agent.layered_memory.l1_store import L1Store
from nanobot.agent.layered_memory.persona.backup import user_file_path
from nanobot.agent.layered_memory.persona.generator import (
    PersonaGenerator,
    format_atoms,
    format_scene_bodies,
    format_scene_index,
    parse_l3_response,
)
from nanobot.agent.layered_memory.pipeline import L3TriggerReason
from nanobot.agent.layered_memory.scene.index import SceneEntry, SceneIndex
from nanobot.config.schema import (
    LayeredMemoryCaptureConfig,
    LayeredMemoryConfig,
    LayeredMemoryPersonaConfig,
)
from nanobot.providers.base import LLMProvider, LLMResponse


class DummyProvider(LLMProvider):
    def __init__(self, responses: list[LLMResponse]):
        super().__init__()
        self._responses = list(responses)

    async def chat(self, *args, **kwargs) -> LLMResponse:
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content='{"action": "skip"}')

    def get_default_model(self) -> str:
        return "test-model"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def lm_cfg() -> LayeredMemoryConfig:
    return LayeredMemoryConfig(
        enable=True,
        capture=LayeredMemoryCaptureConfig(enable=True),
        persona=LayeredMemoryPersonaConfig(
            enable=True,
            min_interval_seconds=0,
            backup_count=2,
        ),
    )


def _update_response(content: str) -> LLMResponse:
    payload = {
        "action": "update",
        "content_md": content,
    }
    return LLMResponse(content=json.dumps(payload))


def test_parse_l3_response_json_fence() -> None:
    raw = '```json\n{"action": "skip"}\n```'
    items = parse_l3_response(raw)
    assert len(items) == 1
    assert items[0].action == "skip"


def test_format_scene_index_empty() -> None:
    assert format_scene_index([]) == "(none)"


def test_format_atoms_empty() -> None:
    assert format_atoms([]) == "(none)"


def test_format_scene_bodies_reads_file(workspace: Path) -> None:
    index = SceneIndex(workspace)
    index.write_scene_markdown("demo", "# Demo\n\nBody text")
    entries = [
        SceneEntry(
            slug="demo",
            title="Demo",
            path="memory/scenes/demo.md",
            updated_at=1.0,
        )
    ]
    body = format_scene_bodies(workspace, index, entries)
    assert "Body text" in body


@pytest.mark.asyncio
async def test_persona_generator_writes_user_md(
    workspace: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    user_file_path(workspace).write_text("# Old profile\n", encoding="utf-8")
    l1 = L1Store(workspace)
    l1.insert(
        session_key="cli:direct",
        memory_type="preference",
        content="Prefers Chinese replies",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    index = SceneIndex(workspace)
    index.write_scene_markdown("profile", "# Profile\n\nChinese user")
    index.upsert(
        SceneEntry(
            slug="profile",
            title="Profile",
            path="memory/scenes/profile.md",
            updated_at=1.0,
        )
    )
    provider = DummyProvider(
        [_update_response("# User Profile\n\n- Communicates in Chinese\n")]
    )
    gen = PersonaGenerator(
        workspace,
        lm_cfg,
        provider,
        l1_store=l1,
        scene_index=index,
    )
    await gen.run("cli:direct", reason=L3TriggerReason.AFTER_L2)

    user_md = user_file_path(workspace).read_text(encoding="utf-8")
    assert "Chinese" in user_md
    assert len(list((workspace / ".nanobot/persona_backups").glob("USER.*.md"))) >= 1


@pytest.mark.asyncio
async def test_persona_generator_skip_no_write(
    workspace: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    user_file_path(workspace).write_text("# Old\n", encoding="utf-8")
    l1 = L1Store(workspace)
    l1.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="Some fact",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    provider = DummyProvider([LLMResponse(content='{"action": "skip"}')])
    gen = PersonaGenerator(workspace, lm_cfg, provider, l1_store=l1)
    await gen.run("cli:direct", reason=L3TriggerReason.AFTER_L2)
    assert user_file_path(workspace).read_text(encoding="utf-8") == "# Old\n"


@pytest.mark.asyncio
async def test_persona_generator_disabled(
    workspace: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    lm_cfg.persona.enable = False
    l1 = L1Store(workspace)
    l1.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="fact",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    provider = DummyProvider([_update_response("# New")])
    gen = PersonaGenerator(workspace, lm_cfg, provider, l1_store=l1)
    await gen.run("cli:direct", reason=L3TriggerReason.AFTER_L2)
    assert not user_file_path(workspace).exists()


@pytest.mark.asyncio
async def test_persona_generator_truncates_long_content(
    workspace: Path,
    lm_cfg: LayeredMemoryConfig,
) -> None:
    lm_cfg.persona.max_user_chars = 50
    l1 = L1Store(workspace)
    l1.insert(
        session_key="cli:direct",
        memory_type="fact",
        content="fact",
        source_l0_ids=(1,),
        source_turn_ids=("t1",),
    )
    long_body = "x" * 200
    provider = DummyProvider([_update_response(long_body)])
    gen = PersonaGenerator(workspace, lm_cfg, provider, l1_store=l1)
    await gen.run("cli:direct", reason=L3TriggerReason.AFTER_L2)
    written = user_file_path(workspace).read_text(encoding="utf-8")
    assert len(written.strip()) <= 50
