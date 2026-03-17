"""Tests for the TUI channel (nanobot/channels/tui.py)."""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from a string."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.tui import TuiChannel, TuiConfig, _to_ansi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_channel(allow_from: list[str] | None = None) -> TuiChannel:
    cfg = TuiConfig(enabled=True, allow_from=allow_from or ["*"])
    return TuiChannel(cfg, MessageBus())


def _outbound(content: str, **meta) -> OutboundMessage:
    return OutboundMessage(channel="tui", chat_id="tui", content=content, metadata=meta)


def _patch_start_env():
    """Shared context managers that suppress all terminal I/O in start() tests."""
    return (
        patch("nanobot.channels.tui.Console"),
        patch("nanobot.channels.tui.patch_stdout"),
        patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock),
    )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_tui_config_defaults():
    cfg = TuiConfig()
    assert cfg.enabled is False
    assert cfg.allow_from == ["local_user"]
    assert cfg.user_id == "local_user"


def test_tui_config_from_camel_dict():
    cfg = TuiConfig.model_validate({"enabled": True, "allowFrom": ["*"], "userId": "admin"})
    assert cfg.enabled is True
    assert cfg.allow_from == ["*"]
    assert cfg.user_id == "admin"


def test_default_config_keys():
    d = TuiChannel.default_config()
    assert isinstance(d, dict)
    assert d["enabled"] is False
    assert "allowFrom" in d
    assert "userId" in d


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def test_init_from_dict():
    ch = TuiChannel({"enabled": True, "allowFrom": ["*"]}, MessageBus())
    assert ch.config.enabled is True
    assert ch.config.allow_from == ["*"]
    assert ch._chat_id == "tui"
    assert ch._session_counter == 0
    assert ch._loading_task is None
    assert ch._response_done.is_set()


def test_init_from_config_object():
    cfg = TuiConfig(enabled=True, allow_from=["user1"])
    ch = TuiChannel(cfg, MessageBus())
    assert ch.config is cfg


def test_channel_name_and_display():
    assert TuiChannel.name == "tui"
    assert TuiChannel.display_name == "TUI"


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_sets_running_false():
    ch = _make_channel()
    ch._running = True
    await ch.stop()
    assert ch._running is False


@pytest.mark.asyncio
async def test_stop_sets_response_done():
    ch = _make_channel()
    ch._response_done.clear()
    await ch.stop()
    assert ch._response_done.is_set()


# ---------------------------------------------------------------------------
# _to_ansi
# ---------------------------------------------------------------------------

def test_to_ansi_returns_string():
    result = _to_ansi(lambda c: c.print("hello"))
    assert isinstance(result, str)
    assert len(result) > 0


def test_to_ansi_contains_rendered_content():
    result = _to_ansi(lambda c: c.print("hello world"))
    assert "hello world" in result


def test_to_ansi_contains_escape_codes():
    """force_terminal=True should produce ANSI escape sequences."""
    result = _to_ansi(lambda c: c.print("[bold]bold text[/bold]"))
    assert "\x1b[" in result


# ---------------------------------------------------------------------------
# _dispatch_command — return value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_stop_returns_true():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        assert await ch._dispatch_command("/stop") is True


@pytest.mark.asyncio
async def test_dispatch_exit_returns_true():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        assert await ch._dispatch_command("/exit") is True


@pytest.mark.asyncio
async def test_dispatch_quit_returns_true():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        assert await ch._dispatch_command("/quit") is True


@pytest.mark.asyncio
async def test_dispatch_help_returns_false():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        assert await ch._dispatch_command("/help") is False


@pytest.mark.asyncio
async def test_dispatch_clear_returns_false():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        assert await ch._dispatch_command("/clear") is False


@pytest.mark.asyncio
async def test_dispatch_unknown_returns_false():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        assert await ch._dispatch_command("/foobar") is False


# ---------------------------------------------------------------------------
# _dispatch_command — /new side-effects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_new_increments_session_counter():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch._dispatch_command("/new")
    assert ch._session_counter == 1
    assert ch._chat_id == "tui-1"


@pytest.mark.asyncio
async def test_dispatch_new_increments_each_call():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch._dispatch_command("/new")
        await ch._dispatch_command("/new")
        await ch._dispatch_command("/new")
    assert ch._session_counter == 3
    assert ch._chat_id == "tui-3"


@pytest.mark.asyncio
async def test_dispatch_new_chat_id_format():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch._dispatch_command("/new")
    assert ch._chat_id == f"tui-{ch._session_counter}"


