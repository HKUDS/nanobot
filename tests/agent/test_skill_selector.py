"""Tests for nanobot.agent.skill_selector."""

from __future__ import annotations

import asyncio

from nanobot.agent.skill_selector import (
    SkillCandidate,
    SkillLLMSelector,
    order_selected_candidates,
    parse_skill_selection_response,
)
from nanobot.config.schema import SkillRetrievalConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class _ScriptedProvider(LLMProvider):
    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=self._content)

    def get_default_model(self) -> str:
        return "test-model"


def test_parse_skill_selection_response_json_object() -> None:
    selected = parse_skill_selection_response(
        '{"skills": ["cron", "pdf", "unknown"]}',
        allowed={"cron", "pdf"},
        max_k=8,
    )
    assert selected == ["cron", "pdf"]


def test_parse_skill_selection_response_strips_code_fence() -> None:
    selected = parse_skill_selection_response(
        '```json\n{"skills": ["cron"]}\n```',
        allowed={"cron"},
        max_k=8,
    )
    assert selected == ["cron"]


def test_parse_skill_selection_response_empty_on_invalid_json() -> None:
    assert parse_skill_selection_response("not json", allowed={"cron"}, max_k=8) == []


def test_order_selected_candidates_preserves_candidate_order() -> None:
    candidates = [
        SkillCandidate("pdf", "PDF"),
        SkillCandidate("cron", "Cron"),
        SkillCandidate("github", "GitHub"),
    ]
    ordered = order_selected_candidates(
        candidates,
        ["cron", "pdf"],
        max_k=8,
    )
    assert ordered == ["pdf", "cron"]


def test_skill_llm_selector_returns_allowed_names_in_candidate_order() -> None:
    provider = _ScriptedProvider('{"skills": ["cron"]}')
    selector = SkillLLMSelector(
        provider,
        SkillRetrievalConfig(enable=True, mode="llm", top_k=2, query_cache_size=0),
    )
    candidates = [
        SkillCandidate("pdf", "Generate PDF documents"),
        SkillCandidate("cron", "Schedule reminders"),
        SkillCandidate("github", "GitHub workflows"),
    ]
    selected = asyncio.run(selector.select("set a cron reminder", candidates, k=2))
    assert selected == ["cron"]
    assert provider.calls == 1


def test_skill_llm_selector_uses_cache_on_repeat_query() -> None:
    provider = _ScriptedProvider('{"skills": ["cron"]}')
    selector = SkillLLMSelector(
        provider,
        SkillRetrievalConfig(enable=True, mode="llm", query_cache_size=8),
    )
    candidates = [SkillCandidate("cron", "Schedule reminders")]
    first = asyncio.run(selector.select("cron reminder", candidates, k=1))
    second = asyncio.run(selector.select("cron reminder", candidates, k=1))
    assert first == second == ["cron"]
    assert provider.calls == 1


def test_skill_llm_selector_returns_empty_on_provider_error() -> None:
    provider = _ScriptedProvider("")
    provider.chat = _fail_chat  # type: ignore[method-assign]
    selector = SkillLLMSelector(
        provider,
        SkillRetrievalConfig(enable=True, mode="llm", query_cache_size=0),
    )
    selected = asyncio.run(
        selector.select(
            "cron",
            [SkillCandidate("cron", "Schedule reminders")],
            k=1,
        )
    )
    assert selected == []


async def _fail_chat(*args, **kwargs) -> LLMResponse:
    raise RuntimeError("provider down")
