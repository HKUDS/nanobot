from __future__ import annotations

import pytest

from nanobot.agent.tools.python_runtime import (
    PythonDescribeTool,
    PythonExecuteTool,
    PythonResetTool,
    PythonRuntimeManager,
    PythonRuntimeTool,
)
from nanobot.config.schema import SecurityRulesConfig


def _make_manager(**kwargs) -> PythonRuntimeManager:
    return PythonRuntimeManager(**kwargs)


# ---------------------------------------------------------------------------
# Security config integration
# ---------------------------------------------------------------------------


class TestSecurityConfigIntegration:
    @pytest.fixture()
    def mgr(self):
        return _make_manager(security_config=SecurityRulesConfig(blocked_imports=["os"]))

    @pytest.mark.asyncio
    async def test_security_config_builds_rules(self, mgr):
        assert mgr._security_rules is not None
        from cave_agent.security import ImportRule

        assert any(isinstance(r, ImportRule) for r in mgr._security_rules)

    @pytest.mark.asyncio
    async def test_security_config_empty_when_rules_provided(self):
        from cave_agent.security import ImportRule

        existing_rule = ImportRule(forbidden_modules={"sys"})
        mgr = _make_manager(
            security_rules=[existing_rule],
            security_config=SecurityRulesConfig(blocked_imports=["os"]),
        )
        assert mgr._security_rules == [existing_rule]
        assert len(mgr._security_rules) == 1

    @pytest.mark.asyncio
    async def test_security_config_blocked_import_enforced(self, mgr):
        tool = PythonExecuteTool(manager=mgr)
        result = await tool.execute(code="import os")
        assert "Error" in result or "blocked" in result.lower() or "security" in result.lower()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    @pytest.fixture()
    def mgr(self):
        return _make_manager()

    @pytest.mark.asyncio
    async def test_cleanup_resets_runtime(self, mgr):
        await mgr.execute("x = 42")
        assert mgr._runtime is not None
        assert mgr._started is True

        await mgr.cleanup()

        assert mgr._runtime is None
        assert mgr._started is False

    @pytest.mark.asyncio
    async def test_cleanup_idempotent(self, mgr):
        await mgr.execute("x = 1")
        await mgr.cleanup()
        await mgr.cleanup()

        assert mgr._runtime is None

    @pytest.mark.asyncio
    async def test_cleanup_on_fresh_manager(self, mgr):
        await mgr.cleanup()

        assert mgr._runtime is None
        assert mgr._started is False


# ---------------------------------------------------------------------------
# Error recovery
# ---------------------------------------------------------------------------


class TestErrorRecovery:
    @pytest.fixture()
    def mgr(self):
        return _make_manager()

    @pytest.mark.asyncio
    async def test_execute_survives_runtime_error(self, mgr):
        tool = PythonExecuteTool(manager=mgr)
        result = await tool.execute(code="1/0")
        assert "Error" in result

        result2 = await tool.execute(code="print('alive')")
        assert "alive" in result2

    @pytest.mark.asyncio
    async def test_is_runtime_dead_returns_false_for_healthy(self, mgr):
        await mgr.execute("x = 1")
        dead = await mgr._is_runtime_dead()
        assert dead is False

    @pytest.mark.asyncio
    async def test_is_runtime_dead_returns_true_for_none(self, mgr):
        assert mgr._runtime is None
        dead = await mgr._is_runtime_dead()
        assert dead is True


# ---------------------------------------------------------------------------
# Injection persistence across reset
# ---------------------------------------------------------------------------


class TestInjectionPersistenceAcrossReset:
    @pytest.fixture()
    def mgr(self):
        return _make_manager()

    @pytest.mark.asyncio
    async def test_injections_persist_after_reset(self, mgr):
        mgr.inject_variable("my_var", 99, "test variable")
        await mgr.execute("print(my_var)")

        await mgr.reset()

        assert mgr._inject_variables
        assert any(v["name"] == "my_var" for v in mgr._inject_variables)

    @pytest.mark.asyncio
    async def test_injections_reapplied_on_restart(self, mgr):
        mgr.inject_variable("my_var", 99, "test variable")
        await mgr.execute("print(my_var)")

        mgr._runtime = None
        mgr._started = False

        result = await mgr.execute("print(my_var)")
        assert "99" in result


# ---------------------------------------------------------------------------
# Tool schema
# ---------------------------------------------------------------------------


class TestToolSchema:
    @pytest.fixture()
    def mgr(self):
        return _make_manager()

    def test_execute_tool_schema_valid(self, mgr):
        tool = PythonExecuteTool(manager=mgr)
        schema = tool.parameters
        assert tool.name == "python"
        assert "code" in schema["required"]
        assert "code" in schema["properties"]

    def test_reset_tool_schema_valid(self, mgr):
        tool = PythonResetTool(manager=mgr)
        assert tool.name == "python_reset"
        assert tool.parameters["properties"] == {}

    def test_describe_tool_schema_valid(self, mgr):
        tool = PythonDescribeTool(manager=mgr)
        assert tool.name == "python_describe"
        assert tool.parameters["properties"] == {}


