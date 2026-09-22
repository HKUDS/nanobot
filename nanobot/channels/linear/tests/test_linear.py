from __future__ import annotations

import asyncio
import hashlib
import hmac
import http.client
import json
import socket
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ContextCompactionEvent,
    ProgressEvent,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.linear import client as linear_client
from nanobot.channels.linear import connect as linear_connect
from nanobot.channels.linear import runtime as linear_runtime
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.config import LinearConfig, validate_public_base_url
from nanobot.channels.linear.oauth import OAUTH_FLOWS, authorization_url
from nanobot.channels.linear.runtime import LinearChannel
from nanobot.channels.linear.server import LinearServerLease, acquire_http_server
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
        scope=("read", "write", "app:mentionable", "app:assignable"),
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


def test_oauth_authorization_uses_app_actor_pkce_and_agent_scopes() -> None:
    flow = OAUTH_FLOWS.create()
    try:
        parsed = urlparse(authorization_url(_config(), flow))
        query = parsed.query
        assert parsed.scheme == "https"
        assert "actor=app" in query
        assert "code_challenge_method=S256" in query
        assert "app%3Amentionable" in query
        assert "app%3Aassignable" in query
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
    assert store.list_installations("client-id") == [installation, second_installation]
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
        body = response.read()
        connection.close()
        assert response.status == 200
        assert b"Authorization received" in body
        assert b"Linear connected" not in body
        assert flow.code == "authorization-code"
    finally:
        OAUTH_FLOWS.remove(flow)
        lease.close()


def test_oauth_callback_does_not_report_cancelled_authorization_as_connected(
    tmp_path: Path,
) -> None:
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
            f"/linear/oauth/callback?state={flow.state}&error=access_denied",
        )
        response = connection.getresponse()
        body = response.read()
        connection.close()
        assert response.status == 200
        assert b"Authorization not completed" in body
        assert b"Linear connected" not in body
        assert flow.error == "access_denied"
    finally:
        OAUTH_FLOWS.remove(flow)
        lease.close()


@pytest.mark.parametrize("concurrent", [False, True])
async def test_successful_authorization_survives_repeated_polls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, concurrent: bool,
) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    lease = Mock(spec=LinearServerLease)

    async def exchange_code(_code: str, _verifier: str) -> LinearInstallation:
        await asyncio.sleep(0)
        installation = _installation()
        state.save_installation(installation)
        return installation

    client = Mock(spec=LinearClient)
    client.exchange_code = AsyncMock(side_effect=exchange_code)
    client.close = AsyncMock()
    monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
    monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: state)
    monkeypatch.setattr(linear_connect, "LinearClient", lambda *_args: client)
    monkeypatch.setattr(linear_connect, "acquire_http_server", lambda *_args: lease)
    store = linear_connect.LinearConnectStore()
    started_at = time.monotonic()
    started = await store.handle("start", {})
    session_id = started["session_id"]
    query = {"session_id": [session_id]}
    oauth_state = parse_qs(urlparse(started["authorization_url"]).query)["state"][0]
    try:
        assert OAUTH_FLOWS.complete(oauth_state, code="authorization-code", error=None)
        if concurrent:
            first, repeated = await asyncio.gather(
                store.handle("poll", query), store.handle("poll", query),
            )
        else:
            first = await store.handle("poll", query)
            repeated = await store.handle("poll", query)
        assert first["status"] == "succeeded"
        assert repeated == first
        assert (await store.handle("poll", query)) == first
        assert state.has_installations("client-id")
        client.exchange_code.assert_awaited_once()
        lease.close.assert_called_once()
        assert (await store.handle("poll", {"session_id": ["unknown"]}))["status"] == "expired"

        monkeypatch.setattr(
            linear_connect, "time",
            SimpleNamespace(monotonic=lambda: started_at + linear_connect.FLOW_TTL_SECONDS + 10),
        )
        assert (await store.handle("poll", query))["status"] == "expired"
        assert state.has_installations("client-id")
    finally:
        await store.cancel(session_id)


