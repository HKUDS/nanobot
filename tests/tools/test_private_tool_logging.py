"""Synthetic privacy regressions for tool diagnostics, without external requests."""

import asyncio
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from agent.runner_helpers import make_run_spec
from loguru import logger
from mcp import types
from mcp.shared.exceptions import McpError

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.context import (
    RequestContext,
    request_context,
    tool_log_content_allowed,
)
from nanobot.agent.tools.execution import _classify_violation, execute_tool_calls
from nanobot.agent.tools.mcp import (
    MCPPromptWrapper,
    MCPProvider,
    MCPResourceWrapper,
    MCPToolWrapper,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool, _redact_url_for_log
from nanobot.agent.turn_hooks import AgentTurnHookSpec, build_agent_turn_hook
from nanobot.config.schema import MCPServerConfig, WebSearchConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_SECRET = "synthetic-private-detail"


@pytest.mark.parametrize("log_content", [True, False])
@pytest.mark.parametrize("transient", [True, False])
async def test_mcp_reconnect_failure_obeys_private_log_policy(
    log_content, transient, monkeypatch, diagnostic_records,
):
    @asynccontextmanager
    async def broken_stdio(_params):
        if transient:
            raise ConnectionResetError(_SECRET)
        raise RuntimeError(_SECRET)
        yield  # pragma: no cover

    monkeypatch.setattr("mcp.client.stdio.stdio_client", broken_stdio)
    session = SimpleNamespace(call_tool=AsyncMock(side_effect=RuntimeError("session terminated")))
    wrapper = MCPToolWrapper(session, "sample", SimpleNamespace(
        name="search", description="synthetic", inputSchema={},
    ))
    registry = ToolRegistry()
    registry.register(wrapper)
    provider = MCPProvider({"sample": MCPServerConfig(command="synthetic-mcp")}, registry)
    provider._attach_reconnect_handlers({"sample"})
    try:
        with request_context(RequestContext(channel="websocket", chat_id="test", log_content=log_content)):
            result = await wrapper.execute(query=_SECRET)
    finally:
        await provider.aclose()

    assert "failed" in result
    failures = [
        r for r in diagnostic_records
        if "connection failure" in r["message"] or "failed to connect" in r["message"]
    ]
    assert failures
    assert any(r["exception"] is not None for r in failures) is log_content


@pytest.mark.parametrize("log_content", [True, False])
@pytest.mark.parametrize("kind", ["injection", "continuation", "finalization", "finally"])
async def test_runner_recovery_diagnostics_obey_private_policy(log_content, kind, diagnostic_records):
    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="done"))
    spec = make_run_spec(
        provider, model="test-model", initial_messages=[{"role": "user", "content": _SECRET}],
        tools=ToolRegistry(), max_iterations=1, max_tool_result_chars=100,
    )
    if kind == "injection":
        spec.injection_callback = AsyncMock(side_effect=ValueError(_SECRET))
    elif kind == "continuation":
        spec.continuation_callback = MagicMock(side_effect=ValueError(_SECRET))
    elif kind == "finalization":
        spec.max_iterations = 0
        provider.chat_stream_with_retry = AsyncMock(side_effect=ValueError(_SECRET))
    else:
        class BrokenFinallyHook(AgentHook):
            async def before_run(self, context):
                raise ValueError(_SECRET)

            async def on_finally(self, context):
                raise RuntimeError("synthetic cleanup failure")

        spec.hook = BrokenFinallyHook()

    with request_context(RequestContext(channel="websocket", chat_id="test", log_content=log_content)):
        if kind == "finally":
            with pytest.raises(ValueError, match=_SECRET):
                await AgentRunner().run(spec)
        else:
            await AgentRunner().run(spec)
    errors = [r for r in diagnostic_records if r["level"].name == "ERROR"]
    assert errors
    assert all((r["exception"] is not None) is log_content for r in errors)


@pytest.fixture
def diagnostic_records():
    records = []
    sink = logger.add(lambda message: records.append(message.record), format="{message}")
    try:
        yield records
    finally:
        logger.remove(sink)


@pytest.mark.parametrize("log_content", [True, False])
@pytest.mark.parametrize("kind", ["tool", "resource", "prompt", "prompt_error", "render", "retry"])
async def test_mcp_private_errors_exclude_exception_payloads(
    log_content, kind, monkeypatch, diagnostic_records,
):
    session = MagicMock()
    definition = SimpleNamespace(name="sample", description="sample", inputSchema={})
    error = ValueError(_SECRET)
    if kind in {"tool", "render", "retry"}:
        tool = MCPToolWrapper(session, "test", definition)
        if kind == "render":
            session.call_tool = AsyncMock(return_value=SimpleNamespace(content=[]))
            monkeypatch.setattr(tool, "_render_call_result", MagicMock(side_effect=error))
        else:
            if kind == "retry":
                error = ConnectionResetError(_SECRET)
                monkeypatch.setattr("nanobot.agent.tools.mcp.asyncio.sleep", AsyncMock())
            session.call_tool = AsyncMock(side_effect=error)
    elif kind == "resource":
        tool = MCPResourceWrapper(session, "test", types.Resource(
            name="sample", uri="https://example.test/resource",
        ))
        session.read_resource = AsyncMock(side_effect=error)
    else:
        tool = MCPPromptWrapper(session, "test", types.Prompt(name="sample"))
        if kind == "prompt_error":
            error = McpError(types.ErrorData(code=-32602, message=_SECRET))
        session.get_prompt = AsyncMock(side_effect=error)

    with request_context(RequestContext(channel="websocket", chat_id="test", log_content=log_content)):
        result = await tool.execute()
    assert "failed" in result or "malformed" in result
    errors = [r for r in diagnostic_records if r["level"].name == "ERROR"]
    assert errors
    if log_content:
        assert errors[-1]["exception"] is not None
    else:
        assert all(r["exception"] is None for r in diagnostic_records)
        assert _SECRET not in str([r["message"] for r in diagnostic_records])


