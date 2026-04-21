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
