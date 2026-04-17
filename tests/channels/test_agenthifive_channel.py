import asyncio

import pytest

from agenthifive_nanobot.types import VaultExecuteResult
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.agenthifive import AgentHiFiveChannel, AgentHiFiveConfig


class _FakeVaultClient:
    def __init__(self, execute_impl):
        self._execute_impl = execute_impl
        self.calls: list[dict] = []
        self.timeout = 10.0

    async def start(self) -> None:
        return None

    async def execute(self, payload: dict):
        self.calls.append(payload)
        return await self._execute_impl(payload)


@pytest.mark.asyncio
async def test_agenthifive_channel_forwards_telegram_updates(monkeypatch):
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "telegram": {
                    "enabled": True,
                }
            },
        }
    )
    channel = AgentHiFiveChannel(config, bus)

    async def _execute(_payload):
        await asyncio.sleep(0)
        return VaultExecuteResult(
            status_code=200,
            headers={},
            body={
                "ok": True,
                "result": [
                    {
                        "update_id": 101,
                        "message": {
                            "message_id": 55,
                            "chat": {"id": 8279370215, "type": "private"},
                            "from": {
                                "id": 8279370215,
                                "username": "supersantux",
                                "first_name": "Marco",
                            },
                            "text": "hello from telegram",
                        },
                    }
                ],
            },
            audit_id="audit_1",
        )

    monkeypatch.setattr(
        "nanobot.channels.agenthifive._build_agenthifive_vault_client",
        lambda: _FakeVaultClient(_execute),
    )

    task = asyncio.create_task(channel.start())
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    await channel.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert msg.channel == "agenthifive"
    assert msg.chat_id == "telegram:8279370215"
    assert msg.sender_id == "telegram:8279370215|supersantux"
    assert msg.content == "hello from telegram"
    assert msg.metadata["provider"] == "telegram"
    assert msg.metadata["message_id"] == 55


@pytest.mark.asyncio
async def test_agenthifive_channel_extends_timeout_for_telegram_long_poll(monkeypatch):
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "telegram": {
                    "enabled": False,
                }
            },
            "pollTimeoutS": 30,
        }
    )
    fake = _FakeVaultClient(lambda _payload: asyncio.sleep(0))
    channel = AgentHiFiveChannel(config, bus)

    monkeypatch.setattr(
        "nanobot.channels.agenthifive._build_agenthifive_vault_client",
        lambda: fake,
    )

    task = asyncio.create_task(channel.start())
    await asyncio.sleep(0)
    assert fake.timeout == 40.0
    await channel.stop()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_agenthifive_channel_sends_telegram_reply():
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "telegram": {
                    "enabled": True,
                }
            },
        }
    )
    sent_payloads: list[dict] = []

    async def _execute(payload):
        sent_payloads.append(payload)
        return VaultExecuteResult(
            status_code=200,
            headers={},
            body={"ok": True, "result": {"message_id": 77}},
            audit_id="audit_2",
        )

    channel = AgentHiFiveChannel(config, bus)
    channel._vault = _FakeVaultClient(_execute)

    await channel.send(
        OutboundMessage(
            channel="agenthifive",
            chat_id="telegram:8279370215:topic:42",
            content="hi back",
            metadata={"message_id": 55},
        )
    )

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["service"] == "telegram"
    assert payload["url"] == "https://api.telegram.org/bot/sendMessage"
    assert payload["body"]["chat_id"] == "8279370215"
    assert payload["body"]["message_thread_id"] == 42
    assert payload["body"]["reply_to_message_id"] == 55
    assert payload["body"]["text"] == "hi back"


def test_agenthifive_channel_formats_attachment_fallback_text():
    text = AgentHiFiveChannel._render_attachment_fallback_text(
        "I got the attachment.",
        ["/home/dev/.nanobot/media/agenthifive/report.pdf"],
    )

    assert "I got the attachment." in text
    assert "Attachment upload is not supported yet on the AgentHiFive channel." in text
    assert "- report.pdf: /home/dev/.nanobot/media/agenthifive/report.pdf" in text


