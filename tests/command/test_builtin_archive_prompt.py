from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import (
    build_help_text,
    builtin_command_palette,
    cmd_archive_prompt,
)
from nanobot.command.router import CommandContext


def _make_ctx(tmp_path, raw: str = "/archive-prompt", args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content=raw)
    loop = SimpleNamespace(context=SimpleNamespace(memory=MemoryStore(tmp_path)))
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


@pytest.mark.asyncio
async def test_archive_prompt_reports_default_prompt(tmp_path) -> None:
    out = await cmd_archive_prompt(_make_ctx(tmp_path))

    assert "Archive consolidation prompt: nanobot default" in out.content
    assert "prompts/consolidator_archive.md" in out.content
    assert str(tmp_path) not in out.content
    assert "/archive-prompt init" in out.content


@pytest.mark.asyncio
async def test_archive_prompt_init_copies_default_prompt(tmp_path) -> None:
    ctx = _make_ctx(tmp_path, "/archive-prompt init", "init")

    out = await cmd_archive_prompt(ctx)

    prompt_file = tmp_path / "prompts" / "consolidator_archive.md"
    assert "Created Archive consolidation prompt" in out.content
    assert "prompts/consolidator_archive.md" in out.content
    assert str(tmp_path) not in out.content
    assert "fully replaces nanobot's default Archive guide" in out.content
    assert (
        prompt_file.read_text(encoding="utf-8")
        == MemoryStore.default_archive_prompt() + "\n"
    )


@pytest.mark.asyncio
async def test_archive_prompt_init_does_not_overwrite_existing_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "consolidator_archive.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("custom", encoding="utf-8")
    ctx = _make_ctx(tmp_path, "/archive-prompt init", "init")

    out = await cmd_archive_prompt(ctx)

    assert "already exist" in out.content
    assert "prompts/consolidator_archive.md" in out.content
    assert str(tmp_path) not in out.content
    assert prompt_file.read_text(encoding="utf-8") == "custom"


@pytest.mark.asyncio
async def test_archive_prompt_init_recreates_empty_prompt(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "consolidator_archive.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("  \n", encoding="utf-8")
    ctx = _make_ctx(tmp_path, "/archive-prompt init", "init")

    out = await cmd_archive_prompt(ctx)

    assert "Created Archive consolidation prompt" in out.content
    assert (
        prompt_file.read_text(encoding="utf-8")
        == MemoryStore.default_archive_prompt() + "\n"
    )


@pytest.mark.asyncio
async def test_archive_prompt_reports_override(tmp_path) -> None:
    prompt_file = tmp_path / "prompts" / "consolidator_archive.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("custom", encoding="utf-8")

    out = await cmd_archive_prompt(_make_ctx(tmp_path))

    assert "Archive consolidation prompt: custom for this workspace" in out.content
    assert "prompts/consolidator_archive.md" in out.content


@pytest.mark.asyncio
async def test_archive_prompt_rejects_unknown_args(tmp_path) -> None:
    out = await cmd_archive_prompt(_make_ctx(tmp_path, "/archive-prompt nope", "nope"))

    assert out.content == "Usage: /archive-prompt [init]"


def test_archive_prompt_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()
    entry = next(item for item in palette if item["command"] == "/archive-prompt")

    assert entry["arg_hint"] == "[init]"
    assert entry["lifecycle"] == "side_channel"
    assert entry["accepts_args"] is True
    assert "/archive-prompt [init]" in build_help_text()
