from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanobot.bus.outbound_events import ProgressEvent, RetryWaitEvent
from nanobot.cli import commands


@pytest.mark.asyncio
async def test_interactive_retry_wait_is_rendered_as_progress_even_when_progress_disabled():
    """Provider retry waits should not fall through as assistant responses."""
    calls: list[tuple[str, object | None]] = []
    thinking = None
    channels_config = SimpleNamespace(send_progress=False, send_tool_hints=False)
    msg = SimpleNamespace(
        content="Model request failed, retry in 2s (attempt 1).",
        event=RetryWaitEvent(content="Model request failed, retry in 2s (attempt 1)."),
        metadata={},
    )

    async def fake_print(text: str, active_thinking: object | None, renderer=None) -> None:
        calls.append((text, active_thinking))

    with patch("nanobot.cli.commands._print_interactive_progress_line", side_effect=fake_print):
        handled = await commands._maybe_print_interactive_progress(
            msg,
            thinking,
            channels_config,
        )

    assert handled is True
    assert calls == [("Model request failed, retry in 2s (attempt 1).", thinking)]


@pytest.mark.asyncio
async def test_reasoning_displayed_when_show_reasoning_enabled():
    """Reasoning content should be displayed when show_reasoning is True."""
    calls: list[str] = []
    channels_config = SimpleNamespace(
        send_progress=True, send_tool_hints=False, show_reasoning=True,
    )
    msg = SimpleNamespace(
        content="Let me think about this...",
        event=ProgressEvent(content="Let me think about this...", reasoning=True),
        metadata={},
    )

    with patch("nanobot.cli.commands._print_cli_reasoning", side_effect=lambda t, th, r=None: calls.append(t)):
        handled = await commands._maybe_print_interactive_progress(msg, None, channels_config)

    assert handled is True
    assert calls == ["Let me think about this..."]


@pytest.mark.asyncio
async def test_reasoning_delta_displayed_when_show_reasoning_enabled():
    """Streamed reasoning delta frames should use the reasoning renderer."""
    calls: list[str] = []
    channels_config = SimpleNamespace(
        send_progress=True, send_tool_hints=False, show_reasoning=True,
    )
    msg = SimpleNamespace(
        content="I should search first.",
        event=ProgressEvent(content="I should search first.", reasoning_delta=True),
        metadata={},
    )

    with patch("nanobot.cli.commands._print_cli_reasoning", side_effect=lambda t, th, r=None: calls.append(t)):
        handled = await commands._maybe_print_interactive_progress(msg, None, channels_config)

    assert handled is True
    assert calls == ["I should search first."]


@pytest.mark.asyncio
async def test_reasoning_delta_buffers_until_sentence_boundary():
    calls: list[str] = []
    channels_config = SimpleNamespace(
        send_progress=True, send_tool_hints=False, show_reasoning=True,
    )
    reasoning_buffer = commands._ReasoningBuffer()

    with patch("nanobot.cli.commands._print_cli_reasoning", side_effect=lambda t, th, r=None: calls.append(t)):
        first = await commands._maybe_print_interactive_progress(
            SimpleNamespace(
                content="The",
                event=ProgressEvent(content="The", reasoning_delta=True),
                metadata={},
            ),
            None,
            channels_config,
            reasoning_buffer=reasoning_buffer,
        )
        second = await commands._maybe_print_interactive_progress(
            SimpleNamespace(
                content=" user asked.",
                event=ProgressEvent(content=" user asked.", reasoning_delta=True),
                metadata={},
            ),
            None,
            channels_config,
            reasoning_buffer=reasoning_buffer,
        )

    assert first is True
    assert second is True
    assert calls == ["The user asked."]


@pytest.mark.asyncio
async def test_reasoning_end_flushes_buffered_delta():
    calls: list[str] = []
    channels_config = SimpleNamespace(
        send_progress=True, send_tool_hints=False, show_reasoning=True,
    )
    reasoning_buffer = commands._ReasoningBuffer()

    with patch("nanobot.cli.commands._print_cli_reasoning", side_effect=lambda t, th, r=None: calls.append(t)):
        delta = await commands._maybe_print_interactive_progress(
            SimpleNamespace(
                content="The user asked",
                event=ProgressEvent(content="The user asked", reasoning_delta=True),
                metadata={},
            ),
            None,
            channels_config,
            reasoning_buffer=reasoning_buffer,
        )
        end = await commands._maybe_print_interactive_progress(
            SimpleNamespace(
                content="",
                event=ProgressEvent(reasoning_end=True),
                metadata={},
            ),
            None,
            channels_config,
            reasoning_buffer=reasoning_buffer,
        )

    assert delta is True
    assert end is True
    assert calls == ["The user asked"]


@pytest.mark.asyncio
async def test_reasoning_hidden_when_show_reasoning_disabled():
    """Reasoning content should be suppressed when show_reasoning is False."""
    channels_config = SimpleNamespace(
        send_progress=True, send_tool_hints=False, show_reasoning=False,
    )
    msg = SimpleNamespace(
        content="Let me think about this...",
        event=ProgressEvent(content="Let me think about this...", reasoning=True),
        metadata={},
    )

    with patch("nanobot.cli.commands._print_cli_reasoning") as mock_reasoning:
        handled = await commands._maybe_print_interactive_progress(msg, None, channels_config)

    assert handled is True
    mock_reasoning.assert_not_called()


@pytest.mark.asyncio
async def test_non_reasoning_progress_not_affected_by_show_reasoning():
    """Regular progress lines should display regardless of show_reasoning."""
    calls: list[str] = []
    channels_config = SimpleNamespace(
        send_progress=True, send_tool_hints=False, show_reasoning=False,
    )
    msg = SimpleNamespace(
        content="working on it...",
        event=ProgressEvent(content="working on it..."),
        metadata={},
    )

    async def fake_print(text: str, thinking=None, renderer=None):
        calls.append(text)

    with patch("nanobot.cli.commands._print_interactive_progress_line", side_effect=fake_print):
        handled = await commands._maybe_print_interactive_progress(msg, None, channels_config)

    assert handled is True
    assert calls == ["working on it..."]


@pytest.mark.asyncio
async def test_reasoning_shown_when_send_progress_disabled():
    """Reasoning display is governed by `show_reasoning` alone, independent
    of `send_progress` — the two knobs are orthogonal."""
    calls: list[str] = []
    channels_config = SimpleNamespace(
        send_progress=False, send_tool_hints=False, show_reasoning=True,
    )
    msg = SimpleNamespace(
        content="Let me think about this...",
        event=ProgressEvent(content="Let me think about this...", reasoning=True),
        metadata={},
    )

    with patch(
        "nanobot.cli.commands._print_cli_reasoning",
        side_effect=lambda t, th, r=None: calls.append(t),
    ):
        handled = await commands._maybe_print_interactive_progress(msg, None, channels_config)

    assert handled is True
    assert calls == ["Let me think about this..."]
