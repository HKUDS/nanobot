"""Tests for the inter-agent communication channel."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.channels.inter_agent import InterAgentChannel, InterAgentConfig, _is_final
from nanobot.bus.queue import MessageBus


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_default_config():
    cfg = InterAgentChannel.default_config()
    assert cfg["enabled"] is False
    assert cfg["apiPort"] == 18800
    assert cfg["instanceName"] == ""
    assert cfg["maxRoundsPerSession"] == 30


def test_config_from_dict():
    cfg = InterAgentConfig.model_validate({
        "enabled": True,
        "apiPort": 18804,
        "instanceName": "yanshifan",
        "auditWebhookUrl": "https://example.com/hook",
        "maxRoundsPerSession": 30,
    })
    assert cfg.enabled is True
    assert cfg.api_port == 18804
    assert cfg.instance_name == "yanshifan"


def test_config_camelcase():
    """Config must accept camelCase keys from JSON."""
    cfg = InterAgentConfig.model_validate({"apiPort": 18801, "instanceName": "zhangjuzheng"})
    assert cfg.api_port == 18801
    assert cfg.instance_name == "zhangjuzheng"


# ---------------------------------------------------------------------------
# Channel init
# ---------------------------------------------------------------------------

def test_channel_accepts_dict_config():
    bus = MessageBus()
    ch = InterAgentChannel({"enabled": True, "apiPort": 18802, "instanceName": "lvfang"}, bus)
    assert ch.config.api_port == 18802
    assert ch.config.instance_name == "lvfang"


def test_channel_accepts_config_object():
    bus = MessageBus()
    cfg = InterAgentConfig(enabled=True, api_port=18803, instance_name="zhuzaihou")
    ch = InterAgentChannel(cfg, bus)
    assert ch.config.instance_name == "zhuzaihou"


# ---------------------------------------------------------------------------
# _is_final
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("这是最终方案，请确认。", True),
    ("讨论结束，感谢合作。", True),
    ("达成共识，方案如下。", True),
    ("DISCUSSION_COMPLETE", True),
    ("discussion complete", True),
    ("consensus reached", True),
    ("final proposal accepted", True),
    ("已确认，无需修改。", True),
    ("我还有一些意见需要补充。", False),
    ("请继续讨论第三点。", False),
    ("", False),
])
def test_is_final(text, expected):
    assert _is_final(text) == expected


# ---------------------------------------------------------------------------
# HTTP handler: /inter-agent/health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_endpoint():
    bus = MessageBus()
    cfg = InterAgentConfig(enabled=True, api_port=18800, instance_name="xuejie")
    ch = InterAgentChannel(cfg, bus)

    mock_request = MagicMock()
    response = await ch._handle_health(mock_request)
    data = response.body
    import json
    body = json.loads(data)
    assert body["status"] == "ok"
    assert body["instance"] == "xuejie"
    assert body["port"] == 18800


# ---------------------------------------------------------------------------
# HTTP handler: /inter-agent/chat — validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_missing_fields():
    bus = MessageBus()
    ch = InterAgentChannel({"instanceName": "xuejie"}, bus)

    mock_request = AsyncMock()
    mock_request.json = AsyncMock(return_value={"message": "hello"})  # missing session_id
    response = await ch._handle_chat(mock_request)
    assert response.status == 400


@pytest.mark.asyncio
async def test_chat_invalid_json():
    bus = MessageBus()
    ch = InterAgentChannel({"instanceName": "xuejie"}, bus)

    mock_request = AsyncMock()
    mock_request.json = AsyncMock(side_effect=Exception("bad json"))
    response = await ch._handle_chat(mock_request)
    assert response.status == 400


# ---------------------------------------------------------------------------
# HTTP handler: /inter-agent/chat — full round trip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_round_trip():
    """Simulate a full request → agent response cycle."""
    bus = MessageBus()
    cfg = InterAgentConfig(enabled=True, api_port=18800, instance_name="xuejie")
    ch = InterAgentChannel(cfg, bus)

    mock_request = AsyncMock()
    mock_request.json = AsyncMock(return_value={
        "message": "请审阅方案",
        "session_id": "collab_test_001",
        "from_instance": "yanshifan",
        "round_count": 1,
    })

    # Simulate agent responding after a short delay
    async def fake_agent():
        await asyncio.sleep(0.05)
        from nanobot.bus.events import OutboundMessage
        await bus.publish_outbound(OutboundMessage(
            channel="inter_agent",
            chat_id="collab_test_001",
            content="方案已审阅，建议补充安全测评维度。",
        ))
        # Manually resolve the future (normally done by channel.send())
        from nanobot.channels.inter_agent import _pending
        fut = _pending.get("collab_test_001")
        if fut and not fut.done():
            fut.set_result("方案已审阅，建议补充安全测评维度。")

    with patch.object(ch, "_push_audit", new=AsyncMock()):
        task = asyncio.create_task(fake_agent())
        response = await ch._handle_chat(mock_request)
        await task

    import json
    body = json.loads(response.body)
    assert body["response"] == "方案已审阅，建议补充安全测评维度。"
    assert body["instance"] == "xuejie"
    assert body["session_id"] == "collab_test_001"
    assert body["is_final"] is False


# ---------------------------------------------------------------------------
# send() resolves pending future
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_resolves_future():
    from nanobot.channels.inter_agent import _pending
    from nanobot.bus.events import OutboundMessage

    bus = MessageBus()
    ch = InterAgentChannel({"instanceName": "xuejie"}, bus)

    loop = asyncio.get_event_loop()
    fut: asyncio.Future[str] = loop.create_future()
    _pending["test_session"] = fut

    await ch.send(OutboundMessage(
        channel="inter_agent",
        chat_id="test_session",
        content="审阅完毕，最终方案已确认。",
    ))

    assert fut.done()
    assert fut.result() == "审阅完毕，最终方案已确认。"
    assert "test_session" not in _pending
