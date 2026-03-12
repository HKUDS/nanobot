from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.channels.base import BaseChannel
from nanobot.config.loader import _migrate_config, get_config_path, load_config, save_config
from nanobot.errors import (
    ContextOverflowError,
    MemoryConsolidationError,
    MemoryRetrievalError,
    ProviderAuthError,
    ProviderRateLimitError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
    ToolValidationError,
)


class _FakeBus:
    def __init__(self) -> None:
        self.messages = []

    async def publish_inbound(self, msg) -> None:
        self.messages.append(msg)


class _TestChannel(BaseChannel):
    name = "test"

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg) -> None:
        return None


def test_config_loader_roundtrip_and_migration(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    data = {"tools": {"exec": {"restrictToWorkspace": True}}}
    path.write_text(json.dumps(data), encoding="utf-8")

    cfg = load_config(path)
    assert cfg.tools.restrict_to_workspace is True

    cfg.tools.restrict_to_workspace = False
    save_config(cfg, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["tools"]["restrictToWorkspace"] is False

    migrated = _migrate_config(data)
    assert migrated["tools"]["restrictToWorkspace"] is True


def test_load_config_invalid_json_falls_back(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid", encoding="utf-8")

    cfg = load_config(bad)
    assert cfg.agents.defaults.model


def test_get_config_path_points_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert get_config_path() == tmp_path / ".nanobot" / "config.json"


@pytest.mark.asyncio
async def test_base_channel_allowlist_and_handle_message() -> None:
    cfg = SimpleNamespace(allow_from=["42", "abc"])
    bus = _FakeBus()
    ch = _TestChannel(cfg, bus)

    assert ch.is_allowed("42")
    assert ch.is_allowed("xyz|abc")
    assert not ch.is_allowed("999")

    await ch._handle_message(sender_id="42", chat_id="c1", content="hello")
    assert len(bus.messages) == 1
    assert bus.messages[0].content == "hello"

    await ch._handle_message(sender_id="nope", chat_id="c1", content="blocked")
    assert len(bus.messages) == 1

    await ch.start()
    assert ch.is_running
    await ch.stop()
    assert not ch.is_running


def test_error_types_and_fields() -> None:
    nf = ToolNotFoundError("x", ["a", "b"])
    assert "Tool 'x' not found" in str(nf)

    val = ToolValidationError("tool", ["bad a", "bad b"])
    assert val.validation_errors == ["bad a", "bad b"]

    tout = ToolTimeoutError("tool", 10)
    assert tout.timeout_seconds == 10

    perm = ToolPermissionError("tool", "denied")
    assert not perm.recoverable

    rate = ProviderRateLimitError("openai", retry_after=3.5)
    assert rate.status_code == 429
    assert rate.retry_after == 3.5

    auth = ProviderAuthError("openai")
    assert not auth.recoverable

    ctx = ContextOverflowError(100, 120)
    assert ctx.budget == 100 and ctx.actual == 120

    mem_r = MemoryRetrievalError("oops")
    mem_c = MemoryConsolidationError("oops2")
    assert mem_r.operation == "retrieval"
    assert mem_c.operation == "consolidation"