# ---------------------------------------------------------------------------
# _dispatch_command — run_in_terminal is called for rendering commands
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_help_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch._dispatch_command("/help")
    mock_rit.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_new_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch._dispatch_command("/new")
    mock_rit.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_clear_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch._dispatch_command("/clear")
    mock_rit.assert_called_once()


@pytest.mark.asyncio
async def test_dispatch_unknown_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch._dispatch_command("/unknown")
    mock_rit.assert_called_once()


# ---------------------------------------------------------------------------
# send()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_final_response_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch.send(_outbound("Hello from agent"))
    mock_rit.assert_called_once()


@pytest.mark.asyncio
async def test_send_progress_tool_hint_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch.send(_outbound("read_file(...)", _progress=True, _tool_hint=True))
    mock_rit.assert_called_once()


@pytest.mark.asyncio
async def test_send_progress_non_tool_calls_run_in_terminal():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock) as mock_rit:
        await ch.send(_outbound("Thinking...", _progress=True))
    mock_rit.assert_called_once()


@pytest.mark.asyncio
async def test_send_renders_correct_ansi_for_final_response():
    """Final response callback should produce a Panel with Markdown content."""
    ch = _make_channel()
    captured_callbacks: list = []

    async def capture_rit(fn):
        captured_callbacks.append(fn)

    with patch("nanobot.channels.tui.run_in_terminal", side_effect=capture_rit), \
         patch("nanobot.channels.tui.print_formatted_text") as mock_pft:
        await ch.send(_outbound("**bold** response"))
        assert len(captured_callbacks) == 1
        captured_callbacks[0]()  # invoke the render callback

    mock_pft.assert_called_once()
    ansi_arg = mock_pft.call_args[0][0]
    assert hasattr(ansi_arg, "value")  # prompt_toolkit ANSI object
    assert "bold" in ansi_arg.value or "\x1b[" in ansi_arg.value


@pytest.mark.asyncio
async def test_send_renders_correct_ansi_for_progress_tool_hint():
    """Tool-hint callback should print with '>' prefix."""
    ch = _make_channel()
    captured_callbacks: list = []

    async def capture_rit(fn):
        captured_callbacks.append(fn)

    with patch("nanobot.channels.tui.run_in_terminal", side_effect=capture_rit), \
         patch("nanobot.channels.tui.print_formatted_text") as mock_pft:
        await ch.send(_outbound("read_file(foo.txt)", _progress=True, _tool_hint=True))
        captured_callbacks[0]()

    ansi_str = mock_pft.call_args[0][0].value
    plain = _strip_ansi(ansi_str)
    assert "read_file(foo.txt)" in plain
    assert ">" in plain


@pytest.mark.asyncio
async def test_send_empty_content_does_not_raise():
    ch = _make_channel()
    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch.send(_outbound(""))


@pytest.mark.asyncio
async def test_send_swallows_run_in_terminal_error():
    """A render failure must not propagate to the caller."""
    ch = _make_channel()

    async def boom(fn):
        raise RuntimeError("terminal gone")

    with patch("nanobot.channels.tui.run_in_terminal", side_effect=boom):
        await ch.send(_outbound("hello"))  # should not raise


# ---------------------------------------------------------------------------
# start() — input loop control flow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_exit_word_terminates():
    ch = _make_channel()
    ch._session = MagicMock(prompt_async=AsyncMock(return_value="exit"))

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert ch._running is False


@pytest.mark.asyncio
async def test_start_quit_word_terminates():
    ch = _make_channel()
    ch._session = MagicMock(prompt_async=AsyncMock(return_value="quit"))

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert ch._running is False


@pytest.mark.asyncio
async def test_start_colon_q_terminates():
    ch = _make_channel()
    ch._session = MagicMock(prompt_async=AsyncMock(return_value=":q"))

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert ch._running is False


@pytest.mark.asyncio
async def test_start_eof_terminates():
    ch = _make_channel()
    ch._session = MagicMock(prompt_async=AsyncMock(side_effect=EOFError))

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert ch._running is False


@pytest.mark.asyncio
async def test_start_stop_command_terminates():
    ch = _make_channel()
    ch._session = MagicMock(prompt_async=AsyncMock(return_value="/stop"))

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert ch._running is False


@pytest.mark.asyncio
async def test_start_keyboard_interrupt_continues_loop():
    """Ctrl+C should not exit; the next input still works."""
    ch = _make_channel()
    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=[KeyboardInterrupt, "exit"])
    )

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert ch._running is False