@pytest.mark.parametrize("log_content", [True, False])
@pytest.mark.parametrize("kind", ["fetch", "jina", "duckduckgo", "ssrf"])
async def test_web_private_diagnostics_keep_error_category_not_content(
    log_content, kind, monkeypatch, diagnostic_records,
):
    url = f"https://{_SECRET}.example/path?query={_SECRET}"
    error = RuntimeError(url)
    with request_context(RequestContext(channel="websocket", chat_id="test", log_content=log_content)):
        if kind == "fetch":
            monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", MagicMock(side_effect=error))
            result = await WebFetchTool()._fetch_readability(url, "text", 100)
            assert url in result
        elif kind == "jina":
            tool = WebSearchTool(config=WebSearchConfig(provider="jina", api_key="synthetic"))
            monkeypatch.setattr("nanobot.agent.tools.web.httpx.AsyncClient", MagicMock(side_effect=error))
            monkeypatch.setattr(tool, "_search_duckduckgo", AsyncMock(return_value="fallback"))
            assert await tool._search_jina(_SECRET, 1) == "fallback"
        elif kind == "duckduckgo":
            monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=MagicMock(side_effect=error)))
            result = await WebSearchTool()._search_duckduckgo(_SECRET, 1)
            assert _SECRET in result
        else:
            raw = f"Error: private/internal address {url}"
            result = _classify_violation(
                raw_text=raw, soft_payload=raw, event={},
                tool_call=ToolCallRequest(id="test", name="web_fetch", arguments={"url": url}),
                workspace_violation_counts={},
            )
            assert result is not None and url in result[0]
    assert diagnostic_records
    assert (_SECRET in str([r["message"] for r in diagnostic_records])) is log_content


async def test_private_logging_policy_is_task_local_and_restored():
    private_started = asyncio.Event()
    ordinary_started = asyncio.Event()

    async def private():
        with request_context(RequestContext(channel="websocket", chat_id="private", log_content=False)):
            private_started.set()
            await ordinary_started.wait()
            assert not tool_log_content_allowed()
            assert _redact_url_for_log("https://example.test/private") == "[content hidden]"

    async def ordinary():
        await private_started.wait()
        with request_context(RequestContext(channel="websocket", chat_id="ordinary")):
            ordinary_started.set()
            await asyncio.sleep(0)
            assert tool_log_content_allowed()
            assert _redact_url_for_log("https://example.test/private") == "https://example.test"

    await asyncio.gather(private(), ordinary())
    assert tool_log_content_allowed()


@pytest.mark.parametrize("log_content", [True, False])
async def test_search_refresh_traceback_cannot_capture_private_call_arguments(
    log_content, monkeypatch,
):
    tool = WebSearchTool(config_loader=MagicMock(side_effect=ValueError("config unavailable")))
    monkeypatch.setattr(tool, "_search_duckduckgo", AsyncMock(return_value="synthetic result"))
    tools = ToolRegistry()
    tools.register(tool)
    rendered: list[str] = []
    sink = logger.add(
        lambda message: rendered.append(str(message)), format="{message}",
        diagnose=True, backtrace=True,
    )
    try:
        with request_context(RequestContext(channel="websocket", chat_id="test", log_content=log_content)):
            results, _ = await execute_tool_calls(
                tools, [ToolCallRequest(id="test", name="web_search", arguments={"query": _SECRET})],
                concurrent=False, external_lookup_counts={}, workspace_violation_counts={},
                hook=AgentHook(), context=AgentHookContext(iteration=1, messages=[]),
            )
    finally:
        logger.remove(sink)
    assert results == ["synthetic result"]
    assert "Failed to refresh web search config" in "\n".join(rendered)
    assert (_SECRET in "\n".join(rendered)) is log_content


@pytest.mark.parametrize("log_content", [True, False])
@pytest.mark.parametrize("factory", [True, False])
async def test_optional_hook_failures_obey_private_log_policy(
    log_content, factory, diagnostic_records,
):
    class BrokenHook(AgentHook):
        async def before_execute_tool(self, *args):
            raise ValueError("synthetic hook failure")

    broken_factory = MagicMock(side_effect=ValueError("synthetic factory failure"))
    with request_context(RequestContext(channel="websocket", chat_id="test", log_content=log_content)):
        hook = build_agent_turn_hook(AgentTurnHookSpec(
            ephemeral=not log_content, run_extra_hooks_for_ephemeral=True,
            registered_hooks=[] if factory else [BrokenHook()],
            turn_hook_factories=[broken_factory] if factory else [],
        ))
        await hook.before_execute_tool(
            AgentHookContext(iteration=1, messages=[]),
            ToolCallRequest(id="test", name="web_search", arguments={"query": _SECRET}),
            None, {"query": _SECRET},
        )
    errors = [r for r in diagnostic_records if r["level"].name == "ERROR"]
    assert errors
    assert (errors[0]["exception"] is not None) is log_content
