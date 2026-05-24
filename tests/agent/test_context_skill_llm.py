"""Async integration tests for LLM skill selection in ContextBuilder."""

from __future__ import annotations

import asyncio
from pathlib import Path

from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import SkillsLoader
from nanobot.config.schema import SkillRetrievalConfig
from nanobot.providers.base import LLMProvider, LLMResponse


def _write_skill(base: Path, name: str, *, description: str) -> None:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "\n".join(["---", f"description: {description}", "---", "", f"# {name}\n"]),
        encoding="utf-8",
    )


class _ScriptedProvider(LLMProvider):
    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content

    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content=self._content)

    def get_default_model(self) -> str:
        return "test-model"


def _make_builder(
    tmp_path: Path,
    *,
    provider: LLMProvider,
    mode: str,
    top_k: int = 8,
) -> ContextBuilder:
    workspace = tmp_path / "ws"
    ws_skills = workspace / "skills"
    ws_skills.mkdir(parents=True)
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    retrieval = SkillRetrievalConfig(
        enable=True,
        mode=mode,  # type: ignore[arg-type]
        top_k=top_k,
        fts_candidate_k=20,
        llm_skill_threshold=15,
        rebuild_on_startup=False,
        query_cache_size=0,
    )
    builder = ContextBuilder(
        workspace,
        skill_retrieval=retrieval,
        skill_llm_provider=provider,
    )
    builder.skills = SkillsLoader(workspace, builtin_skills_dir=builtin)
    return builder


def test_resolve_skill_entries_llm_mode_selects_from_catalog(tmp_path: Path) -> None:
    builder = _make_builder(
        tmp_path,
        provider=_ScriptedProvider('{"skills": ["cron"]}'),
        mode="llm",
        top_k=2,
    )
    _write_skill(builder.workspace / "skills", "cron", description="Schedule reminders and cron jobs")
    _write_skill(builder.workspace / "skills", "pdf", description="Generate PDF documents")
    builder.warm_skill_index()

    entries = asyncio.run(
        builder.resolve_skill_entries(
            "please schedule a reminder",
            exclude=set(),
        )
    )
    assert entries is not None
    assert [entry["name"] for entry in entries] == ["cron"]


def test_resolve_skill_entries_hybrid_falls_back_to_fts_when_llm_empty(
    tmp_path: Path,
) -> None:
    builder = _make_builder(
        tmp_path,
        provider=_ScriptedProvider('{"skills": []}'),
        mode="hybrid",
        top_k=2,
    )
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders and cron jobs")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")
    _write_skill(ws_skills, "github", description="GitHub pull request workflows")
    builder.warm_skill_index()

    entries = asyncio.run(
        builder.resolve_skill_entries(
            "set a cron reminder",
            exclude=set(),
        )
    )
    assert entries is not None
    names = [entry["name"] for entry in entries]
    assert "cron" in names
    assert len(names) <= 2


def test_resolve_skill_entries_auto_uses_llm_for_small_catalog(tmp_path: Path) -> None:
    builder = _make_builder(
        tmp_path,
        provider=_ScriptedProvider('{"skills": ["pdf"]}'),
        mode="auto",
        top_k=2,
    )
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")
    builder.warm_skill_index()

    entries = asyncio.run(builder.resolve_skill_entries("make a pdf", exclude=set()))
    assert entries is not None
    assert [entry["name"] for entry in entries] == ["pdf"]


def test_build_system_prompt_with_preresolved_llm_entries(tmp_path: Path) -> None:
    builder = _make_builder(
        tmp_path,
        provider=_ScriptedProvider('{"skills": ["cron"]}'),
        mode="llm",
    )
    ws_skills = builder.workspace / "skills"
    _write_skill(ws_skills, "cron", description="Schedule reminders and cron jobs")
    _write_skill(ws_skills, "pdf", description="Generate PDF documents")
    builder.warm_skill_index()

    entries = asyncio.run(builder.resolve_skill_entries("cron reminder", exclude=set()))
    prompt = builder.build_system_prompt(
        retrieval_query="cron reminder",
        skill_entries=entries,
    )
    assert "**cron**" in prompt
    assert "**pdf**" not in prompt
