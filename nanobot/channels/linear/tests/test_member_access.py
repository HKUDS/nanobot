from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from nanobot.channels.linear import connect as linear_connect
from nanobot.channels.linear.access import member_allowed
from nanobot.channels.linear.client import LinearApiError, LinearClient
from nanobot.channels.linear.runtime import LinearPayloadError
from nanobot.channels.linear.state import LinearStateStore
from nanobot.channels.linear.tests.test_linear import (
    _agent_webhook,
    _config,
    _installation,
    _runtime,
)
from nanobot.pairing.store import approve_code, generate_code


@pytest.mark.parametrize("legacy", ["pairing", "allowlist", "wildcard", "none"])
def test_member_choice_overrides_legacy_and_survives_restart(tmp_path: Path, legacy: str) -> None:
    config = _config()
    config.allow_from = ["*"] if legacy == "wildcard" else ["user-1"] if legacy == "allowlist" else []
    if legacy == "pairing":
        approve_code(generate_code("linear", "user-1"))
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(_installation())
    assert member_allowed(config, state, "org-1", "user-1") is (legacy != "none")
    state.set_member_access(config.client_id, "org-1", "user-1", allowed=False)
    # A new legacy approval must not resurrect an explicit off switch.
    approve_code(generate_code("linear", "user-1"))
    reopened = LinearStateStore(state.path)
    assert not member_allowed(config, reopened, "org-1", "user-1")
    reopened.set_member_access(config.client_id, "org-1", "user-1", allowed=True)
    assert member_allowed(config, state, "org-1", "user-1")


def test_access_is_scoped_to_app_and_workspace(tmp_path: Path) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(_installation())
    state.save_installation(replace(_installation(), organization_id="org-2"))
    config = _config()
    config.allow_from = []
    state.set_member_access(config.client_id, "org-1", "user-1", allowed=True)
    assert not member_allowed(config, state, "org-2", "user-1")
    with pytest.raises(ValueError, match="not connected"):
        state.set_member_access("other-client", "org-1", "user-1", allowed=True)
    state.save_installation(replace(_installation(), oauth_client_id="other-client"))
    assert not member_allowed(config, state, "org-1", "user-1")
    state.delete_installation("org-1")
    assert not member_allowed(config, state, "org-1", "user-1")