@pytest.mark.asyncio
async def test_connect_store_lists_and_disconnects_workspaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    installation = _installation()
    state.save_installation(installation)
    monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
    monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: state)
    client = SimpleNamespace(revoke_installation=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(linear_connect, "LinearClient", lambda *_args: client)
    store = linear_connect.LinearConnectStore()

    inspected = await store.handle("start", {"operation": ["inspect"]})
    assert inspected["status"] == "inspected"
    assert inspected["installations"] == [{
        "organization_id": "org-1",
        "organization_name": "Example",
        "scopes": ["read", "write", "app:mentionable", "app:assignable"],
        "authorization_status": "authorized",
        "missing_scopes": [],
    }]

    disconnected = await store.handle(
        "start",
        {"operation": ["disconnect"], "organization_id": ["org-1"]},
    )
    assert disconnected["status"] == "disconnected"
    assert disconnected["installations"] == []
    assert state.installation("org-1") is None
    client.revoke_installation.assert_awaited_once_with(installation)

    state.save_installation(replace(_installation(), scope=("read", "write", "app:mentionable")))
    outdated = await store.handle("start", {"operation": ["inspect"]})
    assert outdated["installations"][0]["authorization_status"] == "missing_scopes"
    assert outdated["installations"][0]["missing_scopes"] == ["app:assignable"]


@pytest.mark.asyncio
async def test_disconnect_keeps_local_installation_when_revocation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    installation = _installation()
    state.save_installation(installation)
    monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
    monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: state)
    client = SimpleNamespace(
        revoke_installation=AsyncMock(side_effect=LinearApiError("network unavailable")),
        close=AsyncMock(),
    )
    monkeypatch.setattr(linear_connect, "LinearClient", lambda *_args: client)

    with pytest.raises(linear_connect.ChannelConnectError, match="Unable to revoke"):
        await linear_connect.LinearConnectStore().handle(
            "start",
            {"operation": ["disconnect"], "organization_id": ["org-1"]},
        )

    assert state.installation("org-1") == installation
    client.close.assert_awaited_once()


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
                    "scope": "read write app:mentionable app:assignable",
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
                    "scope": "read write app:mentionable app:assignable",
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


@pytest.mark.asyncio
async def test_client_uploads_attachment_with_linear_presigned_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment = tmp_path / "report.txt"
    attachment.write_text("report body", encoding="utf-8")
    seen_put = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_put
        if request.url.host == "api.linear.app":
            return httpx.Response(200, json={"data": {"fileUpload": {
                "success": True,
                "uploadFile": {
                    "uploadUrl": "https://uploads.linear.app/signed/report.txt",
                    "assetUrl": "https://uploads.linear.app/assets/report.txt",
                    "headers": [{"key": "x-upload-token", "value": "signed"}],
                },
            }}})
        seen_put = True
        assert request.content == b"report body"
        assert request.headers["x-upload-token"] == "signed"
        assert request.headers["content-type"].startswith("text/plain")
        assert request.headers["cache-control"] == "public, max-age=31536000"
        return httpx.Response(200)

    monkeypatch.setattr(linear_client, "validate_url_target", lambda _url: (True, ""))
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(_installation())
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        asset_url = await client.upload_file("org-1", attachment)
    finally:
        await http.aclose()

    assert seen_put is True
    assert asset_url == "https://uploads.linear.app/assets/report.txt"


@pytest.mark.asyncio
async def test_client_downloads_private_linear_attachment_with_workspace_token(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "uploads.linear.app"
        assert request.headers["Authorization"] == "Bearer access"
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"png")

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(_installation())
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        body, content_type = await client.download_file(
            "org-1", "https://uploads.linear.app/private/image"
        )
    finally:
        await http.aclose()

    assert body == b"png"
    assert content_type == "image/png"


