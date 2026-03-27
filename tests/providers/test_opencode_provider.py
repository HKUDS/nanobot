"""Tests for the OpenCode CLI provider."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.providers.opencode_cli_provider import OpenCodeCLIProvider


def test_opencode_parse_output_accepts_pretty_printed_json_events() -> None:
    raw = """
    {
      "type": "step_start",
      "timestamp": 1,
      "part": {
        "type": "step-start",
        "id": "abc"
      }
    }
    {
      "type": "text",
      "timestamp": 2,
      "part": {
        "type": "text",
        "text": "Hello from OpenCode"
      }
    }
    {
      "type": "step_finish",
      "timestamp": 3,
      "part": {
        "type": "step-finish",
        "reason": "stop"
      }
    }
    """

    result = OpenCodeCLIProvider._parse_output(raw)

    assert result.finish_reason == "stop"
    assert result.content == "Hello from OpenCode"


@pytest.mark.asyncio
async def test_opencode_chat_invokes_cli_with_json_payload(monkeypatch) -> None:
    provider = OpenCodeCLIProvider(default_model="opencode/grok-code")

    fake_proc = SimpleNamespace(
        returncode=0,
        communicate=AsyncMock(
            return_value=(
                b'{\n  "type": "text",\n  "part": {\n    "type": "text",\n    "text": "ok"\n  }\n}\n',
                b"",
            )
        ),
    )

    create_proc = AsyncMock(return_value=fake_proc)
    monkeypatch.setattr(
        "nanobot.providers.opencode_cli_provider.asyncio.create_subprocess_exec",
        create_proc,
    )

    result = await provider.chat(
        messages=[{"role": "user", "content": "hello"}],
        model="opencode/grok-code",
    )

    assert result.content == "ok"
    assert result.finish_reason == "stop"

    call_kwargs = create_proc.call_args.kwargs
    assert call_kwargs["cwd"] is None
    assert call_kwargs["stdin"] is not None
    args = create_proc.call_args.args
    assert args[:4] == ("opencode", "run", "--format", "json")
    assert args[4] == "--model"
    assert args[5] == "opencode/grok-code"
    sent_payload = fake_proc.communicate.await_args.args[0]
    assert sent_payload == b'{"message": "User: hello"}'
