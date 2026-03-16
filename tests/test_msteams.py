import json

import pytest

from nanobot.channels.msteams import MSTeamsChannel


class DummyBus:
    def __init__(self):
        self.inbound = []

    async def publish_inbound(self, msg):
        self.inbound.append(msg)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload=None):
        self.payload = payload or {"access_token": "tok", "expires_in": 3600}
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


@pytest.mark.asyncio
async def test_handle_activity_personal_message_publishes_and_stores_ref(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
        },
        bus,
    )

    activity = {
        "type": "message",
        "id": "activity-1",
        "text": "Hello from Teams",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "conv-123",
            "conversationType": "personal",
        },
        "from": {
            "id": "29:user-id",
            "aadObjectId": "aad-user-1",
            "name": "Bob",
        },
        "recipient": {
            "id": "28:bot-id",
            "name": "nanobot",
        },
        "channelData": {
            "tenant": {"id": "tenant-id"},
        },
    }

    await ch._handle_activity(activity)

    assert len(bus.inbound) == 1
    msg = bus.inbound[0]
    assert msg.channel == "msteams"
    assert msg.sender_id == "aad-user-1"
    assert msg.chat_id == "conv-123"
    assert msg.content == "Hello from Teams"
    assert msg.metadata["msteams"]["conversation_id"] == "conv-123"
    assert "conv-123" in ch._conversation_refs

    saved = json.loads((tmp_path / "state" / "msteams_conversations.json").read_text(encoding="utf-8"))
    assert saved["conv-123"]["conversation_id"] == "conv-123"
    assert saved["conv-123"]["tenant_id"] == "tenant-id"


@pytest.mark.asyncio
async def test_handle_activity_ignores_group_messages(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-id",
            "allowFrom": ["*"],
        },
        bus,
    )

    activity = {
        "type": "message",
        "id": "activity-2",
        "text": "Hello group",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "conversation": {
            "id": "conv-group",
            "conversationType": "channel",
        },
        "from": {
            "id": "29:user-id",
            "aadObjectId": "aad-user-1",
            "name": "Bob",
        },
        "recipient": {
            "id": "28:bot-id",
            "name": "nanobot",
        },
    }

    await ch._handle_activity(activity)

    assert bus.inbound == []
    assert ch._conversation_refs == {}


@pytest.mark.asyncio
async def test_get_access_token_uses_configured_tenant(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.channels.msteams.get_workspace_path", lambda: tmp_path)

    bus = DummyBus()
    ch = MSTeamsChannel(
        {
            "enabled": True,
            "appId": "app-id",
            "appPassword": "secret",
            "tenantId": "tenant-123",
            "allowFrom": ["*"],
        },
        bus,
    )

    fake_http = FakeHttpClient()
    ch._http = fake_http

    token = await ch._get_access_token()

    assert token == "tok"
    assert len(fake_http.calls) == 1
    url, kwargs = fake_http.calls[0]
    assert url == "https://login.microsoftonline.com/tenant-123/oauth2/v2.0/token"
    assert kwargs["data"]["client_id"] == "app-id"
    assert kwargs["data"]["client_secret"] == "secret"
    assert kwargs["data"]["scope"] == "https://api.botframework.com/.default"
