from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from nanobot.agent.consolidation import ConsolidationOrchestrator
from nanobot.agent.delegation import DelegationDispatcher
from nanobot.agent.delegation_contract import (
    build_execution_context,
    build_parallel_work_summary,
    extract_plan_text,
    extract_user_request,
)
from nanobot.agent.loop import AgentLoop
from nanobot.agent.task_types import classify_task_type
from nanobot.agent.verifier import AnswerVerifier


def _make_loop(tmp_path: Path) -> AgentLoop:
    loop = object.__new__(AgentLoop)
    loop.workspace = tmp_path
    loop.config = SimpleNamespace(memory_uncertainty_threshold=0.6, max_tokens=32)
    dispatcher = object.__new__(DelegationDispatcher)
    dispatcher.active_messages = []
    dispatcher.routing_trace = []
    dispatcher.delegation_count = 0
    dispatcher.workspace = tmp_path
    dispatcher.scratchpad = None
    loop._dispatcher = dispatcher
    loop._scratchpad = None
    mem_ns = SimpleNamespace(
        retrieve=lambda *_a, **_k: [],
        append_history=lambda _t: None,
    )
    loop.context = SimpleNamespace(memory=mem_ns)
    loop._consolidator = ConsolidationOrchestrator(memory=mem_ns)
    loop._verifier = AnswerVerifier(
        provider=None,  # type: ignore[arg-type]
        model="m",
        temperature=0.0,
        max_tokens=32,
        verification_mode="off",
        memory_uncertainty_threshold=0.6,
        memory_store=mem_ns,  # type: ignore[arg-type]
    )
    return loop


def test_classify_task_type_paths() -> None:
    assert classify_task_type("writing", "write a summary") == "report_writing"
    assert classify_task_type("code", "fix this bug") == "bug_investigation"
    assert classify_task_type("research", "architecture dependency map") == "repo_architecture"
    assert classify_task_type("research", "current industry trends") == "web_research"
    assert classify_task_type("research", "nanobot architecture overview") == "repo_architecture"
    assert classify_task_type("general", "hello world") == "general"
    # hybrid: web + arch/code/project signals combined
    assert classify_task_type("research", "architecture of best practice DI frameworks") == "hybrid"
    assert (
        classify_task_type("research", "compare our codebase with current industry best practices")
        == "hybrid"
    )
    assert (
        classify_task_type("research", "latest best practices for Python module structure")
        == "hybrid"
    )


