from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.mattermost import MattermostChannel, MattermostConfig


class _FakeResponse:
    def __init__(self, payload: object, status_code: int = 200, request_url: str = "https://mm.example.com") -> None:
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request("POST", request_url)

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"http {self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class _FakeAsyncClient:
    def __init__(self) -> None:
        self.get_calls: list[dict[str, object]] = []
        self.post_calls: list[dict[str, object]] = []
        self.get_responses: list[_FakeResponse] = []
        self.post_responses: list[_FakeResponse] = []
        self.closed = False

    async def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        if not self.get_responses:
            raise AssertionError("No fake GET response queued")
        return self.get_responses.pop(0)

    async def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        if not self.post_responses:
            raise AssertionError("No fake POST response queued")
        return self.post_responses.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _make_channel(**kwargs) -> MattermostChannel:
    allow_from = kwargs.pop("allow_from", ["*"])
    config = MattermostConfig(
        enabled=True,
        server_url="https://mm.example.com",
        token="tok",
        allow_from=allow_from,
        **kwargs,
    )
    return MattermostChannel(config, MessageBus())


def _posted_payload(
    *,
    user_id: str = "user1",
    channel_id: str = "chan1",
    message: str = "hello",
    post_id: str = "post1",
    root_id: str = "",
    team_id: str | None = None,
) -> dict[str, object]:
    return {
        "event": "posted",
        "data": {
            "post": json.dumps(
                {
                    "id": post_id,
                    "user_id": user_id,
                    "channel_id": channel_id,
                    "message": message,
                    "root_id": root_id,
                    **({"team_id": team_id} if team_id is not None else {}),
                }
            )
        },
        "broadcast": {
            "channel_id": channel_id,
            **({"team_id": team_id} if team_id is not None else {}),
        },
    }


def test_default_config_returns_disabled_dict() -> None:
    cfg = MattermostChannel.default_config()
    assert isinstance(cfg, dict)
    assert cfg["enabled"] is False
    assert "serverUrl" in cfg
    assert "token" in cfg
    assert cfg["reactEmojiName"] == "star-struck"


def test_init_from_dict_validates_aliases() -> None:
    channel = MattermostChannel(
        {
            "enabled": True,
            "serverUrl": "https://mm.example.com",
            "token": "tok",
            "allowFrom": ["*"],
        },
        MessageBus(),
    )
    assert channel.config.server_url == "https://mm.example.com"
    assert channel.config.allow_from == ["*"]


@pytest.mark.asyncio
async def test_send_posts_basic_message() -> None:
    channel = _make_channel()
    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({"id": "post1"}, status_code=201))
    channel._client = fake

    await channel.send(OutboundMessage(channel="mattermost", chat_id="chan1", content="hello"))

    assert len(fake.post_calls) == 1
    call = fake.post_calls[0]
    assert call["url"].endswith("/api/v4/posts")
    assert call["json"] == {"channel_id": "chan1", "message": "hello"}


@pytest.mark.asyncio
async def test_send_includes_root_id_for_thread_reply() -> None:
    channel = _make_channel()
    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({"id": "post1"}, status_code=201))
    channel._client = fake

    await channel.send(
        OutboundMessage(
            channel="mattermost",
            chat_id="chan1",
            content="reply",
            metadata={"mattermost": {"root_id": "root123", "channel_type": "O"}},
        )
    )

    assert fake.post_calls[0]["json"]["root_id"] == "root123"


@pytest.mark.asyncio
async def test_send_uploads_files_before_creating_post(tmp_path: Path) -> None:
    media_file = tmp_path / "demo.txt"
    media_file.write_text("demo")

    channel = _make_channel()
    fake = _FakeAsyncClient()
    fake.post_responses.extend(
        [
            _FakeResponse({"file_infos": [{"id": "file1"}]}, status_code=201),
            _FakeResponse({"id": "post1"}, status_code=201),
        ]
    )
    channel._client = fake

    await channel.send(
        OutboundMessage(
            channel="mattermost",
            chat_id="chan1",
            content="hello",
            media=[str(media_file)],
        )
    )

    assert len(fake.post_calls) == 2
    upload_call = fake.post_calls[0]
    post_call = fake.post_calls[1]
    assert upload_call["url"].endswith("/api/v4/files")
    assert upload_call["data"] == {"channel_id": "chan1"}
    assert post_call["json"]["file_ids"] == ["file1"]


