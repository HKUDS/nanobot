"""End-to-end tests for mid-turn credential prompts over the WebSocket channel.

These drive the real dispatch path: the ``request_secret`` tool publishes an
``agent_ui`` form request, the client answers with ``credential_submit`` or
``credential_cancel`` envelopes, and submitted values must land only in the
secrets file — never the transcript, inbound bus, or tool result text.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.secret_prompt import RequestSecretTool
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.webui.credential_prompts import credential_prompts
from nanobot.webui.gateway_services import build_gateway_services
from nanobot.webui.metadata import WEBUI_TURN_METADATA_KEY

_PORT = 29877
SECRET_VALUE = "s3cr3t-un1qu3-value"


def _gateway(bus: Any, **kw: Any):
    cfg = WebSocketConfig.model_validate({
        "enabled": True, "allowFrom": ["*"],
        "host": "127.0.0.1", "port": _PORT,
        "path": "/ws", "websocketRequiresToken": False,
    })
    return build_gateway_services(
        config=cfg,
        bus=bus,
        session_manager=kw.get("session_manager"),
        static_dist_path=None,
        workspace_path=kw.get("workspace_path", Path.cwd()),
        default_restrict_to_workspace=False,
        runtime_model_name=None,
        runtime_surface="browser",
        runtime_capabilities_overrides=None,
    )


def _channel(bus: Any, **kw: Any) -> WebSocketChannel:
    return WebSocketChannel(
        {"enabled": True, "allowFrom": ["*"]},
        bus,
        gateway=_gateway(bus, **kw),
    )


def _connection() -> AsyncMock:
    conn = AsyncMock()
    conn.remote_address = ("127.0.0.1", 5000)
    return conn


async def _attach(channel: WebSocketChannel, conn: AsyncMock, chat_id: str) -> None:
    await channel._dispatch_envelope(conn, "webui-client", {
        "type": "attach", "chat_id": chat_id,
    })
    conn.send.reset_mock()


def _frames(conn: AsyncMock) -> list[dict[str, Any]]:
    return [json.loads(call.args[0]) for call in conn.send.await_args_list]


async def _wait_for_frame(conn: AsyncMock, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if conn.send.await_count:
            return json.loads(conn.send.await_args.args[0])
        await asyncio.sleep(0.01)
    raise TimeoutError("no outbound frame")


def _start_secret_request(
    channel: WebSocketChannel,
    chat_id: str,
    secrets_file: Path,
    *,
    service: str = "LinkedIn",
    fields: list[dict[str, Any]] | None = None,
    timeout_seconds: int = 30,
) -> asyncio.Task[str]:
    tool = RequestSecretTool(
        send_callback=channel.send,
        secrets_file=secrets_file,
    )
    ctx = RequestContext(
        channel="websocket",
        chat_id=chat_id,
        turn_id="turn-1",
        metadata={WEBUI_TURN_METADATA_KEY: "turn-1"},
    )
    with request_context(ctx):
        return asyncio.create_task(tool.execute(
            service=service,
            fields=fields or [
                {"key": "LINKEDIN_EMAIL", "label": "Email"},
                {"key": "LINKEDIN_PASSWORD", "label": "Password"},
            ],
            reason="test reason",
            timeout_seconds=timeout_seconds,
        ))


@pytest.fixture()
def bus() -> MagicMock:
    b = MagicMock()
    b.publish_inbound = AsyncMock()
    b.publish_outbound = AsyncMock()
    return b


@pytest.fixture(autouse=True)
def clear_credential_prompts():
    yield
    for request_id in list(credential_prompts._pending):
        credential_prompts.drop(request_id)


@pytest.mark.asyncio
async def test_credential_prompt_submit_roundtrip(bus, tmp_path) -> None:
    channel = _channel(bus)
    conn = _connection()
    channel._webui_connections.add(conn)
    await _attach(channel, conn, "chat-1")
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("EXISTING=keepme\n", encoding="utf-8")

    task = _start_secret_request(channel, "chat-1", secrets_file)
    request_frame = await _wait_for_frame(conn)
    assert request_frame["event"] == "message"
    assert request_frame["chat_id"] == "chat-1"
    blob = request_frame["agent_ui"]
    assert blob["kind"] == "credential_request"
    data = blob["data"]
    assert data["chat_id"] == "chat-1"
    assert data["service"] == "LinkedIn"
    assert [f["key"] for f in data["fields"]] == ["LINKEDIN_EMAIL", "LINKEDIN_PASSWORD"]

    await channel._dispatch_envelope(conn, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": data["request_id"],
        "values": {
            "LINKEDIN_EMAIL": "me@example.com",
            "LINKEDIN_PASSWORD": SECRET_VALUE,
            "UNDECLARED": "dropped",
        },
    })

    result = await asyncio.wait_for(task, timeout=5)
    assert "LINKEDIN_EMAIL" in result and "LINKEDIN_PASSWORD" in result
    assert SECRET_VALUE not in result
    assert "me@example.com" not in result

    resolved = _frames(conn)[-1]
    assert resolved["event"] == "credential_resolved"
    assert resolved["request_id"] == data["request_id"]
    assert resolved["status"] == "submitted"

    text = secrets_file.read_text(encoding="utf-8")
    assert "EXISTING=keepme" in text
    assert f'LINKEDIN_PASSWORD="{SECRET_VALUE}"' in text
    assert "UNDECLARED" not in text

    # The submitted values never enter the transcript, the wire payloads, or
    # the inbound message bus.
    bus.publish_inbound.assert_not_called()
    transcript_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.rglob("*")
        if path.is_file() and path != secrets_file
    )
    assert SECRET_VALUE not in transcript_text
    for frame in _frames(conn):
        assert SECRET_VALUE not in json.dumps(frame)


@pytest.mark.asyncio
async def test_credential_prompt_cancel(bus, tmp_path) -> None:
    channel = _channel(bus)
    conn = _connection()
    channel._webui_connections.add(conn)
    await _attach(channel, conn, "chat-1")

    task = _start_secret_request(channel, "chat-1", tmp_path / "secrets.env")
    request_frame = await _wait_for_frame(conn)
    request_id = request_frame["agent_ui"]["data"]["request_id"]

    await channel._dispatch_envelope(conn, "webui-client", {
        "type": "credential_cancel",
        "chat_id": "chat-1",
        "request_id": request_id,
    })

    result = await asyncio.wait_for(task, timeout=5)
    assert "declined" in result
    assert _frames(conn)[-1]["status"] == "cancelled"
    bus.publish_inbound.assert_not_called()


@pytest.mark.asyncio
async def test_credential_prompt_rejects_wrong_and_duplicate_submit(bus, tmp_path) -> None:
    channel = _channel(bus)
    owner = _connection()
    other = _connection()
    channel._webui_connections.update((owner, other))
    await _attach(channel, owner, "chat-1")
    await _attach(channel, other, "chat-2")

    secrets_file = tmp_path / "secrets.env"
    task = _start_secret_request(channel, "chat-1", secrets_file)
    request_frame = await _wait_for_frame(owner)
    request_id = request_frame["agent_ui"]["data"]["request_id"]

    # A connection subscribed only to another chat cannot fill this request.
    await channel._dispatch_envelope(other, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": request_id,
        "values": {"LINKEDIN_EMAIL": "x", "LINKEDIN_PASSWORD": "y"},
    })
    denied = json.loads(other.send.await_args.args[0])
    assert denied["event"] == "credential_result"
    assert denied["status"] == "forbidden"
    assert not task.done()

    # Unknown request ids are rejected without touching the pending request.
    await channel._dispatch_envelope(owner, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": "does-not-exist",
        "values": {},
    })
    rejected = json.loads(owner.send.await_args.args[0])
    assert rejected["event"] == "credential_result"
    assert rejected["status"] == "unknown"
    assert not task.done()

    await channel._dispatch_envelope(owner, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": request_id,
        "values": {"LINKEDIN_EMAIL": "x@y.z", "LINKEDIN_PASSWORD": "pw"},
    })
    await asyncio.wait_for(task, timeout=5)

    # A second submit for the resolved id reports the terminal status.
    owner.send.reset_mock()
    await channel._dispatch_envelope(owner, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": request_id,
        "values": {"LINKEDIN_EMAIL": "a@b.c", "LINKEDIN_PASSWORD": "pw2"},
    })
    dup = json.loads(owner.send.await_args.args[0])
    assert dup["event"] == "credential_result"
    assert dup["status"] == "submitted"
    assert 'LINKEDIN_PASSWORD="pw"' in secrets_file.read_text()


@pytest.mark.asyncio
async def test_credential_prompt_reports_expired_status(bus, tmp_path) -> None:
    channel = _channel(bus)
    conn = _connection()
    channel._webui_connections.add(conn)
    await _attach(channel, conn, "chat-1")

    # A zero-second request is already expired when the submit arrives.
    task = _start_secret_request(
        channel, "chat-1", tmp_path / "secrets.env", timeout_seconds=10,
    )
    request_frame = await _wait_for_frame(conn)
    request_id = request_frame["agent_ui"]["data"]["request_id"]
    prompt = credential_prompts.get(request_id)
    assert prompt is not None
    prompt.expires_at = time.time() - 1

    await channel._dispatch_envelope(conn, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": request_id,
        "values": {"LINKEDIN_EMAIL": "x", "LINKEDIN_PASSWORD": "y"},
    })
    rejected = json.loads(conn.send.await_args.args[0])
    assert rejected["event"] == "credential_result"
    assert rejected["status"] == "expired"
    assert "closed" in await asyncio.wait_for(task, timeout=5)
    assert not (tmp_path / "secrets.env").exists()


@pytest.mark.asyncio
async def test_credential_prompt_missing_required_fields(bus, tmp_path) -> None:
    channel = _channel(bus)
    conn = _connection()
    channel._webui_connections.add(conn)
    await _attach(channel, conn, "chat-1")

    task = _start_secret_request(channel, "chat-1", tmp_path / "secrets.env")
    request_frame = await _wait_for_frame(conn)
    request_id = request_frame["agent_ui"]["data"]["request_id"]

    await channel._dispatch_envelope(conn, "webui-client", {
        "type": "credential_submit",
        "chat_id": "chat-1",
        "request_id": request_id,
        "values": {"LINKEDIN_EMAIL": "", "LINKEDIN_PASSWORD": "pw"},
    })
    rejected = json.loads(conn.send.await_args.args[0])
    assert rejected["status"] == "missing_fields"
    assert not task.done()

    credential_prompts.cancel(request_id)
    assert "declined" in await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_credential_prompt_cancelled_when_last_subscriber_leaves(bus, tmp_path) -> None:
    channel = _channel(bus)
    conn = _connection()
    channel._webui_connections.add(conn)
    await _attach(channel, conn, "chat-1")

    task = _start_secret_request(channel, "chat-1", tmp_path / "secrets.env")
    await _wait_for_frame(conn)

    await channel._commands.cleanup_connection(conn)
    result = await asyncio.wait_for(task, timeout=5)
    assert "declined" in result


@pytest.mark.asyncio
async def test_credential_prompt_requires_webui_channel(bus, tmp_path) -> None:
    tool = RequestSecretTool(
        send_callback=AsyncMock(),
        secrets_file=tmp_path / "secrets.env",
    )
    ctx = RequestContext(channel="telegram", chat_id="chat-1")
    with request_context(ctx):
        result = await tool.execute(service="LinkedIn", fields=[{"key": "K"}])
    assert "only available for WebUI" in result