def test_extract_plan_and_user_request(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    assert extract_plan_text(list(loop._dispatcher.active_messages)) == ""
    assert extract_user_request(list(loop._dispatcher.active_messages)) == ""

    loop._dispatcher.active_messages = [  # type: ignore[assignment]
        {"role": "user", "content": "  fix tests  "},
        {"role": "system", "content": "please outline a numbered plan"},
        {"role": "assistant", "content": "  1. search\n2. patch  "},
    ]
    assert extract_user_request(list(loop._dispatcher.active_messages)) == "fix tests"
    assert extract_plan_text(list(loop._dispatcher.active_messages)).startswith("1. search")


def test_build_execution_context_includes_conditional_excerpts(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme body", encoding="utf-8")

    general = build_execution_context(tmp_path, "general")
    assert "Workspace:" in general
    assert "AGENTS.md (excerpt)" not in general

    investigative = build_execution_context(tmp_path, "repo_architecture")
    assert "AGENTS.md (excerpt)" in investigative
    assert "README.md (excerpt)" in investigative


def test_build_parallel_and_contract_includes_optional_sections(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    from nanobot.agent import delegation_contract

    scratchpad = SimpleNamespace(
        list_entries=lambda: [
            {"role": "code", "label": "done one"},
            {"role": "research", "label": "done two"},
        ]
    )

    summary = build_parallel_work_summary(scratchpad, "code")
    assert "research" in summary
    assert "code" not in summary

    # Mock helpers to verify contract assembly without real workspace I/O
    monkeypatch.setattr(  # type: ignore[union-attr]
        delegation_contract,
        "extract_plan_text",
        lambda msgs: "1. p",
    )
    monkeypatch.setattr(  # type: ignore[union-attr]
        delegation_contract,
        "build_execution_context",
        lambda ws, tt: "ctx",
    )
    monkeypatch.setattr(  # type: ignore[union-attr]
        delegation_contract,
        "gather_recent_tool_results",
        lambda msgs, **kw: "prior",
    )

    from nanobot.agent.delegation_contract import build_delegation_contract

    active_messages = [{"role": "user", "content": "User request"}]
    user_content, output_schema = build_delegation_contract(
        role="code",
        task="inspect module",
        context="focus failures",
        task_type="local_code_analysis",
        workspace=tmp_path,
        active_messages=active_messages,
        scratchpad=scratchpad,
    )
    assert "Original User Request" in user_content
    assert "Other Agents' Work" in user_content
    assert "Overall Plan" in user_content
    assert "Prior Results" in user_content
    assert "Your response MUST use this structure" in output_schema


def test_verification_helpers_and_lock_lifecycle(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    assert AnswerVerifier._looks_like_question("How are you") is True
    assert AnswerVerifier._looks_like_question("status update") is False

    # Test _estimate_grounding_confidence via the verifier
    v = loop._verifier
    v._memory = SimpleNamespace(
        retriever=SimpleNamespace(retrieve=lambda *_a, **_k: [{"score": "x"}])
    )
    assert v._estimate_grounding_confidence("q") == 0.0
    v._memory = SimpleNamespace(
        retriever=SimpleNamespace(retrieve=lambda *_a, **_k: [{"score": 1.3}])
    )
    assert v._estimate_grounding_confidence("q") == 1.0
    v._memory = SimpleNamespace(
        retriever=SimpleNamespace(retrieve=lambda *_a, **_k: [{"score": 0.2}])
    )
    assert v.should_force_verification("What is this") is True


async def test_attempt_recovery_missing_or_error_paths(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    verifier = loop._verifier
    verifier.provider = SimpleNamespace(chat=None)

    # Missing system/user pair -> skip recovery.
    assert await verifier.attempt_recovery(channel="c", chat_id="id", all_msgs=[]) is None

    async def _raise_chat(**_kwargs):
        raise RuntimeError("boom")

    verifier.provider = SimpleNamespace(chat=_raise_chat)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert await verifier.attempt_recovery(channel="c", chat_id="id", all_msgs=msgs) is None


# ---------------------------------------------------------------------------
# Tool registry injection (LAN-149)
# ---------------------------------------------------------------------------


def _make_loop_via_init(
    tmp_path: Path,
    provider: object,
    *,
    tool_registry: object | None = None,
) -> AgentLoop:
    """Build an AgentLoop through its real __init__ with minimal config."""
    from nanobot.bus.queue import MessageBus
    from nanobot.config.schema import AgentConfig

    bus = MessageBus()
    config = AgentConfig(
        workspace=str(tmp_path),
        model="test-model",
        memory_window=10,
        max_iterations=5,
        planning_enabled=False,
        verification_mode="off",
    )
    kwargs: dict[str, object] = {}
    if tool_registry is not None:
        kwargs["tool_registry"] = tool_registry
    from nanobot.agent.agent_factory import build_agent

    return build_agent(bus=bus, provider=provider, config=config, **kwargs)  # type: ignore[arg-type]


class _StubProvider:
    """Minimal stand-in satisfying LLMProvider duck-typing for construction."""

    def get_default_model(self) -> str:
        return "stub-model"

    async def chat(self, **kwargs: object) -> object:  # noqa: ARG002
        return SimpleNamespace(content="", tool_calls=None, usage=None)


class TestToolRegistryInjection:
    def test_injected_registry_skips_default_tools(self, tmp_path: Path) -> None:
        """When tool_registry is provided, _register_default_tools is skipped."""
        from nanobot.tools.registry import ToolRegistry

        reg = ToolRegistry()
        loop = _make_loop_via_init(tmp_path, _StubProvider(), tool_registry=reg)
        # The injected registry should be used — no default tools registered.
        assert len(loop.tools) == 0

    def test_default_registry_has_tools(self, tmp_path: Path) -> None:
        """Without injection, default tools are registered as before."""
        loop = _make_loop_via_init(tmp_path, _StubProvider())
        # Default registration adds at least the filesystem + exec tools.
        assert len(loop.tools) > 0
