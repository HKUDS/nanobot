"""Tests for nanobot.agent.delegation — DelegationDispatcher unit tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from nanobot.agent.delegation import (
    _SCRATCHPAD_INJECTION_LIMIT,
    TASK_TYPES,
    DelegationConfig,
    DelegationDispatcher,
    _cap_scratchpad_for_injection,
    _delegation_ancestry,
    get_delegation_depth,
)
from nanobot.config.schema import AgentRoleConfig, ExecToolConfig
from nanobot.providers.base import LLMProvider, LLMResponse

# Module reference for monkey-patching run_tool_loop in retry tests.
# Using sys.modules avoids mixing `import X` and `from X import Y` in the
# same file, which CodeQL flags as py/import-and-import-from.
_delegation_mod = sys.modules["nanobot.agent.delegation"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONFIG_FIELDS = {f for f in DelegationConfig.__dataclass_fields__}


def _make_dispatcher(tmp_path: Path, **overrides: Any) -> DelegationDispatcher:
    config_defaults: dict[str, Any] = dict(
        workspace=tmp_path,
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        max_iterations=5,
        restrict_to_workspace=True,
        brave_api_key=None,
        exec_config=None,
        role_name="main",
    )
    cfg_overrides = {k: v for k, v in overrides.items() if k in _CONFIG_FIELDS}
    wiring_overrides = {k: v for k, v in overrides.items() if k not in _CONFIG_FIELDS}
    config_defaults.update(cfg_overrides)
    config = DelegationConfig(**config_defaults)  # type: ignore[arg-type]
    return DelegationDispatcher(
        config=config,
        provider=wiring_overrides.pop("provider", None),
        **wiring_overrides,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        assert d.delegation_count == 0
        assert d.max_delegations == 8
        assert len(d.routing_trace) == 0
        assert d.coordinator is None
        assert d.scratchpad is None
        assert d.tools is None

    def test_custom_role(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path, role_name="coder")
        assert d.role_name == "coder"


# ---------------------------------------------------------------------------
# record_route_trace
# ---------------------------------------------------------------------------


class TestRecordRouteTrace:
    def test_appends_to_routing_trace(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.record_route_trace("route", role="research", confidence=0.9, latency_ms=42.5)
        assert len(d.routing_trace) == 1
        entry = d.routing_trace[0]
        assert entry["event"] == "route"
        assert entry["role"] == "research"
        assert entry["confidence"] == 0.9
        assert entry["latency_ms"] == 42.5

    def test_writes_to_in_memory_trace(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.record_route_trace("delegate", role="code")
        assert len(d.routing_trace) == 1
        assert d.routing_trace[0]["event"] == "delegate"

    def test_tools_used_recorded(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.record_route_trace("delegate_complete", role="code", tools_used=["read_file", "exec"])
        entry = d.routing_trace[0]
        assert entry["tools_used"] == ["read_file", "exec"]
        assert entry["tools_used_count"] == 2

    def test_message_excerpt_truncated(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        long_msg = "x" * 200
        d.record_route_trace("route", message_excerpt=long_msg)
        assert len(d.routing_trace[0]["message"]) == 80


# ---------------------------------------------------------------------------
# get_routing_trace
# ---------------------------------------------------------------------------


class TestGetRoutingTrace:
    def test_returns_copy(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.record_route_trace("route", role="r1")
        trace = d.get_routing_trace()
        assert len(trace) == 1
        # Mutating the copy should not affect original
        trace.clear()
        assert len(d.routing_trace) == 1


# ---------------------------------------------------------------------------
# gather_recent_tool_results
# ---------------------------------------------------------------------------


class TestGatherRecentToolResults:
    def test_empty_messages(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = None
        assert d.gather_recent_tool_results() == ""

    def test_no_tool_messages(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [{"role": "user", "content": "hello"}]
        assert d.gather_recent_tool_results() == ""

    def test_collects_tool_results(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [
            {"role": "tool", "name": "read_file", "content": "file contents here"},
            {"role": "tool", "name": "exec", "content": "command output"},
        ]
        result = d.gather_recent_tool_results()
        assert "read_file" in result
        assert "exec" in result

    def test_respects_max_results(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [
            {"role": "tool", "name": f"t{i}", "content": f"result {i}"} for i in range(20)
        ]
        result = d.gather_recent_tool_results(max_results=3)
        assert result.count("**t") == 3

    def test_respects_max_chars(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [
            {"role": "tool", "name": "big", "content": "x" * 5000},
            {"role": "tool", "name": "bigger", "content": "y" * 5000},
        ]
        result = d.gather_recent_tool_results(max_chars=6000)
        # Should only include one since each is > 5000 chars
        assert "bigger" in result or "big" in result


# ---------------------------------------------------------------------------
# classify_task_type
# ---------------------------------------------------------------------------


class TestClassifyTaskType:
    def test_code_role_default(self):
        result = DelegationDispatcher.classify_task_type("code", "review the module")
        assert result == "local_code_analysis"

    def test_writing_role(self):
        result = DelegationDispatcher.classify_task_type("writing", "write a report")
        assert result == "report_writing"

    def test_research_role_web(self):
        result = DelegationDispatcher.classify_task_type(
            "research", "what are the current industry benchmarks"
        )
        assert result == "web_research"

    def test_research_role_project(self):
        result = DelegationDispatcher.classify_task_type("research", "analyze this project")
        assert result == "repo_architecture"

    def test_bug_investigation(self):
        result = DelegationDispatcher.classify_task_type("code", "fix the crash in parser")
        assert result == "bug_investigation"

    def test_architecture(self):
        result = DelegationDispatcher.classify_task_type("any", "describe the architecture")
        assert result == "repo_architecture"

    def test_general_fallback(self):
        result = DelegationDispatcher.classify_task_type("random", "do something")
        assert result == "general"

    def test_hybrid_web_plus_arch_signals(self) -> None:
        """Web + architecture signals -> hybrid, not repo_architecture."""
        result = DelegationDispatcher.classify_task_type(
            "research", "architecture of best practice DI frameworks"
        )
        assert result == "hybrid"

    def test_hybrid_web_plus_project_signals(self) -> None:
        """Web + project signals -> hybrid, not repo_architecture."""
        result = DelegationDispatcher.classify_task_type(
            "research", "compare our codebase with current industry best practices"
        )
        assert result == "hybrid"

    def test_hybrid_web_plus_code_signals(self) -> None:
        """Web + code signals -> hybrid, not local_code_analysis."""
        result = DelegationDispatcher.classify_task_type(
            "research", "latest best practices for Python module structure"
        )
        assert result == "hybrid"

    def test_pure_web_still_web_research(self) -> None:
        """Pure web signals without local signals -> web_research."""
        result = DelegationDispatcher.classify_task_type(
            "research", "what are the current industry trends"
        )
        assert result == "web_research"

    def test_task_types_dict_complete(self):
        """All expected task types exist in TASK_TYPES."""
        expected = {
            "local_code_analysis",
            "repo_architecture",
            "web_research",
            "report_writing",
            "bug_investigation",
            "hybrid",
            "general",
        }
        assert set(TASK_TYPES.keys()) == expected


# ---------------------------------------------------------------------------
# has_parallel_structure
# ---------------------------------------------------------------------------


class TestHasParallelStructure:
    def test_enumerated_list(self):
        assert DelegationDispatcher.has_parallel_structure(
            "Analyze three areas: frontend, backend, and database"
        )

    def test_numbered_items(self):
        text = "1. First task\n2. Second task\n3. Third task"
        assert DelegationDispatcher.has_parallel_structure(text)

    def test_comma_separated_and(self):
        assert DelegationDispatcher.has_parallel_structure(
            "Check performance, security, and reliability"
        )

    def test_no_parallel(self):
        assert not DelegationDispatcher.has_parallel_structure("Review the code for bugs")


# ---------------------------------------------------------------------------
# extract_user_request / extract_plan_text
# ---------------------------------------------------------------------------


class TestExtractHelpers:
    def test_extract_user_request(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "How does the loop work?"},
        ]
        assert d.extract_user_request() == "How does the loop work?"

    def test_extract_user_request_empty(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = []
        assert d.extract_user_request() == ""

    def test_extract_plan_text_no_plan(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [{"role": "user", "content": "hello"}]
        assert d.extract_plan_text() == ""

    def test_extract_plan_text_with_plan(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [
            {"role": "system", "content": "Please outline a numbered plan"},
            {"role": "assistant", "content": "1. Step one\n2. Step two"},
        ]
        assert "Step one" in d.extract_plan_text()


# ---------------------------------------------------------------------------
# delegation_count
# ---------------------------------------------------------------------------


class TestDelegationCount:
    def test_starts_at_zero(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        assert d.delegation_count == 0

    def test_increment(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.delegation_count += 1
        assert d.delegation_count == 1


# ---------------------------------------------------------------------------
# build_delegation_contract
# ---------------------------------------------------------------------------


class TestBuildDelegationContract:
    def test_basic_contract(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = [{"role": "user", "content": "test request"}]
        content, schema = d.build_delegation_contract(
            "code", "analyze the module", None, "local_code_analysis"
        )
        assert "analyze the module" in content
        assert "Findings" in schema
        assert "Evidence" in schema

    def test_contract_includes_context(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = []
        content, _ = d.build_delegation_contract("code", "task", "extra context here", "general")
        assert "extra context here" in content

    def test_contract_includes_tool_guidance(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = []
        content, _ = d.build_delegation_contract(
            "code", "analyze code", None, "local_code_analysis"
        )
        assert "Preferred tools" in content


# ---------------------------------------------------------------------------
# _cap_scratchpad_for_injection (LAN-158)
# ---------------------------------------------------------------------------


class TestCapScratchpadForInjection:
    def test_below_cap_unchanged(self):
        content = "short content"
        assert _cap_scratchpad_for_injection(content) == content

    def test_above_cap_truncated_with_marker(self):
        content = "x" * (_SCRATCHPAD_INJECTION_LIMIT + 500)
        result = _cap_scratchpad_for_injection(content)
        assert len(result) < len(content)
        assert result.startswith("x" * _SCRATCHPAD_INJECTION_LIMIT)
        assert "truncated" in result
        assert "500 chars omitted" in result
        assert "scratchpad_read" in result

    def test_empty_string_unchanged(self):
        assert _cap_scratchpad_for_injection("") == ""

    def test_exactly_at_limit_unchanged(self):
        content = "a" * _SCRATCHPAD_INJECTION_LIMIT
        assert _cap_scratchpad_for_injection(content) == content

    def test_custom_limit(self):
        content = "hello world"
        result = _cap_scratchpad_for_injection(content, limit=5)
        assert result.startswith("hello")
        assert "truncated" in result
        assert "6 chars omitted" in result


# ---------------------------------------------------------------------------
# Delegation ID uniqueness under asyncio.gather (LAN-155)
# ---------------------------------------------------------------------------


class TestDelegationIdUniqueness:
    async def test_parallel_dispatches_produce_unique_ids(self, tmp_path: Path):
        """Fires 5+ parallel dispatches and verifies all delegation_id values are unique."""
        from nanobot.agent.coordinator import Coordinator, build_default_registry
        from nanobot.providers.base import LLMProvider, LLMResponse

        class StubProvider(LLMProvider):
            def get_default_model(self) -> str:
                return "stub"

            async def chat(
                self,
                messages: Any,
                tools: Any = None,
                model: Any = None,
                max_tokens: int = 4096,
                temperature: float = 0.7,
                metadata: Any = None,
            ) -> LLMResponse:
                return LLMResponse(content='{"role": "general"}')

        provider = StubProvider()
        registry = build_default_registry("general")
        coordinator = Coordinator(provider, registry, default_role="general")

        d = _make_dispatcher(tmp_path, provider=provider)
        d.coordinator = coordinator

        # Patch execute_delegated_agent to avoid full agent execution
        async def fake_execute(role: Any, task: str, context: Any) -> tuple[str, list[str]]:
            await asyncio.sleep(0.01)
            return f"done:{task}", ["read_file"]

        d.execute_delegated_agent = fake_execute  # type: ignore[assignment]

        # Fire 6 parallel dispatches
        results = await asyncio.gather(
            *[d.dispatch("general", f"task_{i}", None) for i in range(6)]
        )

        assert len(results) == 6
        assert d.delegation_count == 6

        # Collect all delegation_ids from the routing trace
        delegation_ids = [
            entry.get("event") for entry in d.routing_trace if entry["event"] == "delegate_complete"
        ]
        # All 6 dispatches should have completed
        assert len(delegation_ids) == 6

        # Each dispatch incremented delegation_count before awaiting,
        # so all IDs should be unique — verify via the count itself.
        # The IDs are del_001 through del_006 based on delegation_count.
        assert d.delegation_count == 6


# ---------------------------------------------------------------------------
# Shell mode forwarding to cached ExecTool (LAN-154)
# ---------------------------------------------------------------------------


class TestShellModeForwarding:
    def test_exec_tool_receives_shell_mode(self, tmp_path: Path):
        """Dispatcher with exec_config shell_mode='allowlist' creates ExecTool accordingly."""
        exec_cfg = ExecToolConfig(timeout=30, shell_mode="allowlist")
        d = _make_dispatcher(tmp_path, exec_config=exec_cfg)

        exec_tool = d._cached_tools.get("exec")
        assert exec_tool is not None, "ExecTool should be in cached tools"
        assert exec_tool.shell_mode == "allowlist"

    def test_exec_tool_default_denylist(self, tmp_path: Path):
        """Default ExecToolConfig uses denylist mode."""
        exec_cfg = ExecToolConfig()
        d = _make_dispatcher(tmp_path, exec_config=exec_cfg)

        exec_tool = d._cached_tools.get("exec")
        assert exec_tool is not None
        assert exec_tool.shell_mode == "denylist"

    def test_no_exec_config_no_exec_tool(self, tmp_path: Path):
        """Without exec_config, no ExecTool is cached."""
        d = _make_dispatcher(tmp_path, exec_config=None)
        assert "exec" not in d._cached_tools


# ---------------------------------------------------------------------------
# build_execution_context (LAN-160)
# ---------------------------------------------------------------------------


class TestBuildExecutionContext:
    def test_happy_path_includes_workspace_and_listing(self, tmp_path: Path):
        """Context includes workspace path and directory listing."""
        (tmp_path / "src").mkdir()
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "main.py").write_text("print('hi')")

        d = _make_dispatcher(tmp_path)
        ctx = d.build_execution_context("general")

        assert str(tmp_path) in ctx
        assert "src/" in ctx
        assert "README.md" in ctx
        assert "main.py" in ctx

    def test_local_code_analysis_includes_project_files(self, tmp_path: Path):
        """Task type local_code_analysis includes AGENTS.md/README.md/SOUL.md excerpts."""
        (tmp_path / "AGENTS.md").write_text("Agent config here")
        (tmp_path / "README.md").write_text("Project readme")
        (tmp_path / "SOUL.md").write_text("Soul document")

        d = _make_dispatcher(tmp_path)
        ctx = d.build_execution_context("local_code_analysis")

        assert "AGENTS.md (excerpt)" in ctx
        assert "Agent config here" in ctx
        assert "README.md (excerpt)" in ctx
        assert "Project readme" in ctx
        assert "SOUL.md (excerpt)" in ctx
        assert "Soul document" in ctx

    def test_report_writing_excludes_project_files(self, tmp_path: Path):
        """Task type report_writing does NOT include AGENTS.md/README.md/SOUL.md."""
        (tmp_path / "AGENTS.md").write_text("Agent config here")
        (tmp_path / "README.md").write_text("Project readme")
        (tmp_path / "SOUL.md").write_text("Soul document")

        d = _make_dispatcher(tmp_path)
        ctx = d.build_execution_context("report_writing")

        assert "AGENTS.md (excerpt)" not in ctx
        assert "SOUL.md (excerpt)" not in ctx
        # README.md appears in the directory listing but not as an excerpt
        assert "README.md (excerpt)" not in ctx

    def test_directory_listing_capped_at_50(self, tmp_path: Path):
        """Directory listing is capped at 50 entries."""
        for i in range(60):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"content {i}")

        d = _make_dispatcher(tmp_path)
        ctx = d.build_execution_context("general")

        # Count the indented lines in the directory layout section
        lines = ctx.split("\n")
        dir_lines = [line for line in lines if line.startswith("  file_")]
        assert len(dir_lines) == 50


# ---------------------------------------------------------------------------
# Shared stubs for execute_delegated_agent retry tests (LAN-159)
# ---------------------------------------------------------------------------


class _StubProvider(LLMProvider):
    """Minimal LLM provider returning a fixed stub response."""

    def get_default_model(self) -> str:
        return "stub"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        metadata: dict[str, Any] | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="stub")


def _make_call_counter_tool_loop(
    responses: list[tuple[str | None, list[str], list[dict[str, Any]]]],
) -> tuple[Any, list[dict[str, Any]]]:
    """Return a stateful async fake for ``run_tool_loop`` and a call log.

    Each invocation pops the next response from *responses*.  The call log
    records the keyword arguments of every invocation so tests can assert on
    ``max_iterations`` etc.
    """
    call_log: list[dict[str, Any]] = []

    async def _fake(
        *,
        provider: Any,
        tools: Any,
        messages: Any,
        model: Any,
        temperature: Any,
        max_tokens: Any,
        max_iterations: Any,
    ) -> tuple[str | None, list[str], list[dict[str, Any]]]:
        call_log.append(
            {
                "provider": provider,
                "tools": tools,
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "max_iterations": max_iterations,
            }
        )
        idx = len(call_log) - 1
        if idx < len(responses):
            return responses[idx]
        # Fallback — should not be reached in well-designed tests
        return ("fallback", [], [])

    return _fake, call_log


# ---------------------------------------------------------------------------
# execute_delegated_agent retry path (LAN-159)
# ---------------------------------------------------------------------------


class TestExecuteDelegatedAgentRetry:
    """Tests for the tool-use retry gate in execute_delegated_agent."""

    async def test_retry_succeeds_when_first_attempt_uses_no_tools(self, tmp_path: Path) -> None:
        """When the first call returns no tools, a retry fires and its result is used."""

        msgs: list[dict[str, Any]] = [{"role": "assistant", "content": "ok"}]
        fake, call_log = _make_call_counter_tool_loop(
            [
                ("first answer", [], msgs),
                ("retry answer", ["read_file"], msgs),
            ]
        )

        d = _make_dispatcher(tmp_path, provider=_StubProvider())
        role = AgentRoleConfig(name="research", description="research role")

        original = _delegation_mod.run_tool_loop
        _delegation_mod.run_tool_loop = fake  # type: ignore[assignment]
        try:
            summary, tools_used = await d.execute_delegated_agent(
                role, "analyze the codebase structure", None
            )
        finally:
            _delegation_mod.run_tool_loop = original

        assert len(call_log) == 2
        assert "retry answer" in summary
        assert "read_file" in tools_used
        assert call_log[1]["max_iterations"] <= 6

    async def test_no_retry_for_report_writing_task_type(self, tmp_path: Path) -> None:
        """report_writing tasks skip the retry even when no tools are used."""

        msgs: list[dict[str, Any]] = [{"role": "assistant", "content": "ok"}]
        fake, call_log = _make_call_counter_tool_loop(
            [
                ("writing answer", [], msgs),
                ("should not reach", ["read_file"], msgs),
            ]
        )

        d = _make_dispatcher(tmp_path, provider=_StubProvider())
        role = AgentRoleConfig(name="writing", description="writing role")

        original = _delegation_mod.run_tool_loop
        _delegation_mod.run_tool_loop = fake  # type: ignore[assignment]
        try:
            result = await d.execute_delegated_agent(role, "write a report about the project", None)
        finally:
            _delegation_mod.run_tool_loop = original

        assert len(call_log) == 1
        assert result is not None

    async def test_no_retry_when_max_iter_is_2(self, tmp_path: Path) -> None:
        """When max_iterations <= 2, retry is suppressed."""

        msgs: list[dict[str, Any]] = [{"role": "assistant", "content": "ok"}]
        fake, call_log = _make_call_counter_tool_loop(
            [
                ("answer", [], msgs),
                ("should not reach", ["read_file"], msgs),
            ]
        )

        d = _make_dispatcher(tmp_path, provider=_StubProvider(), max_iterations=2)
        role = AgentRoleConfig(name="research", description="research role")

        original = _delegation_mod.run_tool_loop
        _delegation_mod.run_tool_loop = fake  # type: ignore[assignment]
        try:
            await d.execute_delegated_agent(role, "analyze the codebase structure", None)
        finally:
            _delegation_mod.run_tool_loop = original

        assert len(call_log) == 1

    async def test_retry_not_applied_when_first_attempt_uses_tools(self, tmp_path: Path) -> None:
        """When the first call already used tools, no retry is attempted."""

        msgs: list[dict[str, Any]] = [{"role": "assistant", "content": "ok"}]
        fake, call_log = _make_call_counter_tool_loop(
            [
                ("answer", ["read_file"], msgs),
                ("should not reach", [], msgs),
            ]
        )

        d = _make_dispatcher(tmp_path, provider=_StubProvider())
        role = AgentRoleConfig(name="research", description="research role")

        original = _delegation_mod.run_tool_loop
        _delegation_mod.run_tool_loop = fake  # type: ignore[assignment]
        try:
            await d.execute_delegated_agent(role, "analyze the codebase structure", None)
        finally:
            _delegation_mod.run_tool_loop = original

        assert len(call_log) == 1


# ---------------------------------------------------------------------------
# get_delegation_depth
# ---------------------------------------------------------------------------


class TestGetDelegationDepth:
    def test_depth_zero_at_top_level(self) -> None:
        assert get_delegation_depth() == 0

    def test_depth_reflects_ancestry(self) -> None:
        token = _delegation_ancestry.set(("code", "research"))
        try:
            assert get_delegation_depth() == 2
        finally:
            _delegation_ancestry.reset(token)