@pytest.mark.asyncio
async def test_client_revokes_access_and_refresh_tokens_before_disconnect(
    tmp_path: Path,
) -> None:
    requests: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.linear.app/oauth/revoke"
        requests.append(parse_qs(request.content.decode()))
        return httpx.Response(200 if len(requests) == 1 else 400)

    state = LinearStateStore(tmp_path / "linear.sqlite3")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LinearClient(_config(), state, http)
    try:
        await client.revoke_installation(_installation())
    finally:
        await http.aclose()

    assert requests == [
        {"token": ["access"], "token_type_hint": ["access_token"]},
        {"token": ["refresh"], "token_type_hint": ["refresh_token"]},
    ]


class _FakeLinearClient:
    def __init__(self) -> None:
        self.activities: list[dict[str, Any]] = []
        self.downloads: list[str] = []

    async def create_activity(
        self,
        organization_id: str,
        agent_session_id: str,
        content: dict[str, Any],
        *,
        activity_id: str,
        ephemeral: bool = False,
        signal: str | None = None,
        signal_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.activities.append(
            {
                "organization_id": organization_id,
                "agent_session_id": agent_session_id,
                "content": content,
                "activity_id": activity_id,
                "ephemeral": ephemeral,
                "signal": signal,
                "signal_metadata": signal_metadata,
            }
        )

    async def upload_file(self, _organization_id: str, file_path: Path) -> str:
        return f"https://uploads.linear.app/{file_path.name}"

    async def download_file(
        self,
        _organization_id: str,
        url: str,
        *,
        max_bytes: int = linear_client.MAX_DOWNLOAD_BYTES,
    ) -> tuple[bytes, str]:
        self.downloads.append(url)
        if len(b"image") > max_bytes:
            raise LinearApiError("Linear attachment exceeds the download budget")
        return b"image", "image/png"


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
async def test_created_session_downloads_private_linear_attachments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel, client = _runtime(tmp_path)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr(linear_runtime, "get_media_dir", lambda _channel: media_dir)
    payload = _agent_webhook()
    payload["promptContext"] = (
        "Review ![checkout.png](https://uploads.linear.app/private/image-1)"
    )

    await channel._process_webhook("delivery-media", payload)  # pyright: ignore[reportPrivateUsage]

    inbound = await channel.bus.consume_inbound()
    assert client.downloads == ["https://uploads.linear.app/private/image-1"]
    assert len(inbound.media) == 1
    assert Path(inbound.media[0]).name == "delivery-media_checkout.png"
    assert Path(inbound.media[0]).read_bytes() == b"image"


@pytest.mark.asyncio
async def test_unpaired_session_does_not_download_private_attachments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel, client = _runtime(tmp_path)
    channel.config.allow_from = []
    monkeypatch.setattr(channel, "is_allowed", lambda _sender_id: False)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr(linear_runtime, "get_media_dir", lambda _channel: media_dir)
    payload = _agent_webhook()
    payload["promptContext"] = "Review https://uploads.linear.app/private/image-1"

    await channel._process_webhook("delivery-unpaired", payload)  # pyright: ignore[reportPrivateUsage]

    assert client.downloads == []
    assert list(media_dir.iterdir()) == []
    assert client.activities[0]["content"]["type"] == "response"
    assert "pairing" in client.activities[0]["content"]["body"].lower()


@pytest.mark.asyncio
async def test_inbound_attachments_share_one_total_download_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel, client = _runtime(tmp_path)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr(linear_runtime, "get_media_dir", lambda _channel: media_dir)
    monkeypatch.setattr(linear_runtime, "MAX_DOWNLOAD_BYTES", 7)
    payload = _agent_webhook()
    payload["promptContext"] = (
        "Review https://uploads.linear.app/private/one "
        "and https://uploads.linear.app/private/two"
    )

    await channel._process_webhook("delivery-budget", payload)  # pyright: ignore[reportPrivateUsage]

    inbound = await channel.bus.consume_inbound()
    assert len(inbound.media) == 1
    assert client.downloads == [
        "https://uploads.linear.app/private/one",
        "https://uploads.linear.app/private/two",
    ]
    assert "[Attachment unavailable: two]" in inbound.content


@pytest.mark.asyncio
async def test_inbound_attachments_enforce_the_count_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel, client = _runtime(tmp_path)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    monkeypatch.setattr(linear_runtime, "get_media_dir", lambda _channel: media_dir)
    monkeypatch.setattr(linear_runtime, "MAX_PROMPT_ATTACHMENTS", 1)
    payload = _agent_webhook()
    payload["promptContext"] = (
        "Review https://uploads.linear.app/private/one "
        "and https://uploads.linear.app/private/two"
    )

    await channel._process_webhook("delivery-count", payload)  # pyright: ignore[reportPrivateUsage]

    inbound = await channel.bus.consume_inbound()
    assert client.downloads == ["https://uploads.linear.app/private/one"]
    assert "[Only the first 1 attachments were accepted.]" in inbound.content


@pytest.mark.asyncio
async def test_prompted_stop_signal_becomes_priority_stop_command(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    channel.config.allow_from = []
    await channel._process_webhook(  # pyright: ignore[reportPrivateUsage]
        "delivery-2",
        _agent_webhook(action="prompted", signal="stop"),
    )

    inbound = await channel.bus.consume_inbound()
    assert inbound.content == "/stop"
    assert inbound.metadata["linear"]["signal"] == "stop"
    assert client.activities == []


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
    assert client.activities[2]["content"]["action"] == "Linear Get Issue"


@pytest.mark.asyncio
async def test_outbound_buttons_keep_media_in_linear_select_elicitation(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    attachment = tmp_path / "choice.png"
    attachment.write_bytes(b"png")
    await channel.send(OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="Choose a priority",
        media=[str(attachment)],
        buttons=[["High", "Low"]],
        metadata={
            "linear": {"organization_id": "org-1", "agent_session_id": "session-1"}
        },
    ))

    assert client.activities[0]["content"] == {
        "type": "elicitation",
        "body": (
            "Choose a priority\n\n"
            "![choice.png](https://uploads.linear.app/choice.png)"
        ),
    }
    assert client.activities[0]["signal"] == "select"
    assert client.activities[0]["signal_metadata"] == {
        "options": [
            {"label": "High", "value": "High"},
            {"label": "Low", "value": "Low"},
        ]
    }


@pytest.mark.asyncio
async def test_outbound_local_media_is_uploaded_and_linked(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    attachment = tmp_path / "diagram.png"
    attachment.write_bytes(b"png")
    await channel.send(OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="Here is the diagram.",
        media=[str(attachment)],
        metadata={
            "linear": {"organization_id": "org-1", "agent_session_id": "session-1"}
        },
    ))

    assert client.activities[0]["content"] == {
        "type": "response",
        "body": (
            "Here is the diagram.\n\n"
            "![diagram.png](https://uploads.linear.app/diagram.png)"
        ),
    }


@pytest.mark.asyncio
async def test_tool_activities_redact_credentials_and_make_start_ephemeral(
    tmp_path: Path,
) -> None:
    channel, client = _runtime(tmp_path)
    metadata = {
        "linear": {"organization_id": "org-1", "agent_session_id": "session-1"}
    }
    await channel.send(OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="",
        metadata=metadata,
        event=ProgressEvent(tool_events=[{
            "phase": "start",
            "call_id": "call-secret",
            "name": "call_api",
            "arguments": {"api_key": "secret-value", "query": "safe"},
        }]),
    ))
    await channel.send(OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="",
        metadata=metadata,
        event=ProgressEvent(tool_events=[{
            "phase": "error",
            "call_id": "call-secret",
            "name": "call_api",
            "error": "Authorization: Bearer plaintext-secret",
        }]),
    ))
    await channel.send(OutboundMessage(
        channel="linear",
        chat_id="session-1",
        content="",
        metadata=metadata,
        event=ProgressEvent(tool_events=[{
            "phase": "end",
            "call_id": "call-secret",
            "name": "call_api",
            "arguments": {"api_key": "secret-value"},
            "result": {"token": "result-secret", "status": "ok"},
        }]),
    ))

    assert client.activities[0]["ephemeral"] is True
    assert client.activities[0]["content"]["action"] == "Call API"
    assert "secret-value" not in client.activities[0]["content"]["parameter"]
    assert client.activities[1]["ephemeral"] is False
    assert "plaintext-secret" not in client.activities[1]["content"]["result"]
    assert "result-secret" not in client.activities[2]["content"]["result"]


