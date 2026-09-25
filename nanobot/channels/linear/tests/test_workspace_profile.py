from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.channels.linear import connect as linear_connect
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.state import LinearStateStore
from nanobot.channels.linear.tests.test_linear import _config, _installation


@pytest.mark.parametrize("logo", [None, "https://public.linear.app/workspace/logo", 42, {"url": "bad"}])
async def test_workspace_profile_normalizes_optional_logo(
    tmp_path: Path, logo: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(_installation())
    client = LinearClient(_config(), state)
    query = AsyncMock(return_value={"organization": {"id": "org-1", "logoUrl": logo}})
    monkeypatch.setattr(client, "_graphql_with_token", query)
    try:
        assert await client.workspace_profile("org-1") == {
            "organization_id": "org-1", "logo_url": logo if isinstance(logo, str) else None,
        }
        assert query.call_args.args[0] == "access"
        assert "logoUrl" in query.call_args.args[1]
    finally:
        await client.close()


async def test_workspace_profile_rejects_different_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(_installation())
    client = LinearClient(_config(), state)
    monkeypatch.setattr(client, "_graphql_with_token", AsyncMock(return_value={"organization": {"id": "other"}}))
    try:
        with pytest.raises(LinearApiError, match="unexpected workspace"):
            await client.workspace_profile("org-1")
    finally:
        await client.close()


async def test_cosmetic_profile_does_not_rotate_expired_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    expired = replace(_installation(), expires_at=0)
    state.save_installation(expired)
    client = LinearClient(_config(), state)
    token_request = AsyncMock()
    monkeypatch.setattr(client, "_token_request", token_request)
    try:
        with pytest.raises(LinearApiError, match="No current"):
            await client.workspace_profile("org-1")
        token_request.assert_not_awaited()
        assert state.installation("org-1") == expired
    finally:
        await client.close()


@pytest.mark.parametrize("scenario", ["connected", "other_app", "disconnected", "api_error"])
async def test_profile_operation_is_scoped_and_never_changes_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str,
) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    installation = replace(_installation(), oauth_client_id="other" if scenario == "other_app" else "client-id")
    if scenario != "disconnected":
        state.save_installation(installation)
    fake = AsyncMock()
    fake.workspace_profile.return_value = {"organization_id": "org-1", "logo_url": None}
    if scenario == "api_error":
        fake.workspace_profile.side_effect = LinearApiError("Unavailable")
    monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
    monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: state)
    monkeypatch.setattr(linear_connect, "LinearClient", lambda *_args: fake)
    store = linear_connect.LinearConnectStore()
    params = {"operation": ["workspace_profile"], "organization_id": ["org-1"]}
    if scenario == "connected":
        assert await store.handle("start", params) == {
            "session_id": "", "status": "workspace_profile", "organization_id": "org-1", "logo_url": None,
        }
    else:
        with pytest.raises(linear_connect.ChannelConnectError):
            await store.handle("start", params)
    if scenario in {"connected", "api_error"}:
        fake.close.assert_awaited_once()
    else:
        fake.workspace_profile.assert_not_awaited()
    assert state.installation("org-1") == (None if scenario == "disconnected" else installation)
    assert state.member_access("client-id", "org-1", "user-1") is None


async def test_profile_requires_explicit_workspace() -> None:
    with pytest.raises(linear_connect.ChannelConnectError, match="missing Linear workspace"):
        await linear_connect.LinearConnectStore().handle("start", {"operation": ["workspace_profile"]})
