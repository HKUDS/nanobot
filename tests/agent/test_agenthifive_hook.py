from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from agenthifive_nanobot.adapter import AgentHiFiveAdapter
from agenthifive_nanobot.hooks import AH5_EXECUTE_TOOL, _parse_approval_response
from agenthifive_nanobot.types import BearerAuthConfig, PendingApproval
from agenthifive_nanobot.vault_client import VaultClient
from nanobot.agent.hook import AgentHookContext
from nanobot.providers.base import ToolCallRequest


class _DummyVault:
    base_url = "https://vault.example"


class _RecordingStore:
    def __init__(self) -> None:
        self.added: list[PendingApproval] = []

    def add(self, approval: PendingApproval) -> None:
        self.added.append(approval)


class _NoopInjector:
    async def deliver(self, *_args, **_kwargs) -> None:
        return None


def _make_tool_context(tool_call_id: str, approval_id: str, url: str) -> AgentHookContext:
    return AgentHookContext(
        iteration=0,
        messages=[],
        tool_calls=[
            ToolCallRequest(
                id=tool_call_id,
                name=AH5_EXECUTE_TOOL,
                arguments={
                    "connectionId": "conn_1",
                    "service": "gmail",
                    "method": "GET",
                    "url": url,
                },
            )
        ],
        tool_results=[
            json.dumps(
                {
                    "approvalRequired": True,
                    "approvalRequestId": approval_id,
                }
            )
        ],
    )


@pytest.mark.asyncio
async def test_agenthifive_hook_keeps_session_context_and_tool_args_task_local():
    store = _RecordingStore()
    adapter = AgentHiFiveAdapter(
        vault_client=_DummyVault(),
        store=store,
        injector=_NoopInjector(),
    )
    hook = adapter.hook

    first_ready = asyncio.Event()
    second_finished = asyncio.Event()

    async def _first_session() -> None:
        adapter.set_session_context(
            channel="agenthifive",
            chat_id="chat-a",
            sender_id="user-a",
            session_key="session-a",
        )
        context = _make_tool_context("call-a", "apr-a", "https://gmail.googleapis.com/a")
        await hook.before_execute_tools(context)
        first_ready.set()
        await second_finished.wait()
        await hook.after_iteration(context)

    async def _second_session() -> None:
        await first_ready.wait()
        adapter.set_session_context(
            channel="agenthifive",
            chat_id="chat-b",
            sender_id="user-b",
            session_key="session-b",
        )
        context = _make_tool_context("call-b", "apr-b", "https://gmail.googleapis.com/b")
        await hook.before_execute_tools(context)
        await hook.after_iteration(context)
        second_finished.set()

    await asyncio.gather(_first_session(), _second_session())

    approvals = {approval.approval_request_id: approval for approval in store.added}
    assert set(approvals) == {"apr-a", "apr-b"}
    assert approvals["apr-a"].chat_id == "chat-a"
    assert approvals["apr-a"].sender_id == "user-a"
    assert approvals["apr-a"].session_key == "session-a"
    assert approvals["apr-a"].original_payload["url"] == "https://gmail.googleapis.com/a"
    assert approvals["apr-b"].chat_id == "chat-b"
    assert approvals["apr-b"].sender_id == "user-b"
    assert approvals["apr-b"].session_key == "session-b"
    assert approvals["apr-b"].original_payload["url"] == "https://gmail.googleapis.com/b"


def test_parse_approval_response_handles_nested_mcp_content_blocks():
    response = json.dumps(
        [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "approvalRequired": True,
                        "approvalRequestId": "apr-nested",
                    }
                ),
            }
        ]
    )

    parsed = _parse_approval_response(response)

    assert parsed == {
        "approvalRequired": True,
        "approvalRequestId": "apr-nested",
    }


@pytest.mark.asyncio
async def test_vault_client_execute_returns_protocol_error_for_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    client = VaultClient(
        base_url="https://vault.example",
        auth=BearerAuthConfig(mode="bearer", token="token"),
    )
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b"not-json",
        request=httpx.Request("POST", "https://vault.example/v1/vault/execute"),
    )

    async def _fake_request(*_args, **_kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(client, "_request", _fake_request)

    with caplog.at_level(logging.WARNING):
        result = await client.execute({"method": "GET", "url": "https://example.com"})

    assert result.blocked is not None
    assert result.blocked.policy == "vault-protocol"
    assert result.blocked.reason == "Vault returned an invalid JSON response."
    assert result.blocked.hint is not None
    assert "invalid_json" in result.blocked.hint
    assert "AgentHiFive vault execute returned invalid JSON" in caplog.text
    assert "not-json" not in caplog.text


@pytest.mark.asyncio
async def test_vault_client_execute_replay_handles_invalid_json_without_raising(
    monkeypatch: pytest.MonkeyPatch,
):
    client = VaultClient(
        base_url="https://vault.example",
        auth=BearerAuthConfig(mode="bearer", token="token"),
    )
    response = httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=b"still-not-json",
        request=httpx.Request("POST", "https://vault.example/v1/vault/execute"),
    )

    async def _fake_request(*_args, **_kwargs) -> httpx.Response:
        return response

    monkeypatch.setattr(client, "_request", _fake_request)

    replay = await client.execute_replay(
        {
            "method": "GET",
            "url": "https://example.com/file",
        },
        "apr-1",
    )

    assert replay.status_code == 200
    assert replay.body == {
        "status": 200,
        "error": "Vault returned an invalid JSON response.",
        "hint": "invalid_json; status=200; content_type=application/json; bytes=14",
    }
