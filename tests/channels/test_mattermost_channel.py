"""Tests for the Mattermost channel implementation."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.mattermost import (
    MATTERMOST_MAX_MESSAGE_LEN,
    MattermostChannel,
    MattermostConfig,
)
from nanobot.pairing import PAIRING_CODE_META_KEY


class _FakeHTTPClient:
    """Mock httpx.AsyncClient that records calls and returns canned responses."""

    def __init__(self) -> None:
        self.get_calls: list[dict[str, Any]] = []
        self.post_calls: list[dict[str, Any]] = []
        self.put_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self._get_responses: dict[str, Any] = {}
        self._post_responses: dict[str, Any] = {}
        self._put_responses: dict[str, Any] = {}
        self._delete_status: int | None = None

    def _req(self, method: str, path: str) -> httpx.Request:
        return httpx.Request(method, f"https://chat.example.com{path}")

    def _resp(self, status: int, json_data: Any, method: str = "GET", path: str = "/") -> httpx.Response:
        return httpx.Response(status, json=json_data, request=self._req(method, path))

    def set_get_response(self, path: str, data: Any) -> None:
        self._get_responses[path] = data

    def set_post_response(self, path: str, data: Any) -> None:
        self._post_responses[path] = data

    def set_put_response(self, path: str, data: Any) -> None:
        self._put_responses[path] = data

    def set_delete_status(self, status: int) -> None:
        self._delete_status = status

    async def get(self, path: str, **kwargs) -> httpx.Response:
        self.get_calls.append({"path": path, **kwargs})
        data = self._get_responses.get(path, {"id": "resp_" + path.split("/")[-1]})
        return self._resp(200, data, "GET", path)

    async def post(self, path: str, *, json: dict[str, Any] | None = None, data: Any = None, files: Any = None, **kwargs) -> httpx.Response:
        call: dict[str, Any] = {"path": path}
        if json is not None:
            call["json"] = json
        if data is not None:
            call["data"] = data
        if files is not None:
            call["files"] = files
        self.post_calls.append(call)
        data = self._post_responses.get(path, {"id": "new_id"})
        return self._resp(201, data, "POST", path)

    async def put(self, path: str, *, json: dict[str, Any] | None = None, **kwargs) -> httpx.Response:
        self.put_calls.append({"path": path, "json": json})
        data = self._put_responses.get(path, {"id": path.split("/")[-1]})
        return self._resp(200, data, "PUT", path)

    async def delete(self, path: str, **kwargs) -> httpx.Response:
        self.delete_calls.append({"path": path})
        status = self._delete_status if self._delete_status is not None else 200
        return self._resp(status, {}, "DELETE", path)

    async def aclose(self) -> None:
        pass


def _make_channel(
    overrides: dict[str, Any] | None = None,
    bus: MessageBus | None = None,
) -> tuple[MattermostChannel, _FakeHTTPClient]:
    config_dict: dict[str, Any] = {
        "enabled": True,
        "serverUrl": "https://chat.example.com",
        "token": "test_token",
        **(overrides or {}),
    }
    config = MattermostConfig.model_validate(config_dict)
    if bus is None:
        bus = MessageBus()
    channel = MattermostChannel(config, bus)
    fake = _FakeHTTPClient()
    fake.set_get_response("/api/v4/users/me", {
        "id": "botuserid123",
        "username": "nanobot",
        "email": "bot@example.com",
    })
    fake.set_post_response("/api/v4/posts", {"id": "post_new_id"})
    channel._http_client = fake
    return channel, fake


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_config_defaults():
    config = MattermostConfig()
    assert config.enabled is False
    assert config.server_url == ""
    assert config.token == ""
    assert config.streaming is True
    assert config.streaming_max_chars == 16000
    assert config.dm.enabled is True
    assert config.dm.policy == "open"
    assert config.reply_in_thread is True


def test_config_camelcase_aliases():
    raw = {
        "serverUrl": "https://mm.example.com",
        "token": "abc123",
        "allowFromMatchMode": "username",
        "streamingMaxChars": 8000,
        "replyInThread": False,
    }
    config = MattermostConfig.model_validate(raw)
    assert config.server_url == "https://mm.example.com"
    assert config.token == "abc123"
    assert config.allow_from_match_mode == "username"
    assert config.streaming_max_chars == 8000
    assert config.reply_in_thread is False


def test_config_default_config_classmethod():
    d = MattermostChannel.default_config()
    assert d["enabled"] is False
    assert d["serverUrl"] == ""
    assert d["token"] == ""


# ---------------------------------------------------------------------------
# Self-identification on start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_identifies_bot():
    channel, fake = _make_channel({"serverUrl": "https://chat.example.com", "token": "tok"})
    calls_before = len(fake.get_calls)

    async def fake_listen_loop():
        while channel._running:
            await asyncio.sleep(0.01)

    with patch.object(channel, "_ws_listen_loop", fake_listen_loop):
        start_task = asyncio.create_task(channel.start())
        for _ in range(50):
            if channel._self_id:
                break
            await asyncio.sleep(0.01)

    assert channel._self_id == "botuserid123"
    assert channel._self_username == "nanobot"
    assert channel._self_email == "bot@example.com"
    assert not start_task.done()
    user_me_calls = [c for c in fake.get_calls[calls_before:] if "/api/v4/users/me" in c["path"]]
    assert len(user_me_calls) == 1
    await channel.stop()
    try:
        await start_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_start_missing_config():
    channel, fake = _make_channel({"serverUrl": "", "token": ""})
    await channel.start()
    assert channel._self_id is None


# ---------------------------------------------------------------------------
# Server URL normalization
# ---------------------------------------------------------------------------


def test_server_url_normalization():
    config = MattermostConfig.model_validate({
        "serverUrl": "https://chat.example.com/",
        "token": "tok",
    })
    channel = MattermostChannel(config, MessageBus())
    assert channel._server_url == "https://chat.example.com"
    assert "/api/v4/websocket" in channel._ws_url
    assert channel._ws_url.startswith("wss://")


def test_server_url_no_trailing_slash():
    config = MattermostConfig.model_validate({
        "serverUrl": "https://chat.example.com",
        "token": "tok",
    })
    channel = MattermostChannel(config, MessageBus())
    assert channel._server_url == "https://chat.example.com"


# ---------------------------------------------------------------------------
# Inbound routing: posted event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_posted_event_routes_to_handle_message():
    channel, fake = _make_channel()
    channel._self_id = "botuserid123"
    channel._self_username = "nanobot"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "id": "post_abc",
                    "user_id": "user_42",
                    "channel_id": "chan_1",
                    "message": "hello",
                    "root_id": "",
                }),
            },
            "broadcast": {"channel_id": "chan_1", "team_id": ""},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_awaited_once()
        args, kwargs = mock_handle.call_args
        assert kwargs["sender_id"] == "user_42"
        assert kwargs["chat_id"] == "chan_1"
        assert kwargs["content"] == "hello"
        assert kwargs["is_dm"] is True


@pytest.mark.asyncio
async def test_posted_event_self_message_ignored():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "id": "p1", "user_id": "bot_id",
                    "channel_id": "c1", "message": "ignore me", "root_id": "",
                }),
            },
            "broadcast": {},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_posted_event_channel_type_detection():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"

    for code, expected_dm in [("D", True), ("O", False), ("P", False), ("G", False)]:
        with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
            with patch.object(channel, "_should_respond_in_channel", return_value=True):
                with patch.object(channel, "_is_allowed", AsyncMock(return_value=True)):
                    ws_msg = {
                        "event": "posted",
                        "data": {
                            "channel_type": code,
                            "post": json.dumps({
                                "id": "p1", "user_id": "u1",
                                "channel_id": "c1", "message": "hi", "root_id": "",
                            }),
                        },
                        "broadcast": {},
                    }
                    await channel._handle_ws_message(ws_msg)
                    mock_handle.assert_called_once()
                    assert mock_handle.call_args[1]["is_dm"] == expected_dm


# ---------------------------------------------------------------------------
# Bot @mention stripping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strip_bot_mention_from_incoming():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    channel._self_username = "nanobot"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        with patch.object(channel, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(channel, "_should_respond_in_channel", return_value=True):
                ws_msg = {
                    "event": "posted",
                    "data": {
                        "channel_type": "O",
                        "post": json.dumps({
                            "id": "p1", "user_id": "u1",
                            "channel_id": "c1", "message": "@nanobot hello there", "root_id": "",
                        }),
                    },
                    "broadcast": {},
                }
                await channel._handle_ws_message(ws_msg)
                assert mock_handle.call_args[1]["content"] == "hello there"


# ---------------------------------------------------------------------------
# DM policy: open / allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_policy_open():
    channel, fake = _make_channel({"dm": {"policy": "open"}})
    result = await channel._is_allowed("any_user", "dm_chan", "dm")
    assert result is True


@pytest.mark.asyncio
async def test_dm_policy_allowlist_match():
    channel, fake = _make_channel({"dm": {"policy": "allowlist", "allowFrom": ["user_1", "user_2"]}})
    assert await channel._is_allowed("user_1", "dm_chan", "dm") is True
    assert await channel._is_allowed("user_3", "dm_chan", "dm") is False


@pytest.mark.asyncio
async def test_dm_disabled():
    channel, fake = _make_channel({"dm": {"enabled": False}})
    assert await channel._is_allowed("u1", "dm_chan", "dm") is False


# ---------------------------------------------------------------------------
# Group policy: mention / open / allowlist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_group_policy_mention():
    channel, fake = _make_channel({"groupPolicy": "mention"})
    channel._self_username = "nanobot"
    assert channel._should_respond_in_channel("hello", "c1") is False
    assert channel._should_respond_in_channel("@nanobot hello", "c1") is True


@pytest.mark.asyncio
async def test_group_policy_open():
    channel, fake = _make_channel({"groupPolicy": "open"})
    assert channel._should_respond_in_channel("anything", "c1") is True


@pytest.mark.asyncio
async def test_group_policy_allowlist():
    channel, fake = _make_channel({"groupPolicy": "allowlist", "groupAllowFrom": ["c1"]})
    assert channel._should_respond_in_channel("msg", "c1") is True
    assert channel._should_respond_in_channel("msg", "c2") is False


# ---------------------------------------------------------------------------
# Match mode: id / username / email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_mode_id():
    channel, fake = _make_channel({"allowFromMatchMode": "id", "allowFrom": ["u1", "u2"]})
    assert await channel._match_sender("u1", ["u1", "u2"]) is True
    assert await channel._match_sender("u3", ["u1", "u2"]) is False


@pytest.mark.asyncio
async def test_match_mode_username():
    channel, fake = _make_channel({"allowFromMatchMode": "username", "allowFrom": ["alice"]})
    fake.set_get_response("/api/v4/users/u1", {"id": "u1", "username": "alice", "email": "alice@x.com"})
    assert await channel._match_sender("u1", ["alice"]) is True
    assert await channel._match_sender("u2", ["alice"]) is False


@pytest.mark.asyncio
async def test_match_mode_email():
    channel, fake = _make_channel({"allowFromMatchMode": "email", "allowFrom": ["alice@x.com"]})
    fake.set_get_response("/api/v4/users/u1", {"id": "u1", "username": "alice", "email": "alice@x.com"})
    assert await channel._match_sender("u1", ["alice@x.com"]) is True
    assert await channel._match_sender("u2", ["alice@x.com"]) is False


# ---------------------------------------------------------------------------
# Identity cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_identity_cache_username():
    channel, fake = _make_channel({"allowFromMatchMode": "username", "allowFrom": ["alice"]})
    fake.set_get_response("/api/v4/users/u1", {"id": "u1", "username": "alice", "email": ""})

    calls_before = len(fake.get_calls)
    await channel._match_sender("u1", ["alice"])
    assert len(fake.get_calls) == calls_before + 1

    await channel._match_sender("u1", ["alice"])
    assert len(fake.get_calls) == calls_before + 1


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_creates_post():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    msg = OutboundMessage(
        channel="mattermost",
        chat_id="chan_1",
        content="hello world",
    )
    await channel.send(msg)
    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    assert len(posts) == 1
    assert posts[0]["json"]["channel_id"] == "chan_1"
    assert posts[0]["json"]["message"] == "hello world"


@pytest.mark.asyncio
async def test_send_with_file_upload():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    fake.set_post_response("/api/v4/files", {
        "file_infos": [{"id": "file_abc", "name": "test.txt"}],
    })

    with patch("nanobot.channels.mattermost.Path.exists", return_value=True):
        with patch("nanobot.channels.mattermost.Path.read_bytes", return_value=b"data"):
            msg = OutboundMessage(
                channel="mattermost",
                chat_id="chan_1",
                content="with file",
                media=["/tmp/test.txt"],
            )
            await channel.send(msg)

    file_uploads = [c for c in fake.post_calls if c["path"] == "/api/v4/files"]
    assert len(file_uploads) == 1

    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    assert len(posts) == 1
    assert posts[0]["json"]["file_ids"] == ["file_abc"]


@pytest.mark.asyncio
async def test_send_with_thread_root_id():
    channel, fake = _make_channel({"replyInThread": True})
    channel._self_id = "bot_id"
    msg = OutboundMessage(
        channel="mattermost",
        chat_id="chan_1",
        content="reply in thread",
        metadata={"mattermost": {"root_id": "root_42"}},
    )
    await channel.send(msg)
    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    assert len(posts) == 1
    assert posts[0]["json"]["root_id"] == "root_42"


@pytest.mark.asyncio
async def test_send_reaction_on_completion():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    msg = OutboundMessage(
        channel="mattermost",
        chat_id="chan_1",
        content="done",
        metadata={"message_id": "orig_post_1"},
    )
    await channel.send(msg)
    reactions = [c for c in fake.post_calls if c["path"] == "/api/v4/reactions"]
    assert len(reactions) == 1
    assert reactions[0]["json"]["emoji_name"] == "white_check_mark"


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_first_delta_creates_post():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    fake.set_post_response("/api/v4/posts", {"id": "stream_post_1"})

    await channel.send_delta("chan_1", "Hello", {"_stream_id": "s1"})
    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    assert len(posts) == 0
    assert channel._stream_buffers["s1"] == "Hello"
    assert channel._stream_committed["s1"] == "Hello"


@pytest.mark.asyncio
async def test_stream_subsequent_delta_edits_post():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    fake.set_post_response("/api/v4/posts", {"id": "stream_post_1"})

    await channel.send_delta("chan_1", "Hello", {"_stream_id": "s1"})
    assert channel._stream_buffers["s1"] == "Hello"

    await channel.send_delta("chan_1", " world", {"_stream_id": "s1"})
    edits = [c for c in fake.put_calls if c["path"] == "/api/v4/posts/stream_post_1"]
    assert len(edits) == 0
    assert channel._stream_buffers["s1"] == "Hello world"


@pytest.mark.asyncio
async def test_stream_end_adds_done_emoji():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    fake.set_post_response("/api/v4/posts", {"id": "stream_post_1"})

    await channel.send_delta("chan_1", "Hello", {"_stream_id": "s1"})
    await channel.send_delta("chan_1", "", {"_stream_id": "s1", "_stream_end": True})
    reactions = [c for c in fake.post_calls if c["path"] == "/api/v4/reactions" and c["json"]["emoji_name"] == "white_check_mark"]
    assert len(reactions) >= 1
    assert channel._stream_posts.get("s1") is None


@pytest.mark.asyncio
async def test_stream_chunk_boundary_finalizes_and_creates_new():
    channel, fake = _make_channel({"streamingMaxChars": 10})
    channel._self_id = "bot_id"
    fake.set_post_response("/api/v4/posts", {"id": "post_1"})

    await channel.send_delta("chan_1", "Hello ", {"_stream_id": "s1"})
    await channel.send_delta("chan_1", "world", {"_stream_id": "s1"})

    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    assert len(posts) == 0
    assert channel._stream_buffers["s1"] == "Hello world"


@pytest.mark.asyncio
async def test_stream_end_keyword_resuming_does_not_post_or_mark_done():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    await channel.send_delta("chan_1", "Working", stream_id="s1")

    await channel.send_delta(
        "chan_1",
        "",
        {"message_id": "orig_post_1"},
        stream_id="s1",
        stream_end=True,
        resuming=True,
    )

    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    reactions = [c for c in fake.post_calls if c["path"] == "/api/v4/reactions"]
    assert posts == []
    assert reactions == []
    assert "s1" not in channel._stream_buffers


@pytest.mark.asyncio
async def test_stream_end_failure_keeps_buffer_for_retry():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    await channel.send_delta("chan_1", "final answer", stream_id="s1")

    async def fail_create_post(*args, **kwargs):
        raise RuntimeError("network down")

    channel._create_post = fail_create_post
    with pytest.raises(RuntimeError):
        await channel.send_delta("chan_1", "", stream_id="s1", stream_end=True)

    assert channel._stream_buffers["s1"] == "final answer"
    assert channel._stream_committed["s1"] == "final answer"


@pytest.mark.asyncio
async def test_coalesced_stream_end_posts_inline_content():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    fake.set_post_response("/api/v4/posts", {"id": "stream_post_1"})

    await channel.send_delta(
        "chan_1",
        "coalesced final",
        {"mattermost": {"root_id": "root_1"}},
        stream_id="s1",
        stream_end=True,
    )

    posts = [c for c in fake.post_calls if c["path"] == "/api/v4/posts"]
    assert len(posts) == 1
    assert posts[0]["json"]["message"] == "coalesced final"
    assert posts[0]["json"]["root_id"] == "root_1"


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reaction_add_on_receipt():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    await channel._add_reaction("chan_1", "post_1", "eyes")
    reactions = [c for c in fake.post_calls if c["path"] == "/api/v4/reactions"]
    assert len(reactions) >= 1
    assert reactions[-1]["json"]["emoji_name"] == "eyes"


@pytest.mark.asyncio
async def test_reaction_remove():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    await channel._remove_reaction("post_1", "eyes")
    assert len(fake.delete_calls) >= 1
    assert "post_1" in fake.delete_calls[-1]["path"]
    assert "eyes" in fake.delete_calls[-1]["path"]


# ---------------------------------------------------------------------------
# Team filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_filtering_rejects_wrong_team():
    channel, fake = _make_channel({"teamId": "team_a"})
    channel._self_id = "bot_id"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "posted",
            "data": {
                "channel_type": "O",
                "post": json.dumps({
                    "id": "p1", "user_id": "u1",
                    "channel_id": "c1", "message": "hi", "root_id": "",
                }),
            },
            "broadcast": {"channel_id": "c1", "team_id": "team_b"},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_team_filtering_allows_correct_team():
    channel, fake = _make_channel({"teamId": "team_a"})
    channel._self_id = "bot_id"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        with patch.object(channel, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(channel, "_should_respond_in_channel", return_value=True):
                ws_msg = {
                    "event": "posted",
                    "data": {
                        "channel_type": "O",
                        "post": json.dumps({
                            "id": "p1", "user_id": "u1",
                            "channel_id": "c1", "message": "hi", "root_id": "",
                        }),
                    },
                    "broadcast": {"channel_id": "c1", "team_id": "team_a"},
                }
                await channel._handle_ws_message(ws_msg)
                mock_handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_team_filtering_dm_bypass():
    channel, fake = _make_channel({"teamId": "team_a"})
    channel._self_id = "bot_id"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "posted",
            "data": {
                "channel_type": "D",
                "post": json.dumps({
                    "id": "p1", "user_id": "u1",
                    "channel_id": "dm_chan", "message": "hi", "root_id": "",
                }),
            },
            "broadcast": {"channel_id": "dm_chan", "team_id": ""},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_awaited_once()


@pytest.mark.asyncio
async def test_team_filtering_resolves_missing_broadcast_team_and_rejects_wrong_team():
    channel, fake = _make_channel({"teamId": "team_a"})
    channel._self_id = "bot_id"
    fake.set_get_response("/api/v4/channels/c1", {
        "id": "c1",
        "type": "O",
        "team_id": "team_b",
    })
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "posted",
            "data": {
                "channel_type": "O",
                "post": json.dumps({
                    "id": "p1", "user_id": "u1",
                    "channel_id": "c1", "message": "hi", "root_id": "",
                }),
            },
            "broadcast": {"channel_id": "c1"},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_not_awaited()


# ---------------------------------------------------------------------------
# Thread session key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thread_session_key():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        with patch.object(channel, "_is_allowed", AsyncMock(return_value=True)):
            with patch.object(channel, "_should_respond_in_channel", return_value=True):
                ws_msg = {
                    "event": "posted",
                    "data": {
                        "channel_type": "O",
                        "post": json.dumps({
                            "id": "post_1", "user_id": "u1",
                            "channel_id": "c1", "message": "in thread",
                            "root_id": "root_99",
                        }),
                    },
                    "broadcast": {},
                }
                await channel._handle_ws_message(ws_msg)
                kwargs = mock_handle.call_args[1]
                assert kwargs["session_key"] == "mattermost:c1:root_99"


@pytest.mark.asyncio
async def test_top_level_mention_uses_thread_session_key():
    channel, fake = _make_channel({"replyInThread": True})
    channel._self_id = "bot_id"
    channel._self_username = "nanobot"
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        with patch.object(channel, "_is_allowed", AsyncMock(return_value=True)):
            ws_msg = {
                "event": "posted",
                "data": {
                    "channel_type": "O",
                    "post": json.dumps({
                        "id": "post_1", "user_id": "u1",
                        "channel_id": "c1", "message": "@nanobot start thread",
                        "root_id": "",
                    }),
                },
                "broadcast": {},
            }
            await channel._handle_ws_message(ws_msg)
            kwargs = mock_handle.call_args[1]
            assert kwargs["session_key"] == "mattermost:c1:post_1"
            assert kwargs["metadata"]["mattermost"]["thread_ts"] == "post_1"


# ---------------------------------------------------------------------------
# Action event (interactive buttons)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_event():
    channel, fake = _make_channel()
    channel._self_id = "bot_id"
    fake.set_get_response("/api/v4/channels/c1", {"id": "c1", "type": "O"})
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "action",
            "data": {
                "user_id": "u1",
                "channel_id": "c1",
                "context": {"selected_option": "Approve"},
            },
            "broadcast": {},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_awaited_once_with(
            sender_id="u1",
            chat_id="c1",
            content="Approve",
            metadata={"mattermost": {"channel_type": "public", "is_action": True}},
        )


@pytest.mark.asyncio
async def test_action_event_denied_dm():
    channel, fake = _make_channel({"dm": {"policy": "allowlist", "allowFrom": ["u_other"]}})
    channel._self_id = "bot_id"
    fake.set_get_response("/api/v4/channels/c1", {"id": "c1", "type": "D"})
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "action",
            "data": {
                "user_id": "u1",
                "channel_id": "c1",
                "context": {"selected_option": "Approve"},
            },
            "broadcast": {},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_event_rejects_wrong_team():
    channel, fake = _make_channel({"teamId": "team_a"})
    channel._self_id = "bot_id"
    fake.set_get_response("/api/v4/channels/c1", {
        "id": "c1",
        "type": "O",
        "team_id": "team_b",
    })
    with patch.object(channel, "_handle_message", AsyncMock()) as mock_handle:
        ws_msg = {
            "event": "action",
            "data": {
                "user_id": "u1",
                "channel_id": "c1",
                "context": {"selected_option": "Approve"},
            },
            "broadcast": {},
        }
        await channel._handle_ws_message(ws_msg)
        mock_handle.assert_not_awaited()


# ---------------------------------------------------------------------------
# Post deleted event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_deleted_cleans_stream_state():
    channel, fake = _make_channel()
    channel._stream_posts["s1"] = "del_post_1"
    channel._stream_posts["s2"] = "keep_post_2"

    ws_msg = {
        "event": "post_deleted",
        "data": {
            "channel_id": "c1",
            "post": json.dumps({"id": "del_post_1", "delete_at": 123}),
        },
        "broadcast": {},
    }
    await channel._handle_ws_message(ws_msg)
    assert "s1" not in channel._stream_posts
    assert channel._stream_posts["s2"] == "keep_post_2"


# ---------------------------------------------------------------------------
# Auth failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_failure_prevents_start():
    channel, fake = _make_channel()
    fake.set_get_response("/api/v4/users/me", {"id": "", "username": ""})
    with patch.object(fake, "get", side_effect=Exception("401 Unauthorized")):
        await channel.start()
        assert channel._self_id is None


# ---------------------------------------------------------------------------
# DM allowlist with match mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dm_allowlist_with_username_match():
    channel, fake = _make_channel({
        "allowFromMatchMode": "username",
        "dm": {"policy": "allowlist", "allowFrom": ["alice"]},
    })
    fake.set_get_response("/api/v4/users/u1", {"id": "u1", "username": "alice", "email": ""})
    assert await channel._is_allowed("u1", "dm_chan", "dm") is True
    assert await channel._is_allowed("u2", "dm_chan", "dm") is False


@pytest.mark.asyncio
async def test_dm_allowlist_accepts_pairing_approval():
    channel, fake = _make_channel({"dm": {"policy": "allowlist", "allowFrom": ["u_allowed"]}})
    with patch("nanobot.channels.mattermost.is_approved", return_value=True):
        assert await channel._is_allowed("u_paired", "dm_chan", "dm") is True


# ---------------------------------------------------------------------------
# Denied DM sends pairing code (not empty message)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_dm_sends_pairing_not_empty_inbound():
    channel, fake = _make_channel({"dm": {"policy": "allowlist", "allowFrom": ["u_allowed"]}})
    channel._self_id = "botuserid123"
    channel._self_username = "nanobot"

    ws_msg = {
        "event": "posted",
        "data": {
            "channel_type": "D",
            "post": json.dumps({
                "id": "p1", "user_id": "u_denied",
                "channel_id": "dm_chan", "message": "hello", "root_id": "",
            }),
        },
        "broadcast": {"channel_id": "dm_chan", "team_id": ""},
    }

    inbound_events = []
    channel.bus.publish_inbound = AsyncMock(side_effect=lambda e: inbound_events.append(e))

    with patch.object(channel, "send", AsyncMock()) as mock_send:
        await channel._handle_ws_message(ws_msg)
        mock_send.assert_awaited_once()
        sent = mock_send.call_args[0][0]
        assert sent.channel == "mattermost"
        assert sent.chat_id == "dm_chan"
        assert "pairing" in sent.content.lower() or "code" in sent.content.lower()
        assert PAIRING_CODE_META_KEY in (sent.metadata or {})

    assert len(inbound_events) == 0


# ---------------------------------------------------------------------------
# Bot mention boundary
# ---------------------------------------------------------------------------


def test_is_mentioned_exact():
    channel, fake = _make_channel({"groupPolicy": "mention"})
    channel._self_username = "nanobot"
    assert channel._is_mentioned("hello @nanobot how are you") is True
    assert channel._is_mentioned("hello @nanobotty") is False
    assert channel._is_mentioned("@nanobot_extra") is False
    assert channel._is_mentioned("plain text") is False


def test_is_mentioned_no_username():
    channel, fake = _make_channel({"groupPolicy": "mention"})
    channel._self_username = None
    assert channel._is_mentioned("hello @nanobot") is False


# ---------------------------------------------------------------------------
# split_message helper
# ---------------------------------------------------------------------------


def test_message_splitting():
    from nanobot.utils.helpers import split_message
    short = "short message"
    assert split_message(short, MATTERMOST_MAX_MESSAGE_LEN) == [short]

    long_text = "A" * (MATTERMOST_MAX_MESSAGE_LEN + 100)
    chunks = split_message(long_text, MATTERMOST_MAX_MESSAGE_LEN)
    assert all(len(c) <= MATTERMOST_MAX_MESSAGE_LEN for c in chunks)
    assert "".join(chunks) == long_text
