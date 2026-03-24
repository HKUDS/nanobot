import json

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.zzdingtalk import ZZDingTalkChannel, ZZDingTalkApiClient, ZZDingTalkConfig


class _FakeApiClient:
    """Fake API client that records calls and returns canned responses."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses or [])
        self._default = {"success": True}

    async def open(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def post(self, api_path: str, params: dict | None = None) -> dict | None:
        self.calls.append({"method": "POST", "path": api_path, "params": params})
        return self._responses.pop(0) if self._responses else self._default

    async def get(self, api_path: str, params: dict | None = None) -> dict | None:
        self.calls.append({"method": "GET", "path": api_path, "params": params})
        return self._responses.pop(0) if self._responses else self._default


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = json.dumps(self._json_body)

    def json(self) -> dict:
        return self._json_body


class _FakeHttp:
    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self.calls: list[dict] = []
        self._responses = list(responses or [])
        self._default = _FakeResponse(200, {"errcode": 0})

    async def post(self, url: str, json=None, headers=None, content=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "content": content})
        return self._responses.pop(0) if self._responses else self._default

    async def aclose(self):
        pass


def _make_channel(**overrides) -> tuple[ZZDingTalkChannel, MessageBus]:
    defaults = {
        "app_key": "test_key",
        "app_secret": "test_secret",
        "tenant_id": "tenant1",
    }
    defaults.update(overrides)
    config = ZZDingTalkConfig(**defaults)
    bus = MessageBus()
    channel = ZZDingTalkChannel(config, bus)
    return channel, bus


@pytest.mark.asyncio
async def test_get_access_token() -> None:
    channel, _ = _make_channel()
    channel._api = _FakeApiClient([
        {
            "success": True,
            "content": {"data": {"accessToken": "tok123", "expiresIn": 7200}},
        },
    ])

    token = await channel._get_access_token()
    assert token == "tok123"

    call = channel._api.calls[0]
    assert call["path"] == "/gettoken.json"
    assert call["params"]["appkey"] == "test_key"
    assert call["params"]["appsecret"] == "test_secret"


@pytest.mark.asyncio
async def test_get_access_token_caches() -> None:
    channel, _ = _make_channel()
    channel._api = _FakeApiClient([
        {
            "success": True,
            "content": {"data": {"accessToken": "tok123", "expiresIn": 7200}},
        },
    ])

    token1 = await channel._get_access_token()
    token2 = await channel._get_access_token()
    assert token1 == token2
    assert len(channel._api.calls) == 1


@pytest.mark.asyncio
async def test_send_chat_msg_single() -> None:
    channel, _ = _make_channel(sender_id="887707")
    channel._access_token = "tok"
    channel._token_expiry = 9999999999
    channel._api = _FakeApiClient()

    ok = await channel._send_chat_msg("user123", "hello")
    assert ok is True

    call = channel._api.calls[0]
    assert call["path"] == "/chat/sendMsg"
    params = call["params"]
    assert params["chatType"] == "1"
    assert params["receiverId"] == "user123"
    assert params["tenantId"] == "tenant1"
    assert params["senderId"] == "887707"
    msg = json.loads(params["msg"])
    assert msg["text"]["content"] == "hello"


@pytest.mark.asyncio
async def test_send_chat_msg_group() -> None:
    channel, _ = _make_channel()
    channel._access_token = "tok"
    channel._token_expiry = 9999999999
    channel._api = _FakeApiClient()

    ok = await channel._send_chat_msg("group:conv456", "hi group")
    assert ok is True

    call = channel._api.calls[0]
    params = call["params"]
    assert params["chatType"] == "2"
    assert params["chatId"] == "conv456"


@pytest.mark.asyncio
async def test_send_via_session_webhook() -> None:
    channel, _ = _make_channel()
    channel._http = _FakeHttp([
        _FakeResponse(200, {"errcode": 0}),
    ])

    ok = await channel._send_via_session_webhook("https://example.com/webhook", "reply")
    assert ok is True
    assert channel._http.calls[0]["json"]["text"]["content"] == "reply"


@pytest.mark.asyncio
async def test_send_via_session_webhook_error_falls_through() -> None:
    channel, _ = _make_channel()
    channel._http = _FakeHttp([
        _FakeResponse(500, {}),
    ])

    ok = await channel._send_via_session_webhook("https://example.com/webhook", "reply")
    assert ok is False


@pytest.mark.asyncio
async def test_config_defaults() -> None:
    config = ZZDingTalkConfig()
    assert config.domain == "https://openplatform.dg-work.cn"
    assert config.webhook_port == 9440
    assert config.webhook_path == "/zzdingtalk/webhook"
    assert config.webhook_integrated is True
    assert config.enabled is False


@pytest.mark.asyncio
async def test_config_from_dict() -> None:
    channel, _ = _make_channel()
    channel2 = ZZDingTalkChannel(
        {"enabled": True, "appKey": "k", "appSecret": "s", "tenantId": "t"},
        MessageBus(),
    )
    assert channel2.config.app_key == "k"
    assert channel2.config.app_secret == "s"
    assert channel2.config.tenant_id == "t"


@pytest.mark.asyncio
async def test_hmac_signature_generation() -> None:
    client = ZZDingTalkApiClient(
        domain="https://test.example.com",
        api_key="testkey",
        secret_key="testsecret",
    )
    headers = client._sign("POST", "/gettoken.json", {"appkey": "testkey"})

    assert "X-Hmac-Auth-Signature" in headers
    assert headers["apiKey"] == "testkey"
    assert "X-Hmac-Auth-Timestamp" in headers
    assert headers["X-Hmac-Auth-Version"] == "1.0"


@pytest.mark.asyncio
async def test_params_str_sorting() -> None:
    client = ZZDingTalkApiClient("https://x.com", "k", "s")
    result = client._build_params_str({"b": "2", "a": "1", "c": "3"})
    assert result == "a=1&b=2&c=3"
