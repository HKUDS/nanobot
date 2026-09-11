from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import ProgressEvent
from nanobot.bus.queue import MessageBus
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.config import LinearConfig, validate_public_base_url
from nanobot.channels.linear.oauth import OAUTH_FLOWS, authorization_url
from nanobot.channels.linear.runtime import LinearChannel
from nanobot.channels.linear.server import acquire_http_server
from nanobot.channels.linear.state import LinearInstallation, LinearStateStore


def _config(port: int = 3979) -> LinearConfig:
    return LinearConfig(
        client_id="client-id",
        client_secret="client-secret",
        webhook_signing_secret="webhook-secret",
        public_base_url="https://nanobot.example.com",
        host="127.0.0.1",
        port=port,
        allow_from=["*"],
    )


def _installation() -> LinearInstallation:
    return LinearInstallation(
        organization_id="org-1",
        oauth_client_id="client-id",
        organization_name="Example",
        app_user_id="app-user-1",
        access_token="access",
        refresh_token="refresh",
        expires_at=time.time() + 3600,
        scope=("read", "write", "app:mentionable"),
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _post_webhook(
    port: int,
    payload: dict[str, Any],
    *,
    signature: str | None = None,
    delivery: str = "delivery-1",
) -> tuple[int, bytes]:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    actual_signature = signature or hmac.new(b"webhook-secret", raw, hashlib.sha256).hexdigest()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        "/linear/webhook",
        raw,
        {
            "Content-Type": "application/json",
            "Linear-Signature": actual_signature,
            "Linear-Delivery": delivery,
        },
    )
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, body


def _agent_webhook(*, action: str = "created", signal: str = "") -> dict[str, Any]:
    activity: dict[str, Any] | None = None
    if action == "prompted":
        activity = {
            "id": "activity-1",
            "agentSessionId": "session-1",
            "content": {"type": "prompt", "body": "continue the work"},
            "signal": signal or None,
            "userId": "user-1",
        }
    return {
        "type": "AgentSessionEvent",
        "action": action,
        "oauthClientId": "client-id",
        "organizationId": "org-1",
        "webhookTimestamp": int(time.time() * 1000),
        "promptContext": "please investigate this issue",
        "agentActivity": activity,
        "agentSession": {
            "id": "session-1",
            "organizationId": "org-1",
            "creatorId": "user-1",
            "issueId": "issue-1",
            "commentId": "comment-1",
        },
    }


def test_linear_config_requires_public_https_origin() -> None:
    assert validate_public_base_url("https://nanobot.example.com") == "https://nanobot.example.com"
    assert LinearConfig(public_base_url="  https://nanobot.example.com/  ").public_base_url == (
        "https://nanobot.example.com"
    )
    for value in (
        "http://nanobot.example.com",
        "https://localhost:3979",
        "https://127.0.0.1",
        "https://nanobot.example.com/linear",
        "https://nanobot.example.com:invalid",
        "https://nanobot.example.com:",
    ):
        with pytest.raises(ValueError):
            validate_public_base_url(value)


def test_linear_config_rejects_overlapping_callback_paths() -> None:
    with pytest.raises(ValueError, match="must be different"):
        LinearConfig(
            webhook_path="/linear/events/",
            oauth_callback_path="/linear/events",
        )


def test_oauth_authorization_uses_app_actor_pkce_and_mention_scope() -> None:
    flow = OAUTH_FLOWS.create()
    try:
        parsed = urlparse(authorization_url(_config(), flow))
        query = parsed.query
        assert parsed.scheme == "https"
        assert "actor=app" in query
        assert "code_challenge_method=S256" in query
        assert "app%3Amentionable" in query
        assert "app%3Aassignable" not in query
        assert f"state={flow.state}" in query
    finally:
        OAUTH_FLOWS.remove(flow)


def test_state_store_persists_installations_and_deduplicates_webhooks(tmp_path: Path) -> None:
    store = LinearStateStore(tmp_path / "linear.sqlite3")
    installation = _installation()
    store.save_installation(installation)
    second_installation = replace(
        installation,
        organization_id="org-2",
        organization_name="Second workspace",
        app_user_id="app-user-2",
        access_token="second-access",
        refresh_token="second-refresh",
    )
    store.save_installation(second_installation)

    assert store.installation("org-1") == installation
    assert store.installation("org-2") == second_installation
    assert store.enqueue_webhook("delivery-1", _agent_webhook()) is True
    assert store.enqueue_webhook("delivery-1", _agent_webhook()) is False

    events = store.claim_webhooks()
    assert len(events) == 1
    assert events[0].delivery_id == "delivery-1"
    store.complete_webhook("delivery-1")
    assert store.claim_webhooks() == []
    assert store.enqueue_webhook("delivery-1", _agent_webhook()) is False


