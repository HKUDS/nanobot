"""Tests for ExecTool env_strip, per-call timeout, and max_output_chars."""

import os

import pytest

from nanobot.agent.tools.shell import ExecTool


class TestEnvStrip:
    @pytest.mark.asyncio
    async def test_env_strip_removes_keys(self):
        """API keys listed in env_strip must not leak to child processes."""
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-secret"
        try:
            tool = ExecTool(env_strip=["ANTHROPIC_API_KEY"])
            result = await tool.execute("echo $ANTHROPIC_API_KEY")
            assert "sk-test-secret" not in result
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

    @pytest.mark.asyncio
    async def test_env_strip_empty_preserves_env(self):
        """An empty env_strip list should not remove any variables."""
        os.environ["TEST_NANOBOT_VAR"] = "keep-me"
        try:
            tool = ExecTool(env_strip=[])
            result = await tool.execute("echo $TEST_NANOBOT_VAR")
            assert "keep-me" in result
        finally:
            os.environ.pop("TEST_NANOBOT_VAR", None)


class TestPerCallTimeout:
    @pytest.mark.asyncio
    async def test_per_call_timeout_overrides_default(self):
        """A per-call timeout should override the instance default."""
        tool = ExecTool(timeout=60)
        # sleep 5 with a 1-second per-call timeout should time out
        result = await tool.execute("sleep 5", timeout=1)
        assert "timed out" in result
        assert "1 seconds" in result

    @pytest.mark.asyncio
    async def test_per_call_timeout_fallback_to_default(self):
        """Without per-call timeout, the instance default is used."""
        tool = ExecTool(timeout=1)
        result = await tool.execute("sleep 5")
        assert "timed out" in result
        assert "1 seconds" in result

    @pytest.mark.asyncio
    async def test_per_call_timeout_succeeds_within_limit(self):
        """A fast command should succeed with a generous per-call timeout."""
        tool = ExecTool(timeout=1)  # tight default
        result = await tool.execute("echo ok", timeout=10)
        assert "ok" in result
        assert "timed out" not in result

    def test_timeout_parameter_in_schema(self):
        """The timeout parameter should be exposed in the JSON schema."""
        tool = ExecTool()
        props = tool.parameters["properties"]
        assert "timeout" in props
        assert props["timeout"]["type"] == "integer"
        assert props["timeout"]["minimum"] == 1
        assert props["timeout"]["maximum"] == 1800

    def test_timeout_validation_rejects_out_of_range(self):
        """Parameter validation should reject timeout outside [1, 1800]."""
        tool = ExecTool()
        errors = tool.validate_params({"command": "echo hi", "timeout": 0})
        assert any("must be >= 1" in e for e in errors)
        errors = tool.validate_params({"command": "echo hi", "timeout": 9999})
        assert any("must be <= 1800" in e for e in errors)


class TestMaxOutputChars:
    @pytest.mark.asyncio
    async def test_max_output_chars_truncation(self):
        """Output exceeding max_output_chars must be truncated."""
        tool = ExecTool(max_output_chars=50)
        result = await tool.execute("python3 -c \"print('A' * 200)\"")
        assert "truncated" in result
        assert len(result.split("\n... (truncated")[0]) <= 50

    @pytest.mark.asyncio
    async def test_max_output_chars_no_truncation(self):
        """Short output should not be truncated."""
        tool = ExecTool(max_output_chars=10000)
        result = await tool.execute("echo hello")
        assert "truncated" not in result
        assert "hello" in result
