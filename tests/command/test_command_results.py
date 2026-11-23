"""Shared copy must work for every shipped client language and command."""

import json
import re
from pathlib import Path

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.bus.outbound_events import CommandResultEvent, outbound_message_for_event
from nanobot.command.application import BUILTIN_COMMAND_SPECS, build_help_text
from nanobot.command.results import command_reply, line, message_text, render
from nanobot.command.router import CommandInput
from nanobot.command_copy import catalog
from nanobot.events import ContextCompactionEvent
from nanobot.goal.command import cmd_goal


def test_shipped_commands_have_complete_copy():
    root = Path(__file__).resolve().parents[2]
    languages = {f.parent.name for f in (root / "webui/src/i18n/locales").glob("*/common.json")}
    assert languages
    entries = catalog()
    for spec in BUILTIN_COMMAND_SPECS:
        for field in ("title", "description"):
            assert f"palette.{spec.command[1:]}.{field}" in entries
    seen: set[str] = set()
    for source in (root / "nanobot/command/locales").glob("*.json"):
        keys = set(json.loads(source.read_bytes()))
        assert not seen.intersection(keys), source
        seen.update(keys)
    for key, values in entries.items():
        assert set(values) == languages, key
        placeholders = set(re.findall(r"\{(\w+)\}", values["en"]))
        for lang, text in values.items():
            assert text.strip(), (key, lang)
            assert set(re.findall(r"\{(\w+)\}", text)) == placeholders, (key, lang)


@pytest.mark.asyncio
async def test_goal_usage_can_be_read_in_different_languages():
    msg = InboundMessage(channel="telegram", sender_id="user", chat_id="room", content="/goal",
                         metadata={"locale": "zh-Hant"})
    reply = await cmd_goal(CommandInput(msg, "", True))
    assert hasattr(reply, "event") and isinstance(reply.event, CommandResultEvent)
    assert reply.event.command == "/goal"
    assert message_text(reply) == "用法：/goal <長期工作說明>"
    assert render(reply.event.parts, "en") == "Usage: /goal <long-running task description>"
    help_lines = build_help_text(locale="zh-TW").splitlines()
    assert len(help_lines) == 1 + len(BUILTIN_COMMAND_SPECS)
    assert any(row.startswith("/model [preset] — 檢視") for row in help_lines)


def test_literal_output_and_parameter_values_are_not_translated(monkeypatch):
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    raw = "{preset} $&"
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/model")
    reply = command_reply(msg, "/model", line("model.switched", preset=raw), raw)
    assert message_text(reply) == f"已切换到 `{raw}`。\n{raw}"


def test_compact_preserves_event_and_projects_localized_text():
    event = ContextCompactionEvent(compaction_id="compact-1", phase="cancelled", notify=True, reason="manual")
    out = outbound_message_for_event(channel="telegram", chat_id="room", event=event, metadata={"locale": "ja"})
    assert message_text(out) == "コンテキストの圧縮を取り消しました。"
    assert out.event is event
