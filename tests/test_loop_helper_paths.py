from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.agent.loop import AgentLoop


def _make_loop(tmp_path: Path) -> AgentLoop:
    loop = object.__new__(AgentLoop)
    loop.workspace = tmp_path
    loop._active_messages = []
    loop._scratchpad = None
    loop.memory_uncertainty_threshold = 0.6
    loop._consolidation_locks = {}
    loop.context = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda *_a, **_k: []))
    return loop


def test_classify_task_type_paths() -> None:
    assert AgentLoop._classify_task_type("writing", "write a summary") == "report_writing"
    assert AgentLoop._classify_task_type("code", "fix this bug") == "bug_investigation"
    assert AgentLoop._classify_task_type("research", "architecture dependency map") == "repo_architecture"
    assert AgentLoop._classify_task_type("research", "current industry trends") == "web_research"
    assert AgentLoop._classify_task_type("research", "nanobot architecture overview") == "repo_architecture"
    assert AgentLoop._classify_task_type("general", "hello world") == "general"


def test_extract_plan_and_user_request(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    assert loop._extract_plan_text() == ""
    assert loop._extract_user_request() == ""

    loop._active_messages = [
        {"role": "user", "content": "  fix tests  "},
        {"role": "system", "content": "please outline a numbered plan"},
        {"role": "assistant", "content": "  1. search\n2. patch  "},
    ]
    assert loop._extract_user_request() == "fix tests"
    assert loop._extract_plan_text().startswith("1. search")


def test_build_execution_context_includes_conditional_excerpts(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme body", encoding="utf-8")
    loop = _make_loop(tmp_path)

    general = loop._build_execution_context("general")
    assert "Workspace:" in general
    assert "AGENTS.md (excerpt)" not in general

    investigative = loop._build_execution_context("repo_architecture")
    assert "AGENTS.md (excerpt)" in investigative
    assert "README.md (excerpt)" in investigative


def test_build_parallel_and_contract_includes_optional_sections(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop._scratchpad = SimpleNamespace(
        list_entries=lambda: [
            {"role": "code", "label": "done one"},
            {"role": "research", "label": "done two"},
        ]
    )
    loop._active_messages = [{"role": "user", "content": "User request"}]
    loop._extract_plan_text = lambda: "1. p"  # type: ignore[method-assign]
    loop._build_execution_context = lambda _tt: "ctx"  # type: ignore[method-assign]
    loop._gather_recent_tool_results = lambda: "prior"  # type: ignore[method-assign]

    summary = loop._build_parallel_work_summary("code")
    assert "research" in summary
    assert "code" not in summary

    user_content, output_schema = loop._build_delegation_contract(
        role="code",
        task="inspect module",
        context="focus failures",
        task_type="local_code_analysis",
    )
    assert "Original User Request" in user_content
    assert "Other Agents' Work" in user_content
    assert "Overall Plan" in user_content
    assert "Prior Results" in user_content
    assert "Your response MUST use this structure" in output_schema


def test_verification_helpers_and_lock_lifecycle(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    assert AgentLoop._looks_like_question("How are you") is True
    assert AgentLoop._looks_like_question("status update") is False

    loop.context = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda *_a, **_k: [{"score": "x"}]))
    assert loop._estimate_grounding_confidence("q") == 0.0
    loop.context = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda *_a, **_k: [{"score": 1.3}]))
    assert loop._estimate_grounding_confidence("q") == 1.0
    loop.context = SimpleNamespace(memory=SimpleNamespace(retrieve=lambda *_a, **_k: [{"score": 0.2}]))
    assert loop._should_force_verification("What is this") is True

    lock = loop._get_consolidation_lock("s1")
    assert isinstance(lock, asyncio.Lock)
    loop._prune_consolidation_lock("s1", lock)
    assert "s1" not in loop._consolidation_locks


@pytest.mark.asyncio
async def test_attempt_recovery_missing_or_error_paths(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop.provider = SimpleNamespace(chat=None)
    loop.model = "m"
    loop.temperature = 0.0
    loop.max_tokens = 32

    # Missing system/user pair -> skip recovery.
    assert await loop._attempt_recovery(SimpleNamespace(channel="c", chat_id="id"), []) is None

    async def _raise_chat(**_kwargs):
        raise RuntimeError("boom")

    loop.provider = SimpleNamespace(chat=_raise_chat)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert await loop._attempt_recovery(SimpleNamespace(channel="c", chat_id="id"), msgs) is None


def test_fallback_archive_snapshot_success_and_failure(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    sink: list[str] = []
    loop.context = SimpleNamespace(
        memory=SimpleNamespace(append_history=lambda text: sink.append(text))
    )
    assert loop._fallback_archive_snapshot([
        {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00"}
    ]) is True
    assert sink and "Fallback archive" in sink[0]

    loop.context = SimpleNamespace(memory=SimpleNamespace(append_history=lambda _t: (_ for _ in ()).throw(RuntimeError("x"))))
    assert loop._fallback_archive_snapshot([{"role": "user", "content": "hello"}]) is False