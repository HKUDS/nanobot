from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.context import current_request_context
from nanobot.api.server import API_CHAT_ID, API_SESSION_KEY, create_app
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

pytestmark = pytest.mark.asyncio
AUTH = {"Authorization": "Bearer test-api-key"}


class RouteProvider(LLMProvider):
    def __init__(self, *, hold_first=False):
        super().__init__(provider_name="offline-api-test")
        self.calls = []
        self.hold_first = hold_first
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def get_default_model(self):
        return "offline-api-test"

    async def chat(self, messages, tools=None, **kwargs):
        ctx = current_request_context()
        assert ctx is not None
        self.calls.append({
            "session_key": ctx.session_key,
            "messages": deepcopy(self._sanitize_empty_content(messages)),
            "tools": deepcopy(tools),
        })
        if self.hold_first and len(self.calls) == 1:
            self.started.set()
            await asyncio.wait_for(self.release.wait(), 10)
        if messages[-1]["role"] != "tool":
            call_number = 1 + sum(len(message.get("tool_calls", [])) for message in messages)
            return LLMResponse(content=None, tool_calls=[ToolCallRequest(
                id=f"inspect-route-{call_number}", name="my",
                arguments={"action": "check", "key": "request.chat_id"},
            )])
        return LLMResponse(content=json.dumps({
            "session_key": ctx.session_key,
            "chat_id": ctx.chat_id,
            "tool_result": messages[-1]["content"],
        }))

    async def chat_stream(self, messages, tools=None, on_content_delta=None, **kwargs):
        response = await self.chat(messages, tools, **kwargs)
        if response.content and on_content_delta:
            midpoint = len(response.content) // 2
            await on_content_delta(response.content[:midpoint])
            await on_content_delta(response.content[midpoint:])
        return response


@asynccontextmanager
async def runtime(workspace, provider, *, received=None):
    agent = AgentLoop(
        bus=MessageBus(), provider=provider, workspace=workspace,
        restrict_to_workspace=True, max_iterations=3,
    )
    app = create_app(agent, api_key="test-api-key")
    if received is not None:
        @web.middleware
        async def observe_request(request, handler):
            body = await request.json()
            if body["messages"][0]["content"] == "SECOND_TURN":
                received.set()
            return await handler(request)
        app.middlewares.append(observe_request)
    client = TestClient(TestServer(app))
    try:
        await client.start_server()
        yield agent, client
    finally:
        await client.close()
        await agent.aclose()


async def post(client, session_id, text, stream=False):
    response = await client.post(
        "/v1/chat/completions", headers=AUTH,
        json={
            "session_id": session_id, "stream": stream,
            "messages": [{"role": "user", "content": text}],
        },
    )
    assert response.status == 200, await response.text()
    if not stream:
        return json.loads((await response.json())["choices"][0]["message"]["content"])
    body = await response.text()
    assert body.endswith("data: [DONE]\n\n")
    chunks = [json.loads(line[6:]) for line in body.splitlines()
              if line.startswith("data: ") and line != "data: [DONE]"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert len({chunk["id"] for chunk in chunks}) == 1
    return json.loads("".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks))


def assert_route(result, chat_id):
    assert result["session_key"] == f"api:{chat_id}"
    assert result["chat_id"] == chat_id
    assert result["tool_result"] == f"request.chat_id: {chat_id!r}"


def assert_prefix(previous, following):
    assert json.dumps(previous["messages"], ensure_ascii=False) == json.dumps(
        following["messages"][:len(previous["messages"])], ensure_ascii=False,
    )
    assert json.dumps(previous["tools"], ensure_ascii=False) == json.dumps(
        following["tools"], ensure_ascii=False,
    )


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("second_id", ["alpha", " alpha ", "beta"])
async def test_concurrent_requests_keep_routes_history_and_order(tmp_path, stream, second_id):
    provider = RouteProvider(hold_first=True)
    received = asyncio.Event()
    async with runtime(tmp_path / "workspace", provider, received=received) as (_, client):
        first = asyncio.create_task(post(client, "alpha", "FIRST_TURN", stream))
        tasks = [first]
        try:
            await asyncio.wait_for(provider.started.wait(), 10)
            second = asyncio.create_task(post(client, second_id, "SECOND_TURN", stream))
            tasks.append(second)
            await asyncio.wait_for(received.wait(), 10)
            if second_id == "alpha":
                assert len(provider.calls) == 1
                assert not second.done()
                provider.release.set()
            else:
                assert_route(await asyncio.wait_for(second, 10), second_id)
                assert not first.done()
                provider.release.set()
            assert_route(await asyncio.wait_for(first, 10), "alpha")
            assert_route(await asyncio.wait_for(second, 10), second_id)
            second_call = next(call for call in provider.calls
                               if "SECOND_TURN" in json.dumps(call["messages"]))
            assert ("FIRST_TURN" in json.dumps(second_call["messages"])) == (second_id == "alpha")
        finally:
            provider.release.set()
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("session_id", ["alpha", " alpha ", "  ", None])
async def test_old_history_survives_route_fix_restart_and_rollback(tmp_path, session_id):
    workspace = tmp_path / "workspace"
    old_key = f"api:{session_id}" if session_id else API_SESSION_KEY
    old_provider = RouteProvider()
    async with runtime(workspace, old_provider) as (agent, _):
        await agent.process_direct(
            "LEGACY_HISTORY", session_key=old_key, channel="api", chat_id=API_CHAT_ID,
        )

    upgraded = RouteProvider()
    async with runtime(workspace, upgraded) as (_, client):
        result = await post(client, session_id, "UPGRADED_TURN")
        assert_route(result, session_id or "default")
        assert "LEGACY_HISTORY" in json.dumps(upgraded.calls[0]["messages"])
        assert_prefix(old_provider.calls[0], upgraded.calls[0])
        old_tool_prefix = old_provider.calls[1]["messages"]
        assert old_tool_prefix == upgraded.calls[0]["messages"][:len(old_tool_prefix)]
        assert_prefix(upgraded.calls[0], upgraded.calls[1])

    reopened = RouteProvider()
    async with runtime(workspace, reopened) as (agent, client):
        assert_route(await post(client, session_id, "AFTER_RESTART"), session_id or "default")
        replay = json.dumps(reopened.calls[0]["messages"])
        assert "LEGACY_HISTORY" in replay and "UPGRADED_TURN" in replay
        await agent.process_direct(
            "ROLLBACK_TURN", session_key=old_key, channel="api", chat_id=API_CHAT_ID,
        )
        replay = json.dumps(reopened.calls[-1]["messages"])
        assert all(text in replay for text in ("LEGACY_HISTORY", "UPGRADED_TURN", "AFTER_RESTART"))
