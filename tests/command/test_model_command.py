"""Tests for /model slash command handler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_model
from nanobot.command.router import CommandContext


# ── Mock AgentLoop ────────────────────────────────────────────

@dataclass
class MockLoop:
    """Minimal AgentLoop stand-in for command tests."""

    model: str = "anthropic/claude-opus-4-6"
    _config_model: str = "anthropic/claude-opus-4-6"
    _config_provider: Any = None
    _switch_called_with: str | None = None
    _switch_error: Exception | None = None
    _reset_called: bool = False

    def switch_model(self, model: str) -> str:
        if self._switch_error:
            raise self._switch_error
        self._switch_called_with = model
        self.model = model
        return model

    def reset_model(self) -> str:
        self._reset_called = True
        self.model = self._config_model
        return self._config_model


def _make_ctx(loop: MockLoop, args: str = "") -> CommandContext:
    msg = InboundMessage(channel="discord", sender_id="user", chat_id="ch1", content="/model")
    return CommandContext(msg=msg, session=None, key="discord:ch1", raw="/model", args=args, loop=loop)


# ── /model（无参数）— 显示状态 ────────────────────────────────

@pytest.mark.asyncio
async def test_model_show_status_default():
    """无参数 + 未 override → 显示 config default + 'using config default'。"""
    loop = MockLoop()
    resp = await cmd_model(_make_ctx(loop))
    assert "anthropic/claude-opus-4-6" in resp.content
    assert "using config default" in resp.content


@pytest.mark.asyncio
async def test_model_show_status_overridden():
    """model 被 override 后 → 显示 'overridden'。"""
    loop = MockLoop(model="anthropic/k2p5")
    resp = await cmd_model(_make_ctx(loop))
    assert "overridden" in resp.content
    assert "anthropic/k2p5" in resp.content


# ── /model <name> — 切换 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_model_switch_success():
    """/model some-model → 调用 switch_model → 返回 'switched to'。"""
    loop = MockLoop()
    resp = await cmd_model(_make_ctx(loop, args="anthropic/k2p5"))
    assert loop._switch_called_with == "anthropic/k2p5"
    assert "switched to" in resp.content.lower()


@pytest.mark.asyncio
async def test_model_switch_failure():
    """switch_model 抛异常 → 返回 'Failed to switch'。"""
    loop = MockLoop(_switch_error=ValueError("No provider configured"))
    resp = await cmd_model(_make_ctx(loop, args="bad/model"))
    assert "Failed to switch" in resp.content
    assert "No provider configured" in resp.content


# ── /model reset — 恢复默认 ──────────────────────────────────

@pytest.mark.asyncio
async def test_model_reset():
    """/model reset → 调用 reset_model → 返回 'reset to default'。"""
    loop = MockLoop(model="anthropic/k2p5")
    resp = await cmd_model(_make_ctx(loop, args="reset"))
    assert loop._reset_called
    assert "reset to default" in resp.content.lower()
    assert loop._config_model in resp.content


# ── fallback chain 状态显示 ──────────────────────────────────

@pytest.mark.asyncio
async def test_model_show_fallback_chain():
    """_config_provider 是 FallbackProvider → 显示 fallback chain。"""
    from nanobot.providers.fallback import FallbackProvider

    primary = MagicMock()
    fb1, fb2 = MagicMock(), MagicMock()
    fp = FallbackProvider(primary, [(fb1, "model-fb1"), (fb2, "model-fb2")])

    loop = MockLoop(_config_provider=fp)
    resp = await cmd_model(_make_ctx(loop))
    assert "model-fb1" in resp.content
    assert "model-fb2" in resp.content
    assert "Fallback chain" in resp.content


@pytest.mark.asyncio
async def test_model_show_cooldown():
    """FallbackProvider 在 cooldown → 显示 cooldown 警告。"""
    import time
    from nanobot.providers.fallback import FallbackProvider

    primary = MagicMock()
    fp = FallbackProvider(primary, [(MagicMock(), "fb-model")], cooldown_s=9999)
    fp._primary_failed_at = time.monotonic()  # 刚失败，在 cooldown 中

    loop = MockLoop(_config_provider=fp)
    resp = await cmd_model(_make_ctx(loop))
    assert "cooldown" in resp.content.lower()


# ── Discord slash command choices ─────────────────────────────

def test_build_model_choices():
    """验证 choices 列表包含所有模型 + reset 选项。"""
    from nanobot.command.discord_slash import _build_model_choices

    choices = _build_model_choices([
        "anthropic/claude-opus-4-6",
        "anthropic/k2p5",
        "openrouter_custom/anthropic/claude-sonnet-4-6",
    ])
    values = [c["value"] for c in choices]
    assert "anthropic/claude-opus-4-6" in values
    assert "anthropic/k2p5" in values
    assert "openrouter_custom/anthropic/claude-sonnet-4-6" in values
    assert "reset" in values

    # 显示名取最后一段
    names = [c["name"] for c in choices]
    assert "claude-opus-4-6" in names
    assert "k2p5" in names
    assert "claude-sonnet-4-6" in names


def test_build_model_choices_none():
    """model_choices=None → 只有 reset 选项。"""
    from nanobot.command.discord_slash import _build_model_choices

    choices = _build_model_choices(None)
    assert len(choices) == 1
    assert choices[0]["value"] == "reset"


def test_builtin_commands_include_model():
    """build_builtin_commands 包含 /model 命令。"""
    from nanobot.command.discord_slash import build_builtin_commands

    cmds = build_builtin_commands(model_choices=["m1", "m2"])
    model_cmds = [c for c in cmds if c["name"] == "model"]
    assert len(model_cmds) == 1
    assert model_cmds[0]["options"][0]["type"] == 3  # STRING
