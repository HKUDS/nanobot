import json
from pathlib import Path

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Config


def _log_path(workspace: Path) -> Path:
    log_dir = workspace / ".nanobot-logs" / "Log"
    files = sorted(log_dir.glob("inbound_outbound-*.jsonl"))
    return files[-1]


def _log_files(workspace: Path) -> list[Path]:
    return sorted((workspace / ".nanobot-logs" / "Log").glob("inbound_outbound-*.jsonl"))


@pytest.mark.asyncio
async def test_inbound_outbound_log_disabled_by_default(tmp_path: Path) -> None:
    bus = MessageBus(workspace=tmp_path)

    # 默认关闭时不落盘，避免无感知地增长调试文件。
    await bus.publish_inbound(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="hello")
    )
    await bus.publish_outbound(OutboundMessage(channel="telegram", chat_id="c1", content="world"))

    assert not _log_files(tmp_path)


@pytest.mark.asyncio
async def test_inbound_outbound_log_writes_mixed_jsonl_in_time_order(tmp_path: Path) -> None:
    bus = MessageBus(workspace=tmp_path, inbound_outbound_log_enabled=True)

    await bus.publish_inbound(
        InboundMessage(
            channel="telegram",
            sender_id="u1",
            chat_id="c1",
            content="first-inbound",
            metadata={"msgId": 1},
        )
    )
    await bus.publish_outbound(
        OutboundMessage(
            channel="telegram",
            chat_id="c1",
            content="middle-outbound",
            metadata={"kind": "final"},
        )
    )
    await bus.publish_inbound(
        InboundMessage(channel="telegram", sender_id="u2", chat_id="c2", content="last-inbound")
    )

    lines = _log_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]

    assert len(records) == 3
    assert [record["direction"] for record in records] == ["inbound", "outbound", "inbound"]
    assert records[0]["message"]["content"] == "first-inbound"
    assert records[1]["message"]["content"] == "middle-outbound"
    assert records[2]["message"]["content"] == "last-inbound"
    assert "recordedAt" in records[0]
    assert "timestamp" in records[0]["message"]
    bus.close()


@pytest.mark.asyncio
async def test_inbound_outbound_log_uses_runtime_config_when_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = Config()
    cfg.agents.defaults.workspace = str(tmp_path)
    cfg.dispatch.inbound_outbound_log_enabled = True
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda: cfg)

    # 不显式传参时也应按配置开关写入日志。
    bus = MessageBus()
    await bus.publish_outbound(OutboundMessage(channel="telegram", chat_id="c1", content="ok"))

    records = [
        json.loads(line)
        for line in _log_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
    ]
    assert records[-1]["direction"] == "outbound"
    assert records[-1]["message"]["content"] == "ok"
    bus.close()


@pytest.mark.asyncio
async def test_inbound_outbound_log_splits_files_by_runtime_start(tmp_path: Path) -> None:
    first = MessageBus(workspace=tmp_path, inbound_outbound_log_enabled=True)
    await first.publish_inbound(
        InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="first-run")
    )
    first_path = first._inbound_outbound_log_path
    assert first_path is not None
    first.close()

    second = MessageBus(workspace=tmp_path, inbound_outbound_log_enabled=True)
    await second.publish_outbound(
        OutboundMessage(channel="telegram", chat_id="c1", content="second-run")
    )
    second_path = second._inbound_outbound_log_path
    assert second_path is not None
    second.close()

    assert first_path != second_path
    first_records = [
        json.loads(line) for line in first_path.read_text(encoding="utf-8").splitlines()
    ]
    second_records = [
        json.loads(line) for line in second_path.read_text(encoding="utf-8").splitlines()
    ]
    assert first_records[-1]["message"]["content"] == "first-run"
    assert second_records[-1]["message"]["content"] == "second-run"
