from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanobot.cli import commands


@pytest.mark.asyncio
async def test_interactive_retry_wait_is_rendered_as_progress_even_when_progress_disabled():
    """Provider retry waits should not fall through as assistant responses."""
    calls: list[tuple[str, object | None]] = []
    thinking = None
    channels_config = SimpleNamespace(send_progress=False, send_tool_hints=False)
    msg = SimpleNamespace(
        content="Model request failed, retry in 2s (attempt 1).",
        metadata={"_retry_wait": True},
    )

    async def fake_print(text: str, active_thinking: object | None) -> None:
        calls.append((text, active_thinking))

    with patch("nanobot.cli.commands._print_interactive_progress_line", side_effect=fake_print):
        handled = await commands._maybe_print_interactive_progress(
            msg,
            thinking,
            channels_config,
        )

    assert handled is True
    assert calls == [("Model request failed, retry in 2s (attempt 1).", thinking)]