@pytest.mark.parametrize(
    "value",
    [
        "token=plain-secret",
        "client_secret=plain-secret",
        "cookie=session-secret",
        "credential: plain-secret",
        "OPENAI_API_KEY=plain-secret",
    ],
)
def test_tool_result_text_redacts_common_credential_assignments(value: str) -> None:
    result = linear_runtime._compact_result(value)  # pyright: ignore[reportPrivateUsage]

    assert "plain-secret" not in result
    assert "session-secret" not in result
    assert "[redacted]" in result


@pytest.mark.asyncio
async def test_reasoning_can_be_hidden_for_linear(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    channel.config.show_reasoning = False
    metadata = {
        "linear": {"organization_id": "org-1", "agent_session_id": "session-1"}
    }

    await channel.send_reasoning_delta("session-1", "private thought", metadata)
    await channel.send_reasoning_end("session-1", metadata)

    assert client.activities == []


@pytest.mark.parametrize("include_start", [True, False])
@pytest.mark.parametrize("phase", ["succeeded", "failed", "cancelled"])
async def test_compaction_uses_temporary_progress_and_a_persistent_outcome(
    tmp_path: Path,
    include_start: bool,
    phase: Literal["succeeded", "failed", "cancelled"],
) -> None:
    channel, client = _runtime(tmp_path)
    metadata: dict[str, Any] = {
        "linear": {"organization_id": "org-1", "agent_session_id": "session-1"},
    }
    if include_start:
        await channel.send(outbound_message_for_event(
            channel="linear",
            chat_id="session-1",
            metadata=metadata,
            event=ContextCompactionEvent(compaction_id="compaction-1", phase="started"),
        ))
        assert client.activities[0]["content"] == {
            "type": "thought", "body": "Compressing context\u2026",
        }
        assert client.activities[0]["ephemeral"] is True

    outcome = outbound_message_for_event(
        channel="linear",
        chat_id="session-1",
        metadata=metadata,
        event=ContextCompactionEvent(compaction_id="compaction-1", phase=phase),
    )
    await channel.send(outcome)
    assert client.activities[-1]["content"] == {"type": "thought", "body": outcome.content}
    assert client.activities[-1]["ephemeral"] is False

    await channel.send(OutboundMessage(
        channel="linear", chat_id="session-1", content="Done", metadata=outcome.metadata,
    ))
    assert client.activities[-1]["content"] == {"type": "response", "body": "Done"}
    assert len({activity["activity_id"] for activity in client.activities}) == len(client.activities)


async def test_idle_compaction_does_not_reactivate_a_completed_agent_session(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    await channel._process_webhook("delivery-1", _agent_webhook())  # pyright: ignore[reportPrivateUsage]
    inbound = await channel.bus.consume_inbound()
    factory = TurnDeliveryFactory(channel.bus)
    session_metadata: dict[str, Any] = {}
    factory.create(inbound, inbound.session_key).remember_session_route(session_metadata)
    await channel.send(OutboundMessage(
        channel="linear", chat_id=inbound.chat_id, content="Done", metadata=inbound.metadata,
    ))
    activity_count = len(client.activities)

    idle_events = factory.session_events(inbound.session_key, session_metadata)
    for phase in ("started", "succeeded"):
        await idle_events.emit(ContextCompactionEvent(compaction_id="idle-1", phase=phase))
        await channel.send(await channel.bus.consume_outbound())

    assert len(client.activities) == activity_count
    assert client.activities[-1]["content"] == {"type": "response", "body": "Done"}


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
