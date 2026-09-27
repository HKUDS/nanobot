"""Delayed network responses must not restore or overwrite workspace authorizations."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from nanobot.channels.linear import connect as linear_connect
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.state import LinearStateStore
from nanobot.channels.linear.tests.test_linear import _config, _installation, _runtime


@pytest.mark.parametrize("replacement", ["removed", "reauthorized", "same_tokens", "other_app"])
async def test_member_read_cannot_restore_or_overwrite_a_changed_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str,
) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    original = replace(_installation(), expires_at=0)
    state.save_installation(original)
    state.set_member_access("client-id", "org-1", "user-1", allowed=False)
    state.save_installation(replace(_installation(), organization_id="org-2"))
    entered, release = asyncio.Event(), asyncio.Event()
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/oauth/token":
            entered.set()
            await release.wait()
            return httpx.Response(200, json={
                "access_token": "late-access", "refresh_token": "late-refresh",
                "expires_in": 86400,
                "scope": "read write app:mentionable app:assignable",
            })
        if request.url.path == "/oauth/revoke":
            return httpx.Response(200)
        return httpx.Response(200, json={"data": {"teams": {
            "nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None},
        }}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
        monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: LinearStateStore(state.path))
        monkeypatch.setattr(linear_connect, "LinearClient", lambda config, store: LinearClient(config, store, http))
        api = linear_connect.LinearConnectStore()
        pending = asyncio.create_task(api.handle("start", {
            "operation": ["members"], "organization_id": ["org-1"],
        }))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            result = await api.handle("start", {
                "operation": ["disconnect"], "organization_id": ["org-1"],
            })
            assert [item["organization_id"] for item in result["installations"]] == ["org-2"]
            revoked_at = datetime.now(timezone.utc).isoformat()
            if replacement != "removed":
                state.save_installation(replace(
                    original,
                    access_token=original.access_token if replacement == "same_tokens" else "new-grant",
                    refresh_token=original.refresh_token if replacement == "same_tokens" else "new-refresh",
                    oauth_client_id="other-client" if replacement == "other_app" else "client-id",
                ), reauthorize=True)
                state.set_member_access(
                    "other-client" if replacement == "other_app" else "client-id",
                    "org-1", "user-1", allowed=False,
                )
            expected = state.installation("org-1")
            release.set()
            with pytest.raises(linear_connect.ChannelConnectError, match="authorization changed"):
                await pending
            assert "/graphql" not in requests  # Never use a discarded refresh result.
            assert LinearStateStore(state.path).installation("org-1") == expected
            assert state.installation("org-2") is not None
            if expected is None:
                assert state.member_access("client-id", "org-1", "user-1") is None
            else:
                assert state.member_access(expected.oauth_client_id, "org-1", "user-1") is False
            # The genuine removal notice can arrive after the network response.
            channel, _ = _runtime(tmp_path / "runtime")
            channel._state = state  # pyright: ignore[reportPrivateUsage]
            channel._process_lifecycle_event({  # pyright: ignore[reportPrivateUsage]
                "action": "revoked", "organizationId": "org-1", "createdAt": revoked_at,
            })
            assert state.installation("org-1") == expected
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)


async def test_late_refresh_cannot_overwrite_another_clients_rotation(tmp_path: Path) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(replace(_installation(), expires_at=0))
    state.set_member_access("client-id", "org-1", "user-1", allowed=False)
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    tokens_used: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        if request.url.path == "/oauth/token":
            count += 1
            number = count
            if number == 1:
                entered.set()
                await release.wait()
            return httpx.Response(200, json={
                "access_token": f"access-{number}", "refresh_token": f"refresh-{number}",
                "expires_in": 86400,
                "scope": "read write app:mentionable app:assignable",
            })
        tokens_used.append(request.headers["Authorization"])
        return httpx.Response(200, json={"data": {"viewer": {"id": "app-user-1"}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        first = LinearClient(_config(), LinearStateStore(state.path), http)
        second = LinearClient(_config(), LinearStateStore(state.path), http)
        pending = asyncio.create_task(first.graphql("org-1", "query Test { viewer { id } }", {}))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await second.graphql("org-1", "query Test { viewer { id } }", {})
            winner = state.installation("org-1")
            release.set()
            with pytest.raises(LinearApiError, match="authorization changed") as error:
                await pending
            assert error.value.retryable
            assert state.installation("org-1") == winner
            assert state.member_access("client-id", "org-1", "user-1") is False
            # Retrying reads the winner's credentials, without another rotation.
            await first.graphql("org-1", "query Test { viewer { id } }", {})
            assert count == 2
            assert tokens_used == ["Bearer access-2", "Bearer access-2"]
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)


async def test_normal_refresh_preserves_authorization_and_member_choices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    state.save_installation(replace(_installation(), expires_at=0))
    state.set_member_access("client-id", "org-1", "user-1", allowed=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={
                "access_token": "rotated", "refresh_token": "rotated-refresh",
                "expires_in": 86400,
                "scope": "read write app:mentionable app:assignable",
            })
        assert request.headers["Authorization"] == "Bearer rotated"
        return httpx.Response(200, json={"data": {"viewer": {"id": "app-user-1"}}})

    monkeypatch.setattr(time, "time", lambda: 2000.0)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await LinearClient(_config(), state, http).graphql("org-1", "query Test { viewer { id } }", {})
    reopened = LinearStateStore(state.path)
    rotated = reopened.installation("org-1")
    assert rotated is not None and rotated.access_token == "rotated"
    assert rotated.authorized_at == 1000.0
    assert reopened.member_access("client-id", "org-1", "user-1") is False
    # Refresh is not a new grant: a real revocation from before the refresh still wins.
    assert reopened.delete_installation("org-1", revoked_at=1500.0)


async def test_forced_refresh_does_not_use_a_different_apps_credentials(tmp_path: Path) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    state.save_installation(_installation())
    requests = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        # The app changed while an earlier API request was in flight.
        state.save_installation(replace(_installation(), oauth_client_id="other-app"))
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(LinearApiError, match="authorization changed"):
            await LinearClient(_config(), state, http).graphql("org-1", "query Test { viewer { id } }", {})
    assert requests == 1  # No refresh request with another app's token.


@pytest.mark.parametrize("replacement", ["reauthorized", "same_tokens", "other_app"])
async def test_delayed_disconnect_keeps_a_new_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str,
) -> None:
    state = LinearStateStore(tmp_path / "linear.sqlite3")
    original = _installation()
    state.save_installation(original)
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/revoke"
        entered.set()
        await release.wait()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
        monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: LinearStateStore(state.path))
        monkeypatch.setattr(linear_connect, "LinearClient", lambda config, store: LinearClient(config, store, http))
        pending = asyncio.create_task(linear_connect.LinearConnectStore().handle("start", {
            "operation": ["disconnect"], "organization_id": ["org-1"],
        }))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            client_id = "other-client" if replacement == "other_app" else "client-id"
            state.save_installation(replace(
                original, oauth_client_id=client_id,
                access_token=original.access_token if replacement == "same_tokens" else "new-grant",
                refresh_token=original.refresh_token if replacement == "same_tokens" else "new-refresh",
            ), reauthorize=True)
            state.set_member_access(client_id, "org-1", "user-1", allowed=False)
            expected = state.installation("org-1")
            release.set()
            with pytest.raises(linear_connect.ChannelConnectError, match="authorization changed") as error:
                await pending
            assert error.value.status == 409
            assert state.installation("org-1") == expected
            assert state.member_access(client_id, "org-1", "user-1") is False
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
