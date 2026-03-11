"""Tests for nanobot.agent.delegation — DelegationDispatcher unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.agent.delegation import (
    TASK_TYPES,
    DelegationDispatcher,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dispatcher(tmp_path: Path, **overrides: Any) -> DelegationDispatcher:
    defaults = dict(
        provider=None,
        workspace=tmp_path,
        model="test-model",
        temperature=0.7,
        max_tokens=4096,
        max_iterations=5,
        restrict_to_workspace=True,
        brave_api_key=None,
        exec_config=None,
        role_name="main",
        trace_path=tmp_path / "trace.jsonl",
    )
    defaults.update(overrides)
    return DelegationDispatcher(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        assert d.delegation_count == 0
        assert d.max_delegations == 8
        assert d.routing_trace == []
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

    def test_writes_jsonl_file(self, tmp_path: Path):
        trace_path = tmp_path / "traces" / "routing.jsonl"
        d = _make_dispatcher(tmp_path, trace_path=trace_path)
        d.record_route_trace("delegate", role="code")
        assert trace_path.exists()
        data = json.loads(trace_path.read_text().strip())
        assert data["event"] == "delegate"

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
            {"role": "tool", "name": f"t{i}", "content": f"result {i}"}
            for i in range(20)
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

    def test_task_types_dict_complete(self):
        """All expected task types exist in TASK_TYPES."""
        expected = {
            "local_code_analysis", "repo_architecture", "web_research",
            "report_writing", "bug_investigation", "general",
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
        assert not DelegationDispatcher.has_parallel_structure(
            "Review the code for bugs"
        )


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
        content, _ = d.build_delegation_contract(
            "code", "task", "extra context here", "general"
        )
        assert "extra context here" in content

    def test_contract_includes_tool_guidance(self, tmp_path: Path):
        d = _make_dispatcher(tmp_path)
        d.active_messages = []
        content, _ = d.build_delegation_contract(
            "code", "analyze code", None, "local_code_analysis"
        )
        assert "Preferred tools" in content
