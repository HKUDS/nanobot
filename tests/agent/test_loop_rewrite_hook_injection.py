"""Tests for CommandRewriteHook injection into AgentLoop._extra_hooks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.hooks.rewrite import CommandRewriteHook
from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import CommandRewriteConfig, ExecToolConfig


def _mk_loop(
    workspace: Path,
    *,
    command_rewrite: CommandRewriteConfig | None = None,
    exec_path_append: str = "",
) -> AgentLoop:
    bus = MagicMock()
    provider = MagicMock()
    provider.get_default_model.return_value = "dummy-model"
    provider.generation = MagicMock(max_tokens=4096)
    return AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        exec_config=ExecToolConfig(enable=False, path_append=exec_path_append),
        command_rewrite_config=command_rewrite,
    )


def _find_rewrite_hooks(loop: AgentLoop) -> list[CommandRewriteHook]:
    return [h for h in loop._extra_hooks if isinstance(h, CommandRewriteHook)]


def test_command_rewrite_disabled_not_injected(tmp_path: Path):
    """默认 / enabled=False 时 hook 不挂到 _extra_hooks。"""
    loop = _mk_loop(tmp_path, command_rewrite=CommandRewriteConfig())
    assert _find_rewrite_hooks(loop) == []
    assert loop._command_rewrite_hook is None


def test_command_rewrite_none_config_not_injected(tmp_path: Path):
    """不传 command_rewrite_config 时 hook 不挂。"""
    loop = _mk_loop(tmp_path, command_rewrite=None)
    assert _find_rewrite_hooks(loop) == []


def test_command_rewrite_enabled_injected(tmp_path: Path):
    """enabled=True 时 hook 进入 _extra_hooks 且配置从 CommandRewriteConfig + exec_config 继承。"""
    cfg = CommandRewriteConfig(enabled=True, verbose=True, timeout=7.5)
    loop = _mk_loop(tmp_path, command_rewrite=cfg, exec_path_append="/opt/rtk/bin")
    hooks = _find_rewrite_hooks(loop)
    assert len(hooks) == 1
    h = hooks[0]
    assert h._enabled is True
    assert h._verbose is True
    assert h._timeout == 7.5
    # path_append 从 ExecToolConfig 继承，保持与旧实现同等的 rtk 查找路径
    assert h._path_append == "/opt/rtk/bin"
