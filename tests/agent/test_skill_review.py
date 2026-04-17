"""Tests for nanobot.agent.skill_review.SkillReviewService."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.skill_evo.skill_review import SkillReviewService
from nanobot.agent.skill_evo.skill_store import SkillStore
from nanobot.agent.skills import SkillsLoader
from nanobot.config.schema import SkillsConfig


def _make_review_service(tmp_path: Path, **config_overrides) -> tuple[SkillReviewService, SkillStore, Path]:
    workspace = tmp_path / "ws"
    (workspace / "skills").mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()

    store = SkillStore(workspace=workspace, session_key="test")
    catalog = SkillsLoader(workspace, builtin_skills_dir=builtin)
    config = SkillsConfig(**{
        "review_enabled": True,
        "review_max_iterations": 3,
        **config_overrides,
    })

    provider = MagicMock()
    service = SkillReviewService(
        provider=provider,
        model="test-model",
        store=store,
        catalog=catalog,
        config=config,
    )
    return service, store, workspace


def test_summarize_conversation_extracts_text() -> None:
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "assistant", "tool_calls": [{"function": {"name": "read_file"}}]},
        {"role": "tool", "content": "file contents"},
    ]
    result = SkillReviewService._summarize_conversation(messages)
    assert "--- USER ---\nHello" in result
    assert "--- ASSISTANT ---\nHi there" in result
    assert "read_file" in result
    assert "--- TOOL_RESULT ---\nfile contents" in result


def test_summarize_conversation_handles_multimodal_content() -> None:
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "Look at this"},
            {"type": "image_url", "image_url": {"url": "data:..."}},
        ]},
    ]
    result = SkillReviewService._summarize_conversation(messages)
    assert "Look at this" in result


def test_summarize_conversation_empty() -> None:
    result = SkillReviewService._summarize_conversation([])
    assert result == ""


@pytest.mark.asyncio
async def test_review_turn_does_not_propagate_exceptions(tmp_path: Path) -> None:
    service, _, _ = _make_review_service(tmp_path)
    # Make runner.run raise
    service._runner = MagicMock()
    service._runner.run = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    # Should not raise
    await service.review_turn(
        [{"role": "user", "content": "test"}],
        session_key="test-session",
    )


@pytest.mark.asyncio
async def test_review_turn_skips_empty_conversation(tmp_path: Path) -> None:
    service, _, _ = _make_review_service(tmp_path)
    service._runner = MagicMock()
    service._runner.run = AsyncMock()

    await service.review_turn([], session_key="test-session")
    service._runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_review_builds_correct_tools(tmp_path: Path) -> None:
    service, _, _ = _make_review_service(tmp_path)
    tools = service._build_tools()
    tool_names = set(tools.tool_names)
    assert "skills_list" in tool_names
    assert "skill_view" in tool_names
    assert "skill_manage" in tool_names
    assert len(tool_names) == 3


def test_review_respects_model_override(tmp_path: Path) -> None:
    service, _, _ = _make_review_service(tmp_path, review_model_override="gpt-4o-mini")
    assert service._model == "gpt-4o-mini"


def test_review_uses_default_model_when_no_override(tmp_path: Path) -> None:
    service, _, _ = _make_review_service(tmp_path)
    assert service._model == "test-model"