@pytest.mark.asyncio
async def test_posted_event_publishes_inbound_message_for_mention() -> None:
    channel = _make_channel(group_policy="mention")
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["chan1"] = "O"

    payload = {
        "event": "posted",
        "data": {
            "post": json.dumps(
                {
                    "id": "post1",
                    "user_id": "user1",
                    "channel_id": "chan1",
                    "message": "@nanobot hello",
                    "root_id": "",
                }
            )
        },
        "broadcast": {"channel_id": "chan1", "team_id": "team1"},
    }

    async def fake_build_sender_id(user_id: str, _data: dict[str, object], _post: dict[str, object]) -> str:
        return f"{user_id}|alice"

    channel._build_sender_id = fake_build_sender_id  # type: ignore[method-assign]

    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({}, status_code=201))
    channel._client = fake

    await channel._handle_websocket_message(json.dumps(payload))
    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1|alice"
    assert msg.chat_id == "chan1"
    assert msg.content == "hello"
    assert msg.metadata["mattermost"]["post_id"] == "post1"
    assert msg.metadata["mattermost"]["team_id"] == "team1"
    assert msg.session_key == "mattermost:chan1:post1"

    assert fake.post_calls[0]["url"].endswith("/api/v4/reactions")
    assert fake.post_calls[0]["json"] == {
        "user_id": "bot1",
        "post_id": "post1",
        "emoji_name": "star-struck",
    }


@pytest.mark.asyncio
async def test_posted_event_ignores_channel_message_without_mention() -> None:
    channel = _make_channel(group_policy="mention")
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["chan1"] = "O"

    fake = _FakeAsyncClient()
    channel._client = fake

    payload = {
        "event": "posted",
        "data": {
            "post": json.dumps(
                {
                    "id": "post1",
                    "user_id": "user1",
                    "channel_id": "chan1",
                    "message": "hello",
                }
            )
        },
        "broadcast": {"channel_id": "chan1", "team_id": "team1"},
    }

    await channel._handle_websocket_message(json.dumps(payload))
    assert channel.bus.inbound_size == 0
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_posted_event_respects_dm_policy_allowlist() -> None:
    channel = _make_channel(
        allow_from_match_mode="id",
        dm={"enabled": True, "policy": "allowlist", "allow_from": ["user1"]},
    )
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["dm1"] = "D"

    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({}, status_code=201))
    channel._client = fake

    allowed = _posted_payload(user_id="user1", channel_id="dm1")
    denied = _posted_payload(user_id="user2", channel_id="dm1", post_id="post2")

    await channel._handle_websocket_message(json.dumps(allowed))
    assert channel.bus.inbound_size == 1
    await channel.bus.consume_inbound()

    await channel._handle_websocket_message(json.dumps(denied))
    assert channel.bus.inbound_size == 0

    assert fake.post_calls[0]["url"].endswith("/api/v4/reactions")


@pytest.mark.asyncio
async def test_posted_event_respects_group_channel_allowlist() -> None:
    channel = _make_channel(group_policy="allowlist", group_allow_from=["chan1"])
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["chan1"] = "O"
    channel._channel_types["chan2"] = "O"

    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({}, status_code=201))
    channel._client = fake

    await channel._handle_websocket_message(json.dumps(_posted_payload(channel_id="chan1")))
    assert channel.bus.inbound_size == 1
    await channel.bus.consume_inbound()

    await channel._handle_websocket_message(json.dumps(_posted_payload(channel_id="chan2", post_id="post2")))
    assert channel.bus.inbound_size == 0

    assert fake.post_calls[0]["url"].endswith("/api/v4/reactions")