@pytest.mark.asyncio
async def test_agenthifive_channel_falls_back_to_text_when_media_is_present():
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "slack": {
                    "enabled": True,
                }
            },
        }
    )
    sent_payloads: list[dict] = []

    async def _execute(payload):
        sent_payloads.append(payload)
        return VaultExecuteResult(
            status_code=200,
            headers={},
            body={"ok": True, "ts": "1712345688.000"},
            audit_id="audit_slack_send",
        )

    channel = AgentHiFiveChannel(config, bus)
    channel._vault = _FakeVaultClient(_execute)

    await channel.send(
        OutboundMessage(
            channel="agenthifive",
            chat_id="slack:C123",
            content="I downloaded the file for you.",
            media=["/home/dev/.nanobot/media/agenthifive/invoice.pdf"],
        )
    )

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["url"] == "https://slack.com/api/chat.postMessage"
    assert payload["body"]["text"] == (
        "I downloaded the file for you.\n"
        "Attachment upload is not supported yet on the AgentHiFive channel.\n"
        "The file was downloaded and saved locally:\n"
        "- invoice.pdf: /home/dev/.nanobot/media/agenthifive/invoice.pdf"
    )


@pytest.mark.asyncio
async def test_agenthifive_channel_forwards_slack_updates(monkeypatch):
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "slack": {
                    "enabled": True,
                }
            },
        }
    )
    channel = AgentHiFiveChannel(config, bus)
    calls: list[dict] = []

    async def _execute(payload):
        calls.append(payload)
        url = payload["url"]
        if "conversations.list" in url:
            return VaultExecuteResult(
                status_code=200,
                headers={},
                body={
                    "ok": True,
                    "channels": [
                        {
                            "id": "C123",
                            "is_channel": True,
                            "is_member": True,
                        }
                    ],
                },
                audit_id="audit_slack_list",
            )
        return VaultExecuteResult(
            status_code=200,
            headers={},
            body={
                "ok": True,
                "messages": [
                    {
                        "user": "U123",
                        "text": "hello from slack",
                        "ts": "1712345678.123",
                        "thread_ts": "1712345600.000",
                    }
                ],
            },
            audit_id="audit_slack_history",
        )

    monkeypatch.setattr(
        "nanobot.channels.agenthifive._build_agenthifive_vault_client",
        lambda: _FakeVaultClient(_execute),
    )

    task = asyncio.create_task(channel.start())
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    await channel.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert any("conversations.list" in call["url"] for call in calls)
    assert any("conversations.history" in call["url"] for call in calls)
    assert msg.channel == "agenthifive"
    assert msg.chat_id == "slack:C123:thread:1712345600.000"
    assert msg.sender_id == "slack:U123"
    assert msg.content == "hello from slack"
    assert msg.metadata["provider"] == "slack"
    assert msg.metadata["thread_ts"] == "1712345600.000"