@pytest.mark.asyncio
async def test_start_regular_message_calls_handle_message():
    ch = _make_channel()
    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=["hello agent", "exit"])
    )

    received: list[str] = []

    async def fake_handle(sender_id, chat_id, content, **kwargs):
        received.append(content)
        ch._response_done.set()

    ch._handle_message = fake_handle

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit, \
         patch.object(ch, "_start_loading"):
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert received == ["hello agent"]


@pytest.mark.asyncio
async def test_start_uses_current_chat_id():
    ch = _make_channel()
    ch._chat_id = "tui-5"
    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=["hi", "exit"])
    )

    received_chat_ids: list[str] = []

    async def fake_handle(sender_id, chat_id, content, **kwargs):
        received_chat_ids.append(chat_id)
        ch._response_done.set()

    ch._handle_message = fake_handle

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit, \
         patch.object(ch, "_start_loading"):
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert received_chat_ids == ["tui-5"]


@pytest.mark.asyncio
async def test_start_empty_input_skipped():
    ch = _make_channel()
    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=["  ", "", "exit"])
    )

    received: list[str] = []

    async def fake_handle(sender_id, chat_id, content, **kwargs):
        received.append(content)

    ch._handle_message = fake_handle

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert received == []


@pytest.mark.asyncio
async def test_start_slash_command_not_forwarded_to_handle_message():
    """/help should not be sent as a message to the agent."""
    ch = _make_channel()
    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=["/help", "exit"])
    )

    received: list[str] = []

    async def fake_handle(sender_id, chat_id, content, **kwargs):
        received.append(content)

    ch._handle_message = fake_handle

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert received == []


@pytest.mark.asyncio
async def test_start_new_command_changes_chat_id_for_subsequent_messages():
    """/new should switch the session; the next message uses the new chat_id."""
    ch = _make_channel()
    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=["/new", "hello", "exit"])
    )

    received_chat_ids: list[str] = []

    async def fake_handle(sender_id, chat_id, content, **kwargs):
        received_chat_ids.append(chat_id)
        ch._response_done.set()

    ch._handle_message = fake_handle

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit, \
         patch.object(ch, "_start_loading"):
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert len(received_chat_ids) == 1
    assert received_chat_ids[0] == "tui-1"


# ---------------------------------------------------------------------------
# Loading indicator (_start_loading / _stop_loading / _response_done)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_loading_creates_task():
    ch = _make_channel()
    with patch.object(ch, "_animate_loading", new_callable=AsyncMock):
        ch._start_loading()
        assert ch._loading_task is not None
        ch._loading_task.cancel()
        try:
            await ch._loading_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_stop_loading_cancels_task():
    ch = _make_channel()
    ch._loading_task = asyncio.get_event_loop().create_task(asyncio.sleep(10))
    await ch._stop_loading()
    assert ch._loading_task is None


@pytest.mark.asyncio
async def test_stop_loading_noop_when_no_task():
    ch = _make_channel()
    await ch._stop_loading()
    assert ch._loading_task is None


@pytest.mark.asyncio
async def test_send_final_response_sets_response_done():
    ch = _make_channel()
    ch._response_done.clear()

    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch.send(_outbound("Hello from agent"))

    assert ch._response_done.is_set()


@pytest.mark.asyncio
async def test_send_progress_does_not_set_response_done():
    ch = _make_channel()
    ch._response_done.clear()

    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch.send(_outbound("working...", _progress=True))

    assert not ch._response_done.is_set()


@pytest.mark.asyncio
async def test_send_tool_hint_does_not_set_response_done():
    ch = _make_channel()
    ch._response_done.clear()

    with patch("nanobot.channels.tui.run_in_terminal", new_callable=AsyncMock):
        await ch.send(_outbound("read_file(x)", _progress=True, _tool_hint=True))

    assert not ch._response_done.is_set()


@pytest.mark.asyncio
async def test_start_calls_start_loading_after_message():
    """_start_loading should be called after user sends a message."""
    ch = _make_channel()

    loading_called = False

    async def fake_handle(sender_id, chat_id, content, **kwargs):
        ch._response_done.set()

    ch._handle_message = fake_handle

    original_start_loading = ch._start_loading

    def tracking_start_loading():
        nonlocal loading_called
        loading_called = True
        ch._response_done.set()

    ch._start_loading = tracking_start_loading

    ch._session = MagicMock(
        prompt_async=AsyncMock(side_effect=["hello", "exit"])
    )

    p_console, p_stdout, p_rit = _patch_start_env()
    with p_console, p_stdout, p_rit:
        await asyncio.wait_for(ch.start(), timeout=2.0)

    assert loading_called is True