def test_webhook_server_verifies_signature_deduplicates_and_ignores_comments(
    tmp_path: Path,
) -> None:
    port = _free_port()
    config = _config(port)
    store = LinearStateStore(tmp_path / "linear.sqlite3")
    lease = acquire_http_server(config, store)
    try:
        status, _ = _post_webhook(port, _agent_webhook(), signature="invalid")
        assert status == 401

        status, _ = _post_webhook(port, _agent_webhook())
        assert status == 200
        status, _ = _post_webhook(port, _agent_webhook())
        assert status == 200
        assert len(store.claim_webhooks()) == 1

        comment = _agent_webhook()
        comment["type"] = "Comment"
        comment.pop("oauthClientId")
        status, body = _post_webhook(port, comment, delivery="comment-1")
        assert status == 200
        assert b"ignored" in body
    finally:
        lease.close()


def test_webhook_server_rejects_stale_or_wrong_app_events(tmp_path: Path) -> None:
    port = _free_port()
    store = LinearStateStore(tmp_path / "linear.sqlite3")
    lease = acquire_http_server(_config(port), store)
    try:
        stale = _agent_webhook()
        stale["webhookTimestamp"] = int((time.time() - 120) * 1000)
        assert _post_webhook(port, stale)[0] == 401

        other_app = _agent_webhook()
        other_app["oauthClientId"] = "other-client"
        assert _post_webhook(port, other_app, delivery="other-app")[0] == 403
    finally:
        lease.close()


def test_oauth_callback_completes_only_registered_state(tmp_path: Path) -> None:
    port = _free_port()
    lease = acquire_http_server(
        _config(port),
        LinearStateStore(tmp_path / "linear.sqlite3"),
    )
    flow = OAUTH_FLOWS.create()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        connection.request(
            "GET",
            f"/linear/oauth/callback?state={flow.state}&code=authorization-code",
        )
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 200
        assert flow.code == "authorization-code"
    finally:
        OAUTH_FLOWS.remove(flow)
        lease.close()


@pytest.mark.asyncio
async def test_oauth_exchange_saves_workspace_app_identity_and_required_scopes(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 86400,
                    "scope": "read write app:mentionable",
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "viewer": {
                        "id": "app-user-1",
                        "organization": {"id": "org-1", "name": "Example"},
                    }
                }
            },
        )

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        installation = await client.exchange_code("code", "verifier")
    finally:
        await http.aclose()

    assert installation.app_user_id == "app-user-1"
    assert installation.organization_id == "org-1"
    assert state.installation("org-1") == installation


@pytest.mark.asyncio
async def test_oauth_exchange_rejects_missing_mention_scope(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 86400,
                    "scope": "read write",
                },
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "viewer": {
                        "id": "app-user-1",
                        "organization": {"id": "org-1", "name": "Example"},
                    }
                }
            },
        )

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        with pytest.raises(LinearApiError, match="app:mentionable"):
            await client.exchange_code("code", "verifier")
    finally:
        await http.aclose()

    assert state.has_installations() is False


@pytest.mark.asyncio
async def test_graphql_non_json_server_error_is_retryable(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="temporarily unavailable")

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(_installation())
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        with pytest.raises(LinearApiError) as error:
            await client.graphql("org-1", "query Test { viewer { id } }", {})
    finally:
        await http.aclose()

    assert error.value.retryable is True


@pytest.mark.asyncio
async def test_graphql_rate_limit_error_is_retryable(tmp_path: Path) -> None:
    reset_at = int((time.time() + 60) * 1000)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            headers={"X-RateLimit-Requests-Reset": str(reset_at)},
            json={
                "errors": [{
                    "message": "Request limit exceeded",
                    "extensions": {"code": "RATELIMITED"},
                }]
            },
        )

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(_installation())
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        with pytest.raises(LinearApiError, match="Request limit exceeded") as error:
            await client.graphql("org-1", "query Test { viewer { id } }", {})
    finally:
        await http.aclose()

    assert error.value.retryable is True
    assert error.value.retry_after is not None
    assert 50 <= error.value.retry_after <= 60