@pytest.mark.asyncio
async def test_agenthifive_channel_retries_slack_discovery_without_missing_scope_types(monkeypatch):
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "slack": {
                    "enabled": True,
                }
            },
        }
    )
    channel = AgentHiFiveChannel(config, bus)
    calls: list[dict] = []
    list_calls = 0

    async def _execute(payload):
        nonlocal list_calls
        calls.append(payload)
        url = payload["url"]
        if "conversations.list" in url:
            list_calls += 1
            if list_calls == 1:
                return VaultExecuteResult(
                    status_code=200,
                    headers={},
                    body={
                        "ok": False,
                        "error": "missing_scope",
                        "needed": "groups:read",
                    },
                    audit_id="audit_slack_list_missing_scope",
                )
            return VaultExecuteResult(
                status_code=200,
                headers={},
                body={
                    "ok": True,
                    "channels": [
                        {
                            "id": "C123",
                            "is_channel": True,
                            "is_member": True,
                        }
                    ],
                },
                audit_id="audit_slack_list",
            )
        return VaultExecuteResult(
            status_code=200,
            headers={},
            body={
                "ok": True,
                "messages": [
                    {
                        "user": "U123",
                        "text": "hello from slack",
                        "ts": "1712345678.123",
                    }
                ],
            },
            audit_id="audit_slack_history",
        )

    monkeypatch.setattr(
        "nanobot.channels.agenthifive._build_agenthifive_vault_client",
        lambda: _FakeVaultClient(_execute),
    )

    task = asyncio.create_task(channel.start())
    msg = await asyncio.wait_for(bus.consume_inbound(), timeout=1.0)
    await channel.stop()
    await asyncio.wait_for(task, timeout=1.0)

    list_urls = [call["url"] for call in calls if "conversations.list" in call["url"]]
    assert len(list_urls) >= 2
    assert "private_channel" in list_urls[0]
    assert "private_channel" not in list_urls[1]
    assert msg.content == "hello from slack"


@pytest.mark.asyncio
async def test_agenthifive_channel_caches_slack_discovery(monkeypatch):
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "slack": {
                    "enabled": True,
                    "discoveryRefreshS": 300,
                }
            },
        }
    )
    channel = AgentHiFiveChannel(config, bus)
    list_calls = 0

    async def _execute(payload):
        nonlocal list_calls
        if "conversations.list" in payload["url"]:
            list_calls += 1
            return VaultExecuteResult(
                status_code=200,
                headers={},
                body={
                    "ok": True,
                    "channels": [
                        {
                            "id": "C123",
                            "is_channel": True,
                            "is_member": True,
                        }
                    ],
                },
                audit_id="audit_slack_list",
            )
        raise AssertionError("Unexpected Slack execute payload")

    current_time = 1000.0
    monkeypatch.setattr("nanobot.channels.agenthifive.time.monotonic", lambda: current_time)
    channel._vault = _FakeVaultClient(_execute)

    first = await channel._slack_get_channels()
    current_time += 60.0
    second = await channel._slack_get_channels()
    current_time += 301.0
    third = await channel._slack_get_channels()

    assert first == second == third
    assert list_calls == 2


def test_agenthifive_channel_scales_slack_sleep_by_channel_count():
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "slack": {
                    "enabled": True,
                    "targetRequestsPerHour": 180,
                }
            },
        }
    )
    channel = AgentHiFiveChannel(config, bus)

    assert channel._slack_cycle_sleep_s(0) == 15.0
    assert channel._slack_cycle_sleep_s(1) == 20.0
    assert channel._slack_cycle_sleep_s(3) == 60.0


@pytest.mark.asyncio
async def test_agenthifive_channel_sends_slack_reply():
    bus = MessageBus()
    config = AgentHiFiveConfig.model_validate(
        {
            "enabled": True,
            "providers": {
                "slack": {
                    "enabled": True,
                }
            },
        }
    )
    sent_payloads: list[dict] = []

    async def _execute(payload):
        sent_payloads.append(payload)
        return VaultExecuteResult(
            status_code=200,
            headers={},
            body={"ok": True, "ts": "1712345688.000"},
            audit_id="audit_slack_send",
        )

    channel = AgentHiFiveChannel(config, bus)
    channel._vault = _FakeVaultClient(_execute)

    await channel.send(
        OutboundMessage(
            channel="agenthifive",
            chat_id="slack:C123:thread:1712345600.000",
            content="hi slack",
        )
    )

    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload["service"] == "slack"
    assert payload["url"] == "https://slack.com/api/chat.postMessage"
    assert payload["body"]["channel"] == "C123"
    assert payload["body"]["thread_ts"] == "1712345600.000"
    assert payload["body"]["text"] == "hi slack"
