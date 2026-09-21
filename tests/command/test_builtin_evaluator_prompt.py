from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import (
    build_help_text,
    builtin_command_palette,
    cmd_evaluator_prompt,
)
from nanobot.command.router import CommandContext
from nanobot.utils.evaluator import default_evaluator_prompt


def _make_ctx(tmp_path, raw: str = "/evaluator-prompt", args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    loop = SimpleNamespace(context=SimpleNamespace(memory=SimpleNamespace(workspace=tmp_path)))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


@pytest.mark.asyncio
async def test_evaluator_prompt_reports_default_prompt(tmp_path) -> None:
    out = await cmd_evaluator_prompt(_make_ctx(tmp_path))

    assert "Heartbeat evaluator prompt: nanobot default" in out.content
    assert "prompts/evaluator.md" in out.content
    assert str(tmp_path) not in out.content
    assert "/evaluator-prompt init" in out.content


@pytest.mark.asyncio
async def test_evaluator_prompt_init_copies_default_prompt(tmp_path) -> None:
    ctx = _make_ctx(tmp_path, "/evaluator-prompt init", "init")

    out = await cmd_evaluator_prompt(ctx)

    prompt_file = tmp_path / "prompts" / "evaluator.md"
    assert "Created heartbeat evaluator prompt" in out.content
    assert "prompts/evaluator.md" in out.content
    assert str(tmp_path) not in out.content
    assert "evaluate_notification" in out.content
    assert prompt_file.read_text(encoding="utf-8") == default_evaluator_prompt() + "\n"


@pytest.mark.asyncio
async def test_evaluator_prompt_init_does_not_overwrite_existing_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "evaluator.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("custom", encoding="utf-8")
    ctx = _make_ctx(tmp_path, "/evaluator-prompt init", "init")

    out = await cmd_evaluator_prompt(ctx)

    assert "already exists" in out.content
    assert "prompts/evaluator.md" in out.content
    assert str(tmp_path) not in out.content
    assert prompt_file.read_text(encoding="utf-8") == "custom"


@pytest.mark.asyncio
async def test_evaluator_prompt_handles_undecodable_existing_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "evaluator.md"
    prompt_file.parent.mkdir()
    original = "custom".encode("utf-16")
    prompt_file.write_bytes(original)

    status = await cmd_evaluator_prompt(_make_ctx(tmp_path))
    init = await cmd_evaluator_prompt(
        _make_ctx(tmp_path, "/evaluator-prompt init", "init")
    )

    assert "Heartbeat evaluator prompt: nanobot default" in status.content
    assert "already exists" in init.content
    assert prompt_file.read_bytes() == original


@pytest.mark.asyncio
async def test_evaluator_prompt_init_recreates_empty_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "evaluator.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("  \n", encoding="utf-8")
    ctx = _make_ctx(tmp_path, "/evaluator-prompt init", "init")

    out = await cmd_evaluator_prompt(ctx)

    assert "Created heartbeat evaluator prompt" in out.content
    assert prompt_file.read_text(encoding="utf-8") == default_evaluator_prompt() + "\n"


@pytest.mark.asyncio
async def test_evaluator_prompt_reports_override(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "evaluator.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("custom", encoding="utf-8")

    out = await cmd_evaluator_prompt(_make_ctx(tmp_path))

    assert "Heartbeat evaluator prompt: custom for this workspace" in out.content
    assert "prompts/evaluator.md" in out.content


@pytest.mark.asyncio
async def test_evaluator_prompt_rejects_unknown_args(tmp_path) -> None:
    out = await cmd_evaluator_prompt(_make_ctx(tmp_path, "/evaluator-prompt nope", "nope"))

    assert out.content == "Usage: /evaluator-prompt [init]"


def test_evaluator_prompt_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()
    entry = next(item for item in palette if item["command"] == "/evaluator-prompt")

    assert entry["arg_hint"] == "[init]"
    assert entry["lifecycle"] == "side_channel"
    assert entry["accepts_args"] is True
    assert "/evaluator-prompt [init]" in build_help_text()
