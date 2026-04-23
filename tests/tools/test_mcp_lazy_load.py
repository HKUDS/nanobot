"""Tests for MCPProxyTool and MCP lazy-load wiring (Stage 2A)."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.tools.mcp import MCPProxyTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import ToolsConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_CFG = SimpleNamespace(
    type="stdio",
    command="echo",
    args=[],
    env=None,
    url=None,
    headers=None,
    tool_timeout=30,
    enabled_tools=["*"],
)


async def _noop_connect(name: str, cfg, registry: ToolRegistry):
    """Successful connect that registers one fake tool and returns a real stack."""
    from nanobot.agent.tools.base import Tool

    class _FakeTool(Tool):
        @property
        def name(self) -> str:
            return f"mcp_{name}_do_thing"

        @property
        def description(self) -> str:
            return "does a thing"

        @property
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}, "required": []}

        async def execute(self, **kwargs: Any) -> str:
            return "done"

    registry.register(_FakeTool())
    stack = AsyncExitStack()
    await stack.__aenter__()
    return name, stack


async def _fail_connect(name: str, cfg, registry: ToolRegistry):
    """Simulates a failed connection."""
    return name, None


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------


def test_proxy_name_format() -> None:
    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("github", _FAKE_CFG, registry, stacks)

    assert proxy.name == "mcp_github__proxy"


def test_proxy_description_mentions_server_and_args() -> None:
    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("github", _FAKE_CFG, registry, stacks)

    assert "github" in proxy.description
    assert "no arguments" in proxy.description.lower() or "arguments" in proxy.description.lower()


def test_proxy_has_no_required_parameters() -> None:
    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("github", _FAKE_CFG, registry, stacks)

    assert proxy.parameters["required"] == []
    assert proxy.parameters["properties"] == {}


# ---------------------------------------------------------------------------
# Execution — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_registers_real_tools_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.mcp as mcp_mod

    monkeypatch.setattr(mcp_mod, "connect_single_mcp_server", _noop_connect)

    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("myserver", _FAKE_CFG, registry, stacks)
    registry.register(proxy)

    result = await proxy.execute()

    assert "mcp_myserver_do_thing" in result
    assert "1" in result  # "Loaded 1 tool(s)"


@pytest.mark.asyncio
async def test_proxy_removes_itself_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.mcp as mcp_mod

    monkeypatch.setattr(mcp_mod, "connect_single_mcp_server", _noop_connect)

    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("myserver", _FAKE_CFG, registry, stacks)
    registry.register(proxy)

    await proxy.execute()

    assert not registry.has("mcp_myserver__proxy")


@pytest.mark.asyncio
async def test_proxy_stores_stack_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.mcp as mcp_mod

    monkeypatch.setattr(mcp_mod, "connect_single_mcp_server", _noop_connect)

    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("myserver", _FAKE_CFG, registry, stacks)
    registry.register(proxy)

    await proxy.execute()

    assert "myserver" in stacks
    assert isinstance(stacks["myserver"], AsyncExitStack)


# ---------------------------------------------------------------------------
# Execution — failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_stays_registered_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.mcp as mcp_mod

    monkeypatch.setattr(mcp_mod, "connect_single_mcp_server", _fail_connect)

    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("badserver", _FAKE_CFG, registry, stacks)
    registry.register(proxy)

    result = await proxy.execute()

    # Proxy must stay registered so the agent can retry.
    assert registry.has("mcp_badserver__proxy")
    # Result must start with "Error" so it won't be cached.
    assert result.startswith("Error")
    # No stack stored.
    assert "badserver" not in stacks


# ---------------------------------------------------------------------------
# Idempotency — calling the proxy again after successful load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_second_call_returns_already_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.mcp as mcp_mod

    call_count = 0

    async def _counting_connect(name, cfg, registry):
        nonlocal call_count
        call_count += 1
        return await _noop_connect(name, cfg, registry)

    monkeypatch.setattr(mcp_mod, "connect_single_mcp_server", _counting_connect)

    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("myserver", _FAKE_CFG, registry, stacks)
    registry.register(proxy)

    await proxy.execute()
    # Proxy unregistered itself; call directly (simulates second agent turn)
    result = await proxy.execute()

    assert call_count == 1  # connect called exactly once
    assert "already loaded" in result.lower()


# ---------------------------------------------------------------------------
# Concurrent execution — only one connect fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_concurrent_calls_connect_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.mcp as mcp_mod

    call_count = 0

    async def _slow_connect(name, cfg, registry):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)  # yield to let the second coroutine start
        return await _noop_connect(name, cfg, registry)

    monkeypatch.setattr(mcp_mod, "connect_single_mcp_server", _slow_connect)

    registry = ToolRegistry()
    stacks: dict = {}
    proxy = MCPProxyTool("myserver", _FAKE_CFG, registry, stacks)
    registry.register(proxy)

    # Fire two concurrent calls
    results = await asyncio.gather(proxy.execute(), proxy.execute())

    assert call_count == 1
    # One result is the "loaded" message, the other is "already loaded"
    combined = " ".join(results)
    assert "loaded" in combined.lower()


# ---------------------------------------------------------------------------
# Config — mcp_lazy_load field
# ---------------------------------------------------------------------------


def test_tools_config_mcp_lazy_load_defaults_false() -> None:
    cfg = ToolsConfig()
    assert cfg.mcp_lazy_load is False


def test_tools_config_mcp_lazy_load_camel_case() -> None:
    cfg = ToolsConfig.model_validate({"mcpLazyLoad": True})
    assert cfg.mcp_lazy_load is True


def test_tools_config_mcp_lazy_load_snake_case() -> None:
    cfg = ToolsConfig.model_validate({"mcp_lazy_load": True})
    assert cfg.mcp_lazy_load is True
