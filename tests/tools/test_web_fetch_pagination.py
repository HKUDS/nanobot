"""Read beyond the first bounded web-fetch result."""

import json
from unittest.mock import MagicMock

import httpx
import pytest
from agent.runner_helpers import make_run_spec

from nanobot.agent.runner import AgentRunner
from nanobot.agent.tools import web as web_module
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.web import _UNTRUSTED_BANNER, WebFetchTool
from nanobot.agent.tools.web_config import WebFetchConfig
from nanobot.providers.base import LLMResponse, ToolCallRequest


@pytest.mark.parametrize("extractor", ["jina", "readability", "raw"])
async def test_fetch_pages_preserve_content_and_trust_banner(monkeypatch, extractor):
    url = "https://93.184.216.34/document"
    content = "first section " * 10 + "后续章节 🐱 " * 20
    local_content = f"<html><body><p>{content}</p></body></html>" if extractor == "readability" else content
    def respond(request):
        if request.url.host == "r.jina.ai":
            return httpx.Response(200, json={"data": {"content": content, "url": url}})
        content_type = "text/html" if extractor == "readability" else "text/plain"
        return httpx.Response(200, text=local_content, headers={"Content-Type": content_type})

    transport = httpx.MockTransport(respond)
    original_client = httpx.AsyncClient

    def client(**kwargs):
        return original_client(transport=transport)

    monkeypatch.setattr(web_module.httpx, "AsyncClient", client)
    tool = WebFetchTool(config=WebFetchConfig(use_jina_reader=extractor == "jina"))
    if extractor == "readability":
        content = tool._extract_readable_html(local_content, "markdown")
    registry = ToolRegistry()
    registry.register(tool)
    chunks = []
    offset = 0
    for _ in range(len(content) // 100 + 1):
        params = {"url": url, "maxChars": 100}
        if offset:
            params["offset"] = offset
        data = json.loads(await registry.execute("web_fetch", params))
        assert data["untrusted"] is True
        assert data["text"].startswith(_UNTRUSTED_BANNER + "\n\n")
        chunk = data["text"].removeprefix(_UNTRUSTED_BANNER + "\n\n")
        assert len(chunk) <= 100
        assert data["offset"] == offset
        assert data["totalLength"] == len(content)
        assert data["extractor"] == extractor
        chunks.append(chunk)
        if data["nextOffset"] is None:
            assert data["truncated"] is False
            break
        assert data["truncated"] is True
        assert data["nextOffset"] == offset + len(chunk)
        offset = data["nextOffset"]
    assert "".join(chunks) == content

    beyond = json.loads(await tool.execute(url=url, maxChars=100, offset=len(content) + 10))
    assert beyond["text"] == _UNTRUSTED_BANNER + "\n\n"
    assert beyond["nextOffset"] is None
    assert beyond["truncated"] is False


async def test_fetch_rejects_negative_offset_before_request():
    registry = ToolRegistry()
    registry.register(WebFetchTool())
    result = await registry.execute("web_fetch", {"url": "https://example.com", "offset": -1})
    assert "offset must be >= 0" in result


@pytest.mark.parametrize("offsets", [[None, 100, "200", 200.0, "0200"], [None, 0, "0"]])
async def test_runner_reads_continuations_but_limits_repeated_pages(monkeypatch, offsets):
    content = "a" * 100 + "b" * 100 + "c" * 100
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, text=content, headers={"Content-Type": "text/plain"},
    ))
    original_client = httpx.AsyncClient
    monkeypatch.setattr(web_module.httpx, "AsyncClient", lambda **kwargs: original_client(transport=transport))
    registry = ToolRegistry()
    registry.register(WebFetchTool(config=WebFetchConfig(use_jina_reader=False)))
    schema = json.dumps(registry.get_definitions(), sort_keys=True)
    requests = []

    async def respond(*, messages, tools, **kwargs):
        assert json.dumps(tools, sort_keys=True) == schema
        snapshot = json.loads(json.dumps(messages))
        if requests:
            assert snapshot[:len(requests[-1])] == requests[-1]
        requests.append(snapshot)
        index = len(requests) - 1
        if index == len(offsets):
            return LLMResponse(content="done")
        arguments = {"url": "https://93.184.216.34/document", "maxChars": 100}
        if offsets[index] is not None:
            arguments["offset"] = offsets[index]
        return LLMResponse(content="", tool_calls=[ToolCallRequest(
            id=f"page_{index}", name="web_fetch", arguments=arguments,
        )])

    provider = MagicMock()
    provider.chat_stream_with_retry = respond
    result = await AgentRunner().run(make_run_spec(
        provider, tools=registry, model="test-model", max_iterations=len(offsets) + 1,
        max_tool_result_chars=4000,
        initial_messages=[{"role": "user", "content": "Read the whole document"}],
    ))
    assert result.final_content == "done"
    results = [message["content"] for message in requests[-1] if message["role"] == "tool"]
    pages = [json.loads(value) for value in results[:-1]]
    assert [page["offset"] for page in pages] == [int(value or 0) for value in offsets[:-1]]
    if len(offsets) > 3:
        assert "".join(page["text"].removeprefix(_UNTRUSTED_BANNER + "\n\n") for page in pages[:3]) == content
    assert "repeated external lookup blocked" in results[-1]
