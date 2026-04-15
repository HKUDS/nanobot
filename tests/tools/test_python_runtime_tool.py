from __future__ import annotations

import pytest

from nanobot.agent.tools.python_runtime import PythonRuntimeTool
from nanobot.config.schema import SecurityRulesConfig


class TestSecurityConfigIntegration:
    @pytest.fixture()
    def tool(self):
        return PythonRuntimeTool(
            security_config=SecurityRulesConfig(blocked_imports=["os"]),
        )

    @pytest.mark.asyncio
    async def test_security_config_builds_rules(self, tool):
        assert tool._security_rules is not None
        from cave_agent.security import ImportRule

        assert any(isinstance(r, ImportRule) for r in tool._security_rules)

    @pytest.mark.asyncio
    async def test_security_config_empty_when_rules_provided(self):
        from cave_agent.security import ImportRule

        existing_rule = ImportRule(forbidden_modules={"sys"})
        tool = PythonRuntimeTool(
            security_rules=[existing_rule],
            security_config=SecurityRulesConfig(blocked_imports=["os"]),
        )
        assert tool._security_rules == [existing_rule]
        assert len(tool._security_rules) == 1

    @pytest.mark.asyncio
    async def test_security_config_blocked_import_enforced(self, tool):
        result = await tool.execute(code="import os")
        assert "Error" in result or "blocked" in result.lower() or "security" in result.lower()


class TestCleanup:
    @pytest.fixture()
    def tool(self):
        return PythonRuntimeTool()

    @pytest.mark.asyncio
    async def test_cleanup_resets_runtime(self, tool):
        await tool.execute(code="x = 42")
        assert tool._runtime is not None
        assert tool._started is True

        await tool.cleanup()

        assert tool._runtime is None
        assert tool._started is False

    @pytest.mark.asyncio
    async def test_cleanup_idempotent(self, tool):
        await tool.execute(code="x = 1")
        await tool.cleanup()
        await tool.cleanup()

        assert tool._runtime is None

    @pytest.mark.asyncio
    async def test_cleanup_on_fresh_tool(self, tool):
        await tool.cleanup()

        assert tool._runtime is None
        assert tool._started is False


class TestErrorRecovery:
    @pytest.fixture()
    def tool(self):
        return PythonRuntimeTool()

    @pytest.mark.asyncio
    async def test_execute_survives_runtime_error(self, tool):
        result = await tool.execute(code="1/0")
        assert "Error" in result

        result2 = await tool.execute(code="print('alive')")
        assert "alive" in result2

    @pytest.mark.asyncio
    async def test_is_runtime_dead_returns_false_for_healthy(self, tool):
        await tool.execute(code="x = 1")
        dead = await tool._is_runtime_dead()
        assert dead is False

    @pytest.mark.asyncio
    async def test_is_runtime_dead_returns_true_for_none(self, tool):
        assert tool._runtime is None
        dead = await tool._is_runtime_dead()
        assert dead is True


class TestInjectionPersistenceAcrossReset:
    @pytest.fixture()
    def tool(self):
        return PythonRuntimeTool()

    @pytest.mark.asyncio
    async def test_injections_persist_after_reset(self, tool):
        tool.inject_variable("my_var", 99, "test variable")
        await tool.execute(code="print(my_var)")

        await tool.reset()

        assert tool._inject_variables
        assert any(v["name"] == "my_var" for v in tool._inject_variables)

    @pytest.mark.asyncio
    async def test_injections_reapplied_on_restart(self, tool):
        tool.inject_variable("my_var", 99, "test variable")
        await tool.execute(code="print(my_var)")

        tool._runtime = None
        tool._started = False

        result = await tool.execute(code="print(my_var)")
        assert "99" in result


class TestToolSchema:
    @pytest.fixture()
    def tool(self):
        return PythonRuntimeTool()

    def test_tool_schema_valid(self, tool):
        schema = tool.parameters
        assert tool.name == "python"
        assert "code" in schema["required"]
        assert "code" in schema["properties"]


class TestExecutionTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        tool = PythonRuntimeTool(timeout=1)
        result = await tool.execute(code="import asyncio; await asyncio.sleep(10)")
        assert (
            "timed out" in result.lower()
            or "timeout" in result.lower()
            or "error" in result.lower()
        )


class TestDescribeNamespaceBudget:
    @pytest.mark.asyncio
    async def test_namespace_description_truncation(self):
        tool = PythonRuntimeTool()
        for i in range(20):
            tool.inject_variable(
                f"var_{i}", i, f"this is a test variable number {i} with extra detail"
            )
        await tool.execute(code="pass")
        desc = tool.describe_namespace(max_chars=50)
        assert "truncated" in desc.lower()


class TestOutputTruncation:
    @pytest.mark.asyncio
    async def test_large_output_truncated(self):
        tool = PythonRuntimeTool(max_output_chars=100)
        result = await tool.execute(code="print('x' * 20000)")
        assert "truncated" in result.lower()
        assert len(result) < 20000


class TestRetrieveMethod:
    @pytest.mark.asyncio
    async def test_retrieve_variable(self):
        tool = PythonRuntimeTool()
        tool.inject_variable("counter", 0, "a counter")
        await tool.execute(code="counter += 42")
        value = await tool.retrieve("counter")
        assert value == 42


class TestAutoRestart:
    @pytest.mark.asyncio
    async def test_execute_restarts_dead_runtime(self):
        tool = PythonRuntimeTool()
        # First execute to start the runtime
        result1 = await tool.execute(code="x = 1")
        assert tool._runtime is not None

        # Simulate a dead runtime
        tool._runtime = None
        tool._started = False

        # Next execute should auto-restart
        result2 = await tool.execute(code="print('restarted')")
        assert "restarted" in result2
        assert tool._runtime is not None
