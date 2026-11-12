"""Model-facing search failures through real ddgs parsing and aggregation."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from ddgs.ddgs import DDGS
from ddgs.engines.wikipedia import Wikipedia
from ddgs.exceptions import TimeoutException
from ddgs.http_client import HttpClient

from agent.runner_helpers import make_run_spec
from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.web import WebSearchTool
from nanobot.config.schema import AgentDefaults, WebSearchConfig
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "expected_header"),
    [
        pytest.param("empty", "Error: Web search unavailable (ddgs; cause unknown).", id="empty-parsing"),
        pytest.param("forbidden", "Error: Web search unavailable (ddgs; cause unknown).", id="http-403"),
        pytest.param("rate_limited", "Error: Web search unavailable (ddgs; cause unknown).", id="http-429"),
        pytest.param("timeout", "Error: Web search unavailable (ddgs reported a timeout).", id="library-timeout"),
    ],
)
async def test_ddgs_failure_reaches_model_with_observable_cause(monkeypatch, outcome, expected_header):
    # Keep the released parser and aggregator, selecting one real engine offline.
    engine = Wikipedia(timeout=1)
    monkeypatch.setattr(DDGS, "_get_engines", lambda *_args: [engine])
    requests: list[str] = []

    def request(_self, method, url, **_kwargs):
        requests.append(url)
        if outcome == "timeout":
            raise TimeoutException("request timed out")
        status = {"empty": 200, "forbidden": 403, "rate_limited": 429}[outcome]
        return SimpleNamespace(status_code=status, text=json.dumps(["nanobot", [], [], []]))

    monkeypatch.setattr(HttpClient, "request", request)
    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content=None, tool_calls=[ToolCallRequest(
            id="search-1", name="web_search", arguments={"query": "nanobot"},
        )]),
        LLMResponse(content="done"),
    ])
    tools = ToolRegistry()
    tools.register(WebSearchTool(config=WebSearchConfig(provider="duckduckgo")))

    result = await AgentRunner().run(make_run_spec(
        provider,
        model="test-model",
        initial_messages=[{"role": "user", "content": "Search for nanobot"}],
        tools=tools,
        max_iterations=2,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
    ))

    assert len(requests) == 1
    assert provider.chat_stream_with_retry.await_count == 2
    model_messages = provider.chat_stream_with_retry.await_args_list[1].kwargs["messages"]
    tool_message = next(message for message in model_messages if message.get("role") == "tool")
    assert tool_message["tool_call_id"] == "search-1"
    assert tool_message["content"].startswith(expected_header)
    assert "No usable search result was obtained" in tool_message["content"]
    if outcome == "timeout":
        assert "matching-page availability is unknown" in tool_message["content"]
    else:
        assert "did not expose a reliable cause" in tool_message["content"]
        assert "does not establish that no matching pages exist" in tool_message["content"]
    assert result.stop_reason == "completed"
    assert result.tool_events[0]["name"] == "web_search"
    assert result.tool_events[0]["status"] == "error"
    assert result.tool_events[0]["detail"].startswith(expected_header)
