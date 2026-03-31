"""Tests for mini planner and lightweight retrieval context."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.retrieval import ProjectRetriever


def test_project_retriever_returns_relevant_snippets(tmp_path):
    (tmp_path / "README.md").write_text("Nanobot supports telegram and task lifecycle tools.\n", encoding="utf-8")
    (tmp_path / "NOTES.md").write_text("Unrelated note about apples.\n", encoding="utf-8")

    retriever = ProjectRetriever(tmp_path, refresh_interval_s=1)
    hits = retriever.search("telegram task lifecycle", max_chunks=2)

    assert hits
    assert any(path == "README.md" for path, _ in hits)


def test_context_builder_injects_retrieval_context(tmp_path):
    (tmp_path / "README.md").write_text("Planner should run before tool execution.\n", encoding="utf-8")
    cb = ContextBuilder(tmp_path, retrieval_enabled=True, retrieval_max_chunks=1)

    messages = cb.build_messages(history=[], current_message="How does planner execution work?")
    user_msg = messages[-1]["content"]

    assert isinstance(user_msg, str)
    assert "[Project Retrieval Context" in user_msg
    assert "Source: README.md" in user_msg


def test_loop_should_plan_heuristic():
    assert AgentLoop._should_plan("please implement this feature in multiple steps", min_chars=20) is True
    assert AgentLoop._should_plan("hi", min_chars=20) is False


@pytest.mark.asyncio
async def test_build_mini_plan_returns_compact_text():
    loop = AgentLoop.__new__(AgentLoop)
    loop.mini_planner_enabled = True
    loop.mini_planner_max_steps = 4
    loop.mini_planner_min_query_chars = 10
    loop.model = "test-model"
    loop.provider = SimpleNamespace(
        chat_with_retry=AsyncMock(return_value=SimpleNamespace(content="1. Read\n2. Edit\n3. Verify"))
    )

    out = await loop._build_mini_plan([], "Implement a medium-sized refactor for this module.")
    assert out is not None
    assert "1." in out

