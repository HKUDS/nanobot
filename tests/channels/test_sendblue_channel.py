"""Tests for the Sendblue channel."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.channels.sendblue import (
    SENDBLUE_MAX_MESSAGE_LEN,
    SendblueChannel,
    SendblueConfig,
    SendblueProfileConfig,
    _ProfileRuntime,
)
from nanobot.config.loader import set_config_path
from nanobot.config.schema import Config


class _Response:
    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self) -> None:
        self.posts: list[dict] = []

    async def post(self, url, *, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return _Response()

    async def aclose(self):
        return None


def _channel(config: dict | None = None) -> SendblueChannel:
    set_config_path(Path(tempfile.mkdtemp()) / "config.json")
    cfg = {
        "enabled": True,
        "apiKeyId": "key-id",
        "apiSecretKey": "secret",
        "fromNumber": "+15550000000",
        "allowFrom": ["+15551111111"],
        "profiles": {
            "ron": {
                "phone": "+15551111111",
                "workspace": "~/.nanobot/profiles/ron",
                "composioUserId": "ron",
            }
        },
    }
    if config:
        cfg.update(config)
    ch = SendblueChannel(cfg, MagicMock())
    ch.set_root_config(Config.model_validate({
        "providers": {"custom": {"apiKey": "sk-test", "apiBase": "https://llm.example/v1"}},
        "agents": {"defaults": {"provider": "custom", "model": "test-model"}},
    }))
    ch._client = _Client()
    return ch


def test_sendblue_config_accepts_plan_shape():
    cfg = SendblueConfig.model_validate({
        "enabled": True,
        "host": "127.0.0.1",
        "port": 18791,
        "webhookPath": "/sendblue/webhook",
        "webhookSecret": "whsec",
        "apiKeyId": "id",
        "apiSecretKey": "secret",
        "fromNumber": "+15125550100",
        "typingIndicators": True,
        "allowFrom": ["+1"],
        "profiles": {
            "gf": {
                "phone": "+2",
                "workspace": "~/.nanobot/profiles/gf",
                "composioUserId": "gf",
            }
        },
    })

    assert cfg.webhook_path == "/sendblue/webhook"
    assert cfg.api_key_id == "id"
    assert cfg.profiles["gf"].composio_user_id == "gf"


@pytest.mark.asyncio
async def test_outbound_payload_uses_sendblue_auth_headers():
    ch = _channel()

    await ch.send(OutboundMessage(channel="sendblue", chat_id="+15551111111", content="hello"))

    assert ch._client.posts
    post = ch._client.posts[0]
    assert post["url"] == "https://api.sendblue.co/api/send-message"
    assert post["headers"]["sb-api-key-id"] == "key-id"
    assert post["headers"]["sb-api-secret-key"] == "secret"
    assert post["json"] == {
        "from_number": "+15550000000",
        "number": "+15551111111",
        "content": "hello",
    }


@pytest.mark.asyncio
async def test_outbound_long_response_is_split():
    ch = _channel()
    text = "x" * (SENDBLUE_MAX_MESSAGE_LEN + 10)

    await ch.send(OutboundMessage(channel="sendblue", chat_id="+15551111111", content=text))

    assert len(ch._client.posts) == 2
    assert len(ch._client.posts[0]["json"]["content"]) == SENDBLUE_MAX_MESSAGE_LEN
    assert len(ch._client.posts[1]["json"]["content"]) == 10


@pytest.mark.asyncio
async def test_typing_indicator_payload():
    ch = _channel()

    await ch.send_typing_indicator("+15551111111")

    post = ch._client.posts[0]
    assert post["url"] == "https://api.sendblue.co/api/send-typing-indicator"
    assert post["json"] == {
        "from_number": "+15550000000",
        "number": "+15551111111",
    }


@pytest.mark.asyncio
async def test_inbound_routes_to_matching_profile(tmp_path):
    set_config_path(tmp_path / "config.json")
    ch = _channel()
    fake_profile = SimpleNamespace(publish_inbound=AsyncMock())
    ch._profiles_by_phone["+15551111111"] = fake_profile

    await ch._handle_payload({
        "is_outbound": False,
        "status": "RECEIVED",
        "message_handle": "m1",
        "from_number": "+15551111111",
        "content": "hi",
    })

    fake_profile.publish_inbound.assert_awaited_once()
    msg = fake_profile.publish_inbound.await_args.args[0]
    assert msg.channel == "sendblue"
    assert msg.sender_id == "+15551111111"
    assert msg.session_key == "sendblue:+15551111111"
    assert msg.content == "hi"


@pytest.mark.asyncio
async def test_duplicate_message_handle_is_ignored(tmp_path):
    set_config_path(tmp_path / "config.json")
    ch = _channel()
    fake_profile = SimpleNamespace(publish_inbound=AsyncMock())
    ch._profiles_by_phone["+15551111111"] = fake_profile
    payload = {
        "is_outbound": False,
        "status": "RECEIVED",
        "message_handle": "m1",
        "from_number": "+15551111111",
        "content": "hi",
    }

    await ch._handle_payload(payload)
    await ch._handle_payload(payload)

    fake_profile.publish_inbound.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_sender_is_not_routed(tmp_path):
    set_config_path(tmp_path / "config.json")
    ch = _channel()
    ch._profiles_by_phone.clear()

    await ch._handle_payload({
        "is_outbound": False,
        "status": "RECEIVED",
        "message_handle": "m2",
        "from_number": "+15552222222",
        "content": "hi",
    })

    assert ch._client.posts == []


def test_composio_mcp_url_is_profile_specific():
    set_config_path(Path("/tmp/nanobot-sendblue-test/config.json"))
    cfg = Config.model_validate({
        "providers": {"custom": {"apiKey": "sk-test", "apiBase": "https://llm.example/v1"}},
        "agents": {"defaults": {"provider": "custom", "model": "test-model"}},
        "tools": {
            "composio": {
                "enabled": True,
                "apiKey": "cmp-key",
                "mcpServerId": "srv_123",
            }
        },
    })
    ch = SendblueChannel({
        "enabled": True,
        "apiKeyId": "key-id",
        "apiSecretKey": "secret",
        "fromNumber": "+15550000000",
        "allowFrom": ["+15551111111"],
    }, MagicMock())
    profile = SendblueProfileConfig(
        phone="+15551111111",
        workspace="/tmp/ron",
        composioUserId="ron",
    )
    runtime = _ProfileRuntime.__new__(_ProfileRuntime)
    runtime.profile_id = "ron"
    runtime.profile = profile
    runtime.root_config = cfg
    runtime.workspace = Path("/tmp/ron")

    profile_cfg = runtime._profile_config()

    server = profile_cfg.tools.mcp_servers["composio"]
    assert server.url == "https://backend.composio.dev/v3/mcp/srv_123?user_id=ron"
    assert server.headers == {"x-api-key": "cmp-key"}