# ---------------------------------------------------------------------------
# Execution timeout
# ---------------------------------------------------------------------------


class TestExecutionTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        mgr = _make_manager(timeout=1)
        tool = PythonExecuteTool(manager=mgr)
        result = await tool.execute(code="import asyncio; await asyncio.sleep(10)")
        assert (
            "timed out" in result.lower()
            or "timeout" in result.lower()
            or "error" in result.lower()
        )


# ---------------------------------------------------------------------------
# Describe namespace budget
# ---------------------------------------------------------------------------


class TestDescribeNamespaceBudget:
    @pytest.mark.asyncio
    async def test_namespace_description_truncation(self):
        mgr = _make_manager()
        for i in range(20):
            mgr.inject_variable(
                f"var_{i}", i, f"this is a test variable number {i} with extra detail"
            )
        await mgr.execute("pass")
        desc = mgr.describe_namespace(max_chars=50)
        assert "truncated" in desc.lower()


# ---------------------------------------------------------------------------
# Output truncation
# ---------------------------------------------------------------------------


class TestOutputTruncation:
    @pytest.mark.asyncio
    async def test_large_output_truncated(self):
        mgr = _make_manager(max_output_chars=100)
        tool = PythonExecuteTool(manager=mgr)
        result = await tool.execute(code="print('x' * 20000)")
        assert "truncated" in result.lower()
        assert len(result) < 20000


# ---------------------------------------------------------------------------
# Retrieve method
# ---------------------------------------------------------------------------


class TestRetrieveMethod:
    @pytest.mark.asyncio
    async def test_retrieve_variable(self):
        mgr = _make_manager()
        mgr.inject_variable("counter", 0, "a counter")
        await mgr.execute("counter += 42")
        value = await mgr.retrieve("counter")
        assert value == 42


# ---------------------------------------------------------------------------
# Auto restart
# ---------------------------------------------------------------------------


class TestAutoRestart:
    @pytest.mark.asyncio
    async def test_execute_restarts_dead_runtime(self):
        mgr = _make_manager()
        tool = PythonExecuteTool(manager=mgr)
        result1 = await tool.execute(code="x = 1")
        assert mgr._runtime is not None

        mgr._runtime = None
        mgr._started = False

        result2 = await tool.execute(code="print('restarted')")
        assert "restarted" in result2
        assert mgr._runtime is not None


# ---------------------------------------------------------------------------
# PythonResetTool
# ---------------------------------------------------------------------------


class TestPythonResetTool:
    @pytest.mark.asyncio
    async def test_reset_clears_variables(self):
        mgr = _make_manager()
        tool = PythonExecuteTool(manager=mgr)
        await tool.execute(code="x = 42")

        reset_tool = PythonResetTool(manager=mgr)
        result = await reset_tool.execute()
        assert "reset" in result.lower()

        result2 = await tool.execute(code="print(x)")
        assert "Error" in result2 or "NameError" in result2


# ---------------------------------------------------------------------------
# PythonDescribeTool
# ---------------------------------------------------------------------------


class TestPythonDescribeTool:
    @pytest.mark.asyncio
    async def test_describe_shows_namespace(self):
        mgr = _make_manager()
        mgr.inject_variable("data", [1, 2, 3], "test data")
        await mgr.execute("pass")

        desc_tool = PythonDescribeTool(manager=mgr)
        result = await desc_tool.execute()
        assert "data" in result
        assert "list" in result

    @pytest.mark.asyncio
    async def test_describe_empty_namespace(self):
        mgr = _make_manager()

        desc_tool = PythonDescribeTool(manager=mgr)
        result = await desc_tool.execute()
        assert "Empty namespace" in result


# ---------------------------------------------------------------------------
# Dynamic description on PythonExecuteTool
# ---------------------------------------------------------------------------


class TestDynamicDescription:
    @pytest.mark.asyncio
    async def test_description_includes_namespace(self):
        mgr = _make_manager()
        mgr.inject_variable("my_data", {"key": "value"}, "some data")
        tool = PythonExecuteTool(manager=mgr)

        desc = tool.description
        assert "namespace" in desc.lower()
        assert "my_data" in desc

    def test_description_without_namespace(self):
        mgr = _make_manager()
        tool = PythonExecuteTool(manager=mgr)

        desc = tool.description
        assert "STATEFUL" in desc
        assert "namespace" not in desc.lower()


# ---------------------------------------------------------------------------
# Backward compatibility: PythonRuntimeTool
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_runtime_tool_is_execute_tool(self):
        tool = PythonRuntimeTool()
        assert isinstance(tool, PythonExecuteTool)
        assert tool.name == "python"

    def test_runtime_tool_accepts_old_constructor(self):
        tool = PythonRuntimeTool(
            backend="ipython",
            max_output_chars=5000,
            security_config=SecurityRulesConfig(blocked_imports=["os"]),
        )
        assert tool._runtime_manager._max_output == 5000
