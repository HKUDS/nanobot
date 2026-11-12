"""Regression tests for turns that stop at the tool-iteration limit (#5924)."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.runtime_context import public_history_messages
from nanobot.session.goal_state import GOAL_STATE_KEY

_STOP_MARKER = "previous turn stopped at the tool-iteration limit"


class BudgetProvider(LLMProvider):
    def __init__(self, requests):
        super().__init__(provider_name="offline-budget-test")
        self.requests = requests
        self.schemas = []

    def get_default_model(self):
        return "test-model"

    async def chat(self, messages, tools=None, **kwargs):
        self.requests.append(deepcopy(self._sanitize_empty_content(messages)))
        self.schemas.append(deepcopy(tools))
        last_user = next(m for m in reversed(messages) if m.get("role") == "user")
        if str(last_user.get("content")).startswith("run the tests") and tools is not None:
            return LLMResponse(
                content="running",
                tool_calls=[
                    ToolCallRequest(
                        id=f"call_{len(self.requests)}",
                        name="exec",
                        arguments={"command": "make test"},
                    )
                ],
            )
        return LLMResponse(content="done", tool_calls=[])


def _make_loop(tmp_path, requests: list[list[dict[str, Any]]]) -> AgentLoop:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=BudgetProvider(requests),
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=128_000,
        max_iterations=2,
    )
    exec_tool = loop.tools.get("exec")
    assert exec_tool is not None
    exec_tool.execute = AsyncMock(return_value="Error: make test failed")
    return loop


def _last_user_content(messages: list[dict[str, Any]]) -> str:
    return str(next(m for m in reversed(messages) if m.get("role") == "user")["content"])


async def test_next_turn_is_told_not_to_resume_after_iteration_limit(tmp_path):
    requests: list[list[dict[str, Any]]] = []
    loop = _make_loop(tmp_path, requests)
    try:
        await loop.process_direct("run the tests", session_key="cli:limit")
        assert _STOP_MARKER not in _last_user_content(requests[0])

        await loop.process_direct("what is 2 + 2?", session_key="cli:limit")
        assert _STOP_MARKER in _last_user_content(requests[-1])

        # Later inputs get no new marker; the earlier marked input stays in history.
        await loop.process_direct("thanks", session_key="cli:limit")
        assert _STOP_MARKER not in _last_user_content(requests[-1])
        assert _STOP_MARKER in json.dumps(requests[-1])
    finally:
        await loop.aclose()


async def test_stop_survives_restart_and_keeps_history_prefix(tmp_path):
    previous: list[list[dict[str, Any]]] = []
    loop = _make_loop(tmp_path, previous)
    try:
        await loop.process_direct("hello", session_key="cli:limit")
        await loop.process_direct("run the tests", session_key="cli:limit")
        schemas = loop.provider.schemas
    finally:
        await loop.aclose()

    current: list[list[dict[str, Any]]] = []
    loop = _make_loop(tmp_path, current)
    try:
        await loop.process_direct("what is 2 + 2?", session_key="cli:limit")
        assert _STOP_MARKER in _last_user_content(current[0])
        # Ordinary prefix and tool schemas are unchanged. Structured failed calls remain.
        assert json.dumps(previous[0]) == json.dumps(current[0][:len(previous[0])])
        assert schemas[0] == loop.provider.schemas[0]
        assert [m for m in previous[-1] if m["role"] == "tool"] == [
            m for m in current[0] if m["role"] == "tool"
        ]
        await loop.process_direct("thanks", session_key="cli:limit")
        assert json.dumps(current[0]) == json.dumps(current[1][:len(current[0])])
        assert _STOP_MARKER not in _last_user_content(current[1])
        session = await loop.sessions.state.get("cli:limit")
        assert _STOP_MARKER not in json.dumps(public_history_messages(session.messages))

        # Another session must not inherit this stopped turn.
        await loop.process_direct("hello", session_key="cli:other")
        assert _STOP_MARKER not in json.dumps(current[-1])
    finally:
        await loop.aclose()


async def test_goal_budget_handoff_is_not_an_abandoned_turn(tmp_path):
    requests: list[list[dict[str, Any]]] = []
    loop = _make_loop(tmp_path, requests)
    pending: asyncio.Queue[InboundMessage] = asyncio.Queue()
    try:
        await loop.sessions.state.get("cli:goal")
        await loop.sessions.state.update_metadata("cli:goal", {
            GOAL_STATE_KEY: {"status": "active", "objective": "run the tests"},
        })
        await loop._process_message(
            InboundMessage(channel="cli", sender_id="user", chat_id="goal", content="run the tests"),
            pending_queue=pending,
        )
        continuation = pending.get_nowait()
        assert continuation.sender_id == "system:continuation"

        # A new user input can run before the already queued goal continuation.
        next_request = len(requests)
        await loop.process_direct("give me a progress update", session_key="cli:goal")
        assert _STOP_MARKER not in _last_user_content(requests[next_request])
        next_request = len(requests)
        await loop._process_message(continuation, pending_queue=pending)
        assert _STOP_MARKER not in _last_user_content(requests[next_request])
    finally:
        await loop.aclose()


@pytest.mark.parametrize("operation", ["reset", "fork"])
async def test_new_history_does_not_inherit_abandoned_turn(tmp_path, operation):
    requests: list[list[dict[str, Any]]] = []
    loop = _make_loop(tmp_path, requests)
    try:
        await loop.process_direct("run the tests", session_key="cli:limit")
        target = "cli:limit"
        if operation == "reset":
            await loop.process_direct("/new", session_key=target)
        else:
            target = "cli:fork"
            await loop.sessions.state.fork("cli:limit", target, before_user_index=0)
        await loop.process_direct("hello", session_key=target)
        assert _STOP_MARKER not in _last_user_content(requests[-1])
    finally:
        await loop.aclose()


async def test_temporary_turn_skips_hint_and_explicit_retry_can_use_tools(tmp_path):
    requests: list[list[dict[str, Any]]] = []
    loop = _make_loop(tmp_path, requests)
    try:
        await loop.process_direct("run the tests", session_key="cli:limit")
        await loop.process_direct("hello", session_key="cli:limit", ephemeral=True)
        assert _STOP_MARKER not in _last_user_content(requests[-1])
        next_request = len(requests)
        await loop.process_direct("run the tests again", session_key="cli:limit")
        assert _STOP_MARKER in _last_user_content(requests[next_request])
        assert "only if the user asks" in _last_user_content(requests[next_request])
        assert loop.tools.get("exec").execute.await_count == 4
    finally:
        await loop.aclose()