@pytest.mark.asyncio
async def test_group_channel_allowlist_does_not_block_dm() -> None:
    channel = _make_channel(
        group_policy="allowlist",
        group_allow_from=["chan1"],
        dm={"enabled": True, "policy": "open", "allow_from": []},
    )
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["dm1"] = "D"

    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({}, status_code=201))
    channel._client = fake

    await channel._handle_websocket_message(json.dumps(_posted_payload(channel_id="dm1")))
    assert channel.bus.inbound_size == 1
    assert fake.post_calls[0]["url"].endswith("/api/v4/reactions")


@pytest.mark.asyncio
async def test_is_dm_allowed_accepts_id_from_allowlist_in_id_mode() -> None:
    channel = _make_channel(
        allow_from_match_mode="id",
        dm={"enabled": True, "policy": "allowlist", "allow_from": ["user1"]},
    )

    assert await channel._is_dm_allowed("user1") is True
    assert await channel._is_dm_allowed("user2") is False


@pytest.mark.asyncio
async def test_is_dm_allowed_accepts_username_from_allowlist_in_username_mode() -> None:
    channel = _make_channel(
        allow_from_match_mode="username",
        dm={"enabled": True, "policy": "allowlist", "allow_from": ["alice"]},
    )

    async def fake_get_user_identity(user_id: str) -> dict[str, str | None]:
        return {"username": "alice", "email": None} if user_id == "user1" else {"username": "mallory", "email": None}

    channel._get_user_identity = fake_get_user_identity  # type: ignore[method-assign]

    assert await channel._is_dm_allowed("user1") is True
    assert await channel._is_dm_allowed("user2") is False


@pytest.mark.asyncio
async def test_is_dm_allowed_accepts_email_from_allowlist_in_email_mode() -> None:
    channel = _make_channel(
        allow_from_match_mode="email",
        dm={"enabled": True, "policy": "allowlist", "allow_from": ["alice@example.com"]},
    )

    async def fake_get_user_identity(user_id: str) -> dict[str, str | None]:
        return (
            {"username": "alice", "email": "alice@example.com"}
            if user_id == "user1"
            else {"username": "mallory", "email": "mallory@example.com"}
        )

    channel._get_user_identity = fake_get_user_identity  # type: ignore[method-assign]

    assert await channel._is_dm_allowed("user1") is True
    assert await channel._is_dm_allowed("user2") is False


def test_is_allowed_accepts_mattermost_id_and_username_formats() -> None:
    channel = _make_channel(allow_from=["user1"], allow_from_match_mode="id")

    assert channel.is_allowed("user1") is True
    assert channel.is_allowed("user9") is False


def test_is_allowed_accepts_username_in_username_mode() -> None:
    channel = _make_channel(allow_from=["alice"], allow_from_match_mode="username")

    assert channel.is_allowed("user1|alice") is True
    assert channel.is_allowed("user1|bob") is False


@pytest.mark.asyncio
async def test_is_allowed_accepts_email_in_email_mode() -> None:
    channel = _make_channel(allow_from=["alice@example.com"], allow_from_match_mode="email")

    async def fake_get_user_identity(user_id: str) -> dict[str, str | None]:
        assert user_id == "user1"
        return {"username": "alice", "email": "Alice@Example.com"}

    channel._get_user_identity = fake_get_user_identity  # type: ignore[method-assign]

    assert await channel._is_sender_allowed("user1") is True
    assert await channel._is_sender_allowed("user2") is False


@pytest.mark.asyncio
async def test_is_allowed_rejects_email_mode_when_email_missing() -> None:
    channel = _make_channel(allow_from=["alice@example.com"], allow_from_match_mode="email")

    async def fake_get_user_identity(_user_id: str) -> dict[str, str | None]:
        return {"username": "alice", "email": None}

    channel._get_user_identity = fake_get_user_identity  # type: ignore[method-assign]

    assert await channel._is_sender_allowed("user1") is False


def test_is_allowed_rejects_invalid_mattermost_sender_shapes() -> None:
    channel = _make_channel(allow_from=["alice"], allow_from_match_mode="username")

    assert channel.is_allowed("attacker|alice|extra") is False
    assert channel.is_allowed("|alice") is False
    assert channel.is_allowed("user1|") is False