def connection(nodes: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    return {"nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


async def test_directory_paginates_teams_and_members_filters_apps_and_deduplicates(tmp_path: Path) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(_installation())
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        variables = body["variables"]
        calls.append(variables)
        assert request.headers["Authorization"] == "Bearer access"
        if "NanobotMemberTeams" in body["query"]:
            teams = connection([{"id": "t1", "name": "One"}], "team-next") if not variables["after"] else connection([{"id": "t2", "name": "Two"}])
            return httpx.Response(200, json={"data": {"teams": teams}})
        assert "avatarUrl" in body["query"]
        human = {"id": "u1", "name": "Yongru", "active": True, "app": False,
                 "avatarUrl": "https://public.linear.app/u1/avatar"}
        if variables["team"] == "t1" and not variables["after"]:
            members = connection([human, {**human, "id": "bot", "app": True}], "member-next")
        elif variables["after"]:
            members = connection([{**human, "id": "inactive", "active": False}])
        else:
            members = connection([human])
        return httpx.Response(200, json={"data": {"team": {"members": members}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = LinearClient(_config(), state, http)
        assert await client.list_members("org-1") == [{
            "id": "u1", "name": "Yongru", "teams": ["One", "Two"],
            "avatar_url": "https://public.linear.app/u1/avatar",
        }]
    assert len(calls) == 5


async def test_filtered_lookup_sends_user_filter(tmp_path: Path) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    client = LinearClient(_config(), state)
    client.graphql = AsyncMock(side_effect=[
        {"teams": connection([{"id": "t1", "name": "Team"}])},
        {"team": {"members": connection([{"id": "u1", "name": "Yongru", "active": True, "app": False}])}},
    ])
    try:
        members = await client.list_members("org-1", user_id="u1")
        assert len(members) == 1
        assert members[0]["avatar_url"] is None
        assert client.graphql.call_args.args[2]["filter"] == {"id": {"eq": "u1"}}
    finally:
        await client.close()


@pytest.mark.parametrize("avatar", [None, 42, {"url": "unexpected"}])
async def test_directory_ignores_missing_or_invalid_avatars(tmp_path: Path, avatar: Any) -> None:
    client = LinearClient(_config(), LinearStateStore(tmp_path / "state.sqlite3"))
    client.graphql = AsyncMock(side_effect=[
        {"teams": connection([{"id": "t1", "name": "Team"}])},
        {"team": {"members": connection([
            {"id": "u1", "name": "Yongru", "active": True, "app": False, "avatarUrl": avatar},
        ])}},
    ])
    try:
        assert (await client.list_members("org-1"))[0]["avatar_url"] is None
    finally:
        await client.close()


@pytest.mark.parametrize("response", [
    {"teams": {"nodes": []}},
    {"teams": {"nodes": [], "pageInfo": {"hasNextPage": True, "endCursor": None}}},
    {"teams": connection([{"id": "t1"}])},
])
async def test_incomplete_directory_fails_closed(tmp_path: Path, response: dict[str, Any]) -> None:
    client = LinearClient(_config(), LinearStateStore(tmp_path / "state.sqlite3"))
    client.graphql = AsyncMock(return_value=response)
    try:
        with pytest.raises(LinearApiError):
            await client.list_members("org-1")
    finally:
        await client.close()


async def test_repeated_cursor_does_not_loop_or_return_partial_roster(tmp_path: Path) -> None:
    client = LinearClient(_config(), LinearStateStore(tmp_path / "state.sqlite3"))
    client.graphql = AsyncMock(return_value={"teams": connection([], "repeated")})
    try:
        with pytest.raises(LinearApiError, match="repeated"):
            await client.list_members("org-1")
        assert client.graphql.await_count == 2
    finally:
        await client.close()


async def test_member_management_reads_effective_access_and_saves_without_pairing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    config.allow_from = []
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(_installation())
    fake = AsyncMock()
    fake.list_members.return_value = [{"id": "user-1", "name": "Yongru", "teams": ["Team"],
                                       "avatar_url": "https://public.linear.app/user-1/avatar"}]
    monkeypatch.setattr(linear_connect, "_load_linear_config", lambda: config)
    monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: state)
    monkeypatch.setattr(linear_connect, "LinearClient", lambda *_args: fake)
    store = linear_connect.LinearConnectStore()
    params = {"operation": ["members"], "organization_id": ["org-1"]}
    assert (await store.handle("start", params))["members"][0]["allowed"] is False
    for value in ("true", "false"):
        result = await store.handle("start", {**params, "operation": ["member_access"], "user_id": ["user-1"], "allowed": [value]})
        assert result["status"] == "member_access_saved"
        assert result["members"][0]["allowed"] is (value == "true")
        assert result["members"][0]["avatar_url"] == "https://public.linear.app/user-1/avatar"
    assert not member_allowed(config, state, "org-1", "user-1")
    fake.close.assert_awaited()


@pytest.mark.parametrize("failure", ["unavailable", "out_of_scope", "invalid_boolean", "other_app"])
async def test_failed_management_does_not_grant_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    state = LinearStateStore(tmp_path / "state.sqlite3")
    state.save_installation(replace(_installation(), oauth_client_id="other" if failure == "other_app" else "client-id"))
    fake = AsyncMock()
    fake.list_members.return_value = []
    if failure == "unavailable":
        fake.list_members.side_effect = LinearApiError("Rate limited", retryable=True)
    monkeypatch.setattr(linear_connect, "_load_linear_config", _config)
    monkeypatch.setattr(linear_connect, "LinearStateStore", lambda: state)
    monkeypatch.setattr(linear_connect, "LinearClient", lambda *_args: fake)
    with pytest.raises(linear_connect.ChannelConnectError):
        await linear_connect.LinearConnectStore().handle("start", {
            "operation": ["member_access"], "organization_id": ["org-1"],
            "user_id": ["user-1"], "allowed": ["yes" if failure == "invalid_boolean" else "true"],
        })
    assert state.member_access("client-id", "org-1", "user-1") is None


async def test_enabled_member_can_run_without_pairing_and_disable_blocks_even_stop(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)
    channel.config.allow_from = []
    channel._state.set_member_access("client-id", "org-1", "user-1", allowed=True)
    await channel._process_webhook("enabled", _agent_webhook())
    inbound = await channel.bus.consume_inbound()
    assert inbound.sender_id == "user-1"
    assert inbound.session_key == "linear:org-1:session-1"
    channel._state.set_member_access("client-id", "org-1", "user-1", allowed=False)
    channel.config.allow_from = ["*"]
    approve_code(generate_code("linear", "user-1"))
    await channel._process_webhook("disabled", _agent_webhook())
    await channel._process_webhook("disabled-stop", _agent_webhook(action="prompted", signal="stop"))
    assert channel.bus.inbound.empty()
    assert "Access is disabled" in client.activities[-1]["content"]["body"]


@pytest.mark.parametrize("failure", ["departed", "api_error"])
async def test_admission_rechecks_membership_and_never_uses_stale_approvals(tmp_path: Path, failure: str) -> None:
    channel, client = _runtime(tmp_path)
    client.list_members = AsyncMock(return_value=[])
    expected = LinearPayloadError
    if failure == "api_error":
        client.list_members.side_effect = LinearApiError("Unavailable", retryable=True)
        expected = LinearApiError
    with pytest.raises(expected):
        await channel._process_webhook("no-access", _agent_webhook())
    assert channel.bus.inbound.empty()
    assert client.downloads == []
    assert client.activities == []


async def test_revocation_during_attachment_download_is_checked_before_publish(tmp_path: Path) -> None:
    channel, client = _runtime(tmp_path)

    async def revoke_during_download(*_args: Any, **_kwargs: Any) -> tuple[list[str], list[str]]:
        channel._state.set_member_access("client-id", "org-1", "user-1", allowed=False)
        return [], []

    channel._download_prompt_media = revoke_during_download
    await channel._process_webhook("race", _agent_webhook())
    assert channel.bus.inbound.empty()
