"""Tests for discord UI components."""
from __future__ import annotations

import pytest

try:
    import discord
except ImportError:
    pytest.skip("discord.py not installed", allow_module_level=True)

from unittest.mock import AsyncMock, MagicMock

from nanobot.channels.discord_ui import (
    McpServerSelect,
    McpView,
    ModelPickerView,
    StatusView,
)


async def test_model_picker_view_has_provider_select():
    on_confirm = AsyncMock()
    view = ModelPickerView(providers=[("anthropic", "Anthropic"), ("openai", "OpenAI")], on_confirm=on_confirm)
    # Has at least one item (ProviderSelect) + one button
    assert len(view.children) >= 2
    # Timeout is 600s
    assert view.timeout == 600.0


async def test_model_picker_confirm_without_selection_sends_error():
    on_confirm = AsyncMock()
    view = ModelPickerView(providers=[("anthropic", "Anthropic")], on_confirm=on_confirm)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    # Find and call the confirm button callback directly
    button = next(item for item in view.children if isinstance(item, discord.ui.Button))
    await button.callback(interaction)
    interaction.response.send_message.assert_called_once()
    args, kwargs = interaction.response.send_message.call_args
    assert kwargs.get("ephemeral") is True
    on_confirm.assert_not_called()


async def test_stop_button_triggers_callback():
    on_stop = AsyncMock()
    # Use a real StatusView so the button has a proper parent
    view = StatusView(on_stop=on_stop)
    button = next(item for item in view.children if isinstance(item, discord.ui.Button))

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.message.edit = AsyncMock()

    await button.callback(interaction)

    # Verify defer called, button disabled, and stop callback invoked
    interaction.response.defer.assert_called_once_with(ephemeral=True)
    assert button.disabled is True
    on_stop.assert_called_once()


async def test_mcp_view_with_empty_servers():
    view = McpView(servers=[])
    assert len(view.children) == 1
    select = view.children[0]
    assert isinstance(select, McpServerSelect)
    assert select.disabled is True


async def test_mcp_view_with_servers():
    view = McpView(servers=["server1", "server2"])
    select = view.children[0]
    assert isinstance(select, McpServerSelect)
    assert select.disabled is False
    assert len(select.options) == 2
