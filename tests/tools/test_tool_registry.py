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


# ---------------------------------------------------------------------------
# Parameter-type validation for read_file / write_file — originally covered
# by `registry.prepare_call(...)` (removed in commit 1d18d24 when the
# timing/audit wrapper in `execute()` absorbed `prepare_call`).  The
# semantic contract still holds through `execute()`, so the tests are
# re-targeted there to keep the coverage.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_read_file_rejects_non_object_params_with_actionable_hint() -> None:
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))

    result = await registry.execute("read_file", ["foo.txt"])

    assert "must be a JSON object" in result
    assert "Use named parameters" in result


@pytest.mark.asyncio
async def test_execute_other_tools_keep_generic_object_validation() -> None:
    """Non read_file/write_file tools still flow through the generic
    `validate_params` path and get the generic error message."""
    registry = ToolRegistry()
    registry.register(_FakeTool("grep"))

    result = await registry.execute("grep", ["TODO"])

    # The specific 'JSON object' hint is reserved for read_file/write_file.
    assert "must be a JSON object" not in result
    # And the generic validator's error surfaces instead.
    assert "Invalid parameters for tool 'grep'" in result


# ---------------------------------------------------------------------------
# Cache behaviour for get_definitions().  The internal attribute was
# renamed `_cached_definitions` -> `_definitions_cache` in commit 1d18d24,
# so the old test that poked at the attribute by its old name is removed.
# The observable contract — same list instance across calls, fresh list
# after mutation — is kept via the two invalidation tests below.
# ---------------------------------------------------------------------------


def test_get_definitions_is_cached_between_calls() -> None:
    """Back-to-back calls return the same list instance (stable ordering
    cache, no resorting)."""
    registry = ToolRegistry()
    registry.register(_FakeTool("read_file"))
    first = registry.get_definitions()
    second = registry.get_definitions()
    assert first is second


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


class _AnyReturningTool(Tool):
    """Fake tool that returns an arbitrary non-string payload verbatim."""

    def __init__(self, name: str, payload: Any):
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
async def test_execute_passes_structured_payload_containing_secret_string_unchanged() -> None:
    """Document string-only redaction scope: nested structured payloads pass through.

    Current behavior is string-only redaction; `ToolRegistry.execute()` guards the
    scrubber with `isinstance(result, str)`, so dict/list results flow through
    untouched even when they embed secret-looking strings in nested fields. This
    is intentional today (image blocks from ReadFileTool are list[dict]), but it
    is a known scope limit: if a future tool returns user-facing text in a nested
    field, consider recursive scanning (tracked separately, unticketed).

    This test is a regression guard + scope-documentation test, not a fix.
    """
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAy3... (truncated)\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    # Nested dict (simulating a future tool that returns structured output)
    dict_payload: dict[str, Any] = {"content": pem, "meta": {"path": "/tmp/key.pem"}}
    registry = ToolRegistry()
    registry.register(_AnyReturningTool("structured_dict", dict_payload))

    result = await registry.execute("structured_dict", {})

    # Pass-through: the dict flows through untouched, secret string still present.
    assert result is dict_payload
    assert isinstance(result, dict)
    assert "BEGIN RSA PRIVATE KEY" in result["content"]
    assert "REDACTED" not in result["content"]

    # Same contract for a list of dicts with a nested secret string.
    list_payload: list[dict[str, Any]] = [
        {"type": "text", "text": "Authorization: token ghp_0123456789abcdef0123456789abcdef0123"},
    ]
    registry2 = ToolRegistry()
    registry2.register(_AnyReturningTool("structured_list", list_payload))

    result2 = await registry2.execute("structured_list", {})

    assert result2 is list_payload
    assert isinstance(result2, list)
    assert "ghp_0123456789abcdef0123456789abcdef0123" in result2[0]["text"]