@pytest.mark.asyncio
async def test_posted_event_ignores_self_message() -> None:
    channel = _make_channel(group_policy="open")
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["chan1"] = "O"

    fake = _FakeAsyncClient()
    channel._client = fake

    payload = {
        "event": "posted",
        "data": {
            "post": json.dumps(
                {
                    "id": "post1",
                    "user_id": "bot1",
                    "channel_id": "chan1",
                    "message": "hello",
                }
            )
        },
        "broadcast": {"channel_id": "chan1"},
    }

    await channel._handle_websocket_message(json.dumps(payload))
    assert channel.bus.inbound_size == 0
    assert fake.post_calls == []


@pytest.mark.asyncio
async def test_load_bot_identity_reads_users_me() -> None:
    channel = _make_channel()
    fake = _FakeAsyncClient()
    fake.get_responses.append(_FakeResponse({"id": "bot1", "username": "nanobot"}))
    channel._client = fake

    await channel._load_bot_identity()

    assert fake.get_calls[0]["url"].endswith("/api/v4/users/me")
    assert channel._bot_user_id == "bot1"
    assert channel._bot_username == "nanobot"


@pytest.mark.asyncio
async def test_build_sender_id_fetches_username_when_missing() -> None:
    channel = _make_channel()
    fake = _FakeAsyncClient()
    fake.get_responses.append(_FakeResponse({"id": "user1", "username": "alice"}))
    channel._client = fake

    sender_id = await channel._build_sender_id("user1", {}, {"user_id": "user1"})

    assert sender_id == "user1|alice"
    assert fake.get_calls[0]["url"].endswith("/api/v4/users/user1")


@pytest.mark.asyncio
async def test_build_sender_id_falls_back_to_user_id_when_username_lookup_fails() -> None:
    channel = _make_channel()

    async def fail_lookup(_user_id: str) -> str | None:
        raise RuntimeError("lookup failed")

    channel._get_username = fail_lookup  # type: ignore[method-assign]

    sender_id = await channel._build_sender_id("user1", {}, {"user_id": "user1"})

    assert sender_id == "user1"


@pytest.mark.asyncio
async def test_get_channel_type_fetches_and_caches_when_missing() -> None:
    channel = _make_channel()
    fake = _FakeAsyncClient()
    fake.get_responses.append(_FakeResponse({"id": "chan1", "type": "D"}))
    channel._client = fake

    first = await channel._get_channel_type("chan1", {})
    second = await channel._get_channel_type("chan1", {})

    assert first == "D"
    assert second == "D"
    assert len(fake.get_calls) == 1


@pytest.mark.asyncio
async def test_posted_event_reaction_failure_does_not_block_inbound_publish() -> None:
    channel = _make_channel(group_policy="open")
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"
    channel._channel_types["chan1"] = "O"

    fake = _FakeAsyncClient()
    fake.post_responses.append(_FakeResponse({}, status_code=400))
    channel._client = fake

    await channel._handle_websocket_message(json.dumps(_posted_payload(channel_id="chan1", message="hello")))

    assert channel.bus.inbound_size == 1


@pytest.mark.asyncio
async def test_posted_event_ignores_message_when_channel_type_lookup_fails() -> None:
    channel = _make_channel(group_policy="open")
    channel._bot_user_id = "bot1"
    channel._bot_username = "nanobot"

    fake = _FakeAsyncClient()
    channel._client = fake

    async def fail_lookup(_channel_id: str, _data: dict[str, object]) -> str:
        raise RuntimeError("lookup failed")

    channel._get_channel_type = fail_lookup  # type: ignore[method-assign]

    payload = {
        "event": "posted",
        "data": {
            "post": json.dumps(
                {
                    "id": "post1",
                    "user_id": "user1",
                    "channel_id": "chan1",
                    "message": "hello",
                }
            )
        },
        "broadcast": {"channel_id": "chan1"},
    }

    await channel._handle_websocket_message(json.dumps(payload))
    assert channel.bus.inbound_size == 0
    assert fake.post_calls == []