@pytest.mark.asyncio
async def test_expired_workspace_token_is_refreshed_and_rotated(tmp_path: Path) -> None:
    seen_refresh_form: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            seen_refresh_form.update(parse_qs(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "access_token": "rotated-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 86400,
                    "scope": "read write app:mentionable",
                },
            )
        assert request.headers["Authorization"] == "Bearer rotated-access"
        return httpx.Response(200, json={"data": {"viewer": {"id": "app-user-1"}}})

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(replace(_installation(), expires_at=time.time() - 1))
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        data = await client.graphql("org-1", "query Test { viewer { id } }", {})
    finally:
        await http.aclose()

    assert data["viewer"] == {"id": "app-user-1"}
    assert seen_refresh_form["grant_type"] == ["refresh_token"]
    assert seen_refresh_form["refresh_token"] == ["refresh"]
    refreshed = state.installation("org-1")
    assert refreshed is not None
    assert refreshed.access_token == "rotated-access"
    assert refreshed.refresh_token == "rotated-refresh"


class _FakeLinearClient:
    def __init__(self) -> None:
        self.activities: list[dict[str, Any]] = []

    async def create_activity(
        self,
        organization_id: str,
        agent_session_id: str,
        content: dict[str, Any],
        *,
        activity_id: str,
        ephemeral: bool = False,
    ) -> None:
        self.activities.append(
            {
                "organization_id": organization_id,
                "agent_session_id": agent_session_id,
                "content": content,
                "activity_id": activity_id,
                "ephemeral": ephemeral,
            }
        )


def _runtime(tmp_path: Path) -> tuple[LinearChannel, _FakeLinearClient]:
    channel = LinearChannel(_config(), MessageBus())
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(_installation())
    fake = _FakeLinearClient()
    channel._state = state  # pyright: ignore[reportPrivateUsage]
    channel._client = fake  # type: ignore[assignment]  # pyright: ignore[reportPrivateUsage]
    return channel, fake


@pytest.mark.asyncio
async def test_created_agent_session_publishes_only_the_mention_prompt(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    await channel._process_webhook("delivery-1", _agent_webhook())  # pyright: ignore[reportPrivateUsage]

    inbound = await channel.bus.consume_inbound()
    assert inbound.content == "please investigate this issue"
    assert inbound.sender_id == "user-1"
    assert inbound.chat_id == "session-1"
    assert inbound.session_key == "linear:org-1:session-1"
    assert inbound.metadata["linear"]["issue_id"] == "issue-1"
    assert client.activities[0]["content"] == {"type": "thought", "body": "Starting…"}


@pytest.mark.asyncio
async def test_prompted_stop_signal_becomes_priority_stop_command(tmp_path: Path) -> None:
    channel, _ = _runtime(tmp_path)
    await channel._process_webhook(  # pyright: ignore[reportPrivateUsage]
        "delivery-2",
        _agent_webhook(action="prompted", signal="stop"),
    )

    inbound = await channel.bus.consume_inbound()
    assert inbound.content == "/stop"
    assert inbound.metadata["linear"]["signal"] == "stop"


@pytest.mark.asyncio
async def test_app_authored_activity_is_not_echoed_back(tmp_path: Path) -> None:
    channel, _ = _runtime(tmp_path)
    payload = _agent_webhook(action="prompted")
    payload["agentActivity"]["userId"] = "app-user-1"

    await channel._process_webhook("delivery-3", payload)  # pyright: ignore[reportPrivateUsage]

    assert channel.bus.inbound.empty()


@pytest.mark.asyncio
async def test_outbound_response_and_tool_progress_use_native_activity_shapes(
    tmp_path: Path,
) -> None:
    channel, client = _runtime(tmp_path)
    metadata = {
        "linear": {
            "organization_id": "org-1",
            "agent_session_id": "session-1",
        }
    }
    response = OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="Done",
        metadata=metadata,
    )
    await channel.send(response)
    activity_id = client.activities[-1]["activity_id"]
    await channel.send(response)

    tool = OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="",
        metadata=metadata,
        event=ProgressEvent(
            tool_events=[{
                "phase": "end",
                "call_id": "call-1",
                "name": "linear_get_issue",
                "arguments": {"id": "issue-1"},
                "result": {"title": "Bug"},
            }]
        ),
    )
    await channel.send(tool)

    assert client.activities[0]["content"] == {"type": "response", "body": "Done"}
    assert client.activities[1]["activity_id"] == activity_id
    assert client.activities[2]["content"]["type"] == "action"
    assert client.activities[2]["content"]["action"] == "linear_get_issue"


def test_revocation_removes_workspace_installation(tmp_path: Path) -> None:
    channel, _ = _runtime(tmp_path)
    channel._process_lifecycle_event(  # pyright: ignore[reportPrivateUsage]
        {
            "type": "OAuthApp",
            "action": "revoked",
            "organizationId": "org-1",
        }
    )
    assert channel._state.installation("org-1") is None  # pyright: ignore[reportPrivateUsage]
