from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class _FakeTool(Tool):
    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return kwargs


def _tool_names(definitions: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for definition in definitions:
        fn = definition.get("function", {})
        names.append(fn.get("name", ""))
    return names


def test_get_definitions_orders_builtins_then_mcp_tools() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("mcp_git_status"))
    registry.register(_FakeTool("write_file"))
    registry.register(_FakeTool("mcp_fs_list"))
    registry.register(_FakeTool("read_file"))

    assert _tool_names(registry.get_definitions()) == [
        "read_file",
        "write_file",
        "mcp_fs_list",
        "mcp_git_status",
    ]


def test_prepare_call_read_file_rejects_non_object_params_with_actionable_hint() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    tool, params, error = registry.prepare_call("read_file", ["foo.txt"])

    assert tool is None
    assert params == ["foo.txt"]
    assert error is not None
    assert "must be a JSON object" in error
    assert "Use named parameters" in error


def test_prepare_call_other_tools_keep_generic_object_validation() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("grep"))

    tool, params, error = registry.prepare_call("grep", ["TODO"])

    assert tool is not None
    assert params == ["TODO"]
    assert error == "Error: Invalid parameters for tool 'grep': parameters must be an object, got list"


def test_get_definitions_returns_cached_result() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    assert registry._cached_definitions is not None
    second = registry.get_definitions()
    assert first == second


def test_register_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    registry.register(_FakeTool("write_file"))
    second = registry.get_definitions()
    assert first is not second
    assert len(second) == 2


def test_unregister_invalidates_cache() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    registry.register(_FakeTool("write_file"))
    first = registry.get_definitions()
    registry.unregister("write_file")
    second = registry.get_definitions()
    assert first is not second
    assert len(second) == 1


# ---------------------------------------------------------------------------
# Secret redaction (MIT-122)
#
# ToolRegistry.execute() must scrub embedded secrets from string results so
# that, even if a misbehaving or adversarial tool pulls a private key or API
# token into its output, the model never gets to see it. Non-string results
# (e.g. ReadFileTool returning a list of multimodal image blocks) must pass
# through untouched.
# ---------------------------------------------------------------------------


class _StringReturningTool(Tool):
    """Fake tool that returns a caller-supplied string verbatim."""

    def __init__(self, name: str, payload: str):
        self._name = name
        self._payload = payload

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return self._payload


class _ListReturningTool(Tool):
    """Fake tool that returns a list result (mimics ReadFileTool for images)."""

    def __init__(self, name: str, payload: list[dict[str, Any]]):
        self._name = name
        self._payload = payload

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> Any:
        return self._payload


@pytest.mark.asyncio
async def test_execute_redacts_private_key_in_output() -> None:
    payload = (
        "Here are some notes:\n"
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAy3... (truncated)\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    registry = ToolRegistry()
    registry.register(_StringReturningTool("leaky", payload))

    result = await registry.execute("leaky", {})

    assert "BEGIN RSA PRIVATE KEY" not in result
    assert "REDACTED" in result
    assert "security policy" in result.lower()


@pytest.mark.asyncio
async def test_execute_redacts_aws_access_key() -> None:
    payload = "export AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n"
    registry = ToolRegistry()
    registry.register(_StringReturningTool("leaky", payload))

    result = await registry.execute("leaky", {})

    assert "AKIAABCDEFGHIJKLMNOP" not in result
    assert "REDACTED" in result


@pytest.mark.asyncio
async def test_execute_redacts_github_token() -> None:
    payload = "Authorization: token ghp_0123456789abcdef0123456789abcdef0123\n"
    registry = ToolRegistry()
    registry.register(_StringReturningTool("leaky", payload))

    result = await registry.execute("leaky", {})

    assert "ghp_0123456789abcdef0123456789abcdef0123" not in result
    assert "REDACTED" in result


@pytest.mark.asyncio
async def test_execute_passes_clean_output_unchanged() -> None:
    payload = "hello, world — no secrets here"
    registry = ToolRegistry()
    registry.register(_StringReturningTool("clean", payload))

    result = await registry.execute("clean", {})

    assert result == payload


@pytest.mark.asyncio
async def test_execute_does_not_touch_list_results() -> None:
    """Non-string results (image blocks from ReadFileTool) must pass through."""
    image_blocks: list[dict[str, Any]] = [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,AAAA"},
            "_meta": {"path": "/tmp/pixel.png"},
        },
        {"type": "text", "text": "(Image file: /tmp/pixel.png)"},
    ]
    registry = ToolRegistry()
    registry.register(_ListReturningTool("read_file", image_blocks))

    result = await registry.execute("read_file", {})

    # Identity — the list must flow through untouched, not stringified.
    assert result is image_blocks
    assert isinstance(result, list)
    assert result[0]["image_url"]["url"] == "data:image/png;base64,AAAA"


@pytest.mark.asyncio
async def test_execute_does_not_redact_error_output() -> None:
    """Error outputs are short-circuited before the redactor runs.

    Error strings are safe by construction (they come from our own error
    builders) and we want them to reach the model verbatim so it can react.
    """
    registry = ToolRegistry()
    registry.register(_StringReturningTool("boom", "Error: something bad"))

    result = await registry.execute("boom", {})

    assert result.startswith("Error: something bad")
