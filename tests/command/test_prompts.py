from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.prompts import PromptCommandError, PromptCommands
from nanobot.config.schema import ToolsConfig
from nanobot.providers.base import LLMResponse


def data(**kwargs):
    return {"name": "review", "source": "user", "revision": "", "description": "审查改动",
            "argument_hint": "[files]", "body": "Review $ARGUMENTS", "enabled": True, **kwargs}


@pytest.fixture
def commands(tmp_path, monkeypatch):
    config = tmp_path / "instance" / "config.json"
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config)
    return PromptCommands(tmp_path / "project", config)


def test_save_update_delete_and_literal_arguments(commands, tmp_path):
    commands.save(data())
    command, arguments = commands.lookup('/review@mybot $(echo SECRET) @file.md')
    assert "$(echo SECRET) @file.md" in command.expand(arguments)
    assert command.description == "审查改动"
    assert not (tmp_path / "SECRET").exists()
    with pytest.raises(PromptCommandError, match="changed"):
        commands.save(data(body="stale update"))
    commands.save(data(revision=command.revision, body="Explain"))
    command, args = commands.lookup("/REVIEW hello\n世界")
    assert command.expand(args).endswith("Explain\n\nhello\n世界")
    commands.save(data(revision=command.revision), delete=True)
    assert commands.lookup("/review") is None


def test_workspace_shadow_disabled_and_broken_do_not_fall_back(commands, tmp_path):
    commands.save(data())
    commands.save(data(source="workspace", body="Workspace", enabled=False))
    assert commands.lookup("/review") is None
    assert commands.effective() == []
    assert commands.payload()["commands"][0]["shadowed"] is True
    path = tmp_path / "project/.nanobot/commands/review.md"
    path.write_text("broken", encoding="utf-8")
    assert commands.lookup("/review") is None
    assert commands.payload()["invalid"] == 1
    assert commands.effective() == []


def test_restart_custom_instance_and_failed_replace_preserve_command(commands, tmp_path, monkeypatch):
    commands.save(data())
    current = commands.payload()["commands"][0]
    restored = PromptCommands(tmp_path / "project", tmp_path / "instance/config.json")
    assert restored.lookup("/review")[0].body == "Review $ARGUMENTS"
    assert PromptCommands(tmp_path / "project", tmp_path / "other/config.json").lookup("/review") is None
    def fail(*args):
        raise OSError("simulated replace failure")
    monkeypatch.setattr("nanobot.command.prompts.os.replace", fail)
    with pytest.raises(OSError):
        commands.save({**current, "body": "new"})
    assert restored.lookup("/review")[0].body == "Review $ARGUMENTS"
    assert not list((tmp_path / "instance/commands").glob(".prompt-*"))


def test_deep_yaml_is_rejected_before_construction(commands, tmp_path):
    root = tmp_path / "project/.nanobot/commands"
    root.mkdir(parents=True)
    (root / "review.md").write_text("---\ndescription: " + "[" * 1500 + "]" * 1500 + "\n---\nprompt")
    assert commands.lookup("/review") is None


@pytest.mark.parametrize("name", ["stop", "goal", "new", "__shell", "../x", "/tmp/a", "x/y", "x\\y", "UPPER", "", "a" * 49])
def test_invalid_and_reserved_names(commands, name):
    with pytest.raises(PromptCommandError):
        commands.save(data(name=name))
    assert commands.lookup("/" + name) is None


@pytest.mark.parametrize("header", ["description: &x [*x]", "description: !!python/object/apply:os.system ['pwd']",
                                   "description: [bad]", "enabled: yes", "tools: exec"])
def test_invalid_yaml_is_not_run(commands, tmp_path, header):
    root = tmp_path / "project/.nanobot/commands"
    root.mkdir(parents=True)
    (root / "review.md").write_text(f"---\n{header}\n---\nhello", encoding="utf-8")
    assert commands.lookup("/review") is None
    assert commands.payload()["invalid"] == 1


def test_symlinks_and_size(commands, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("unchanged")
    root = tmp_path / "project/.nanobot/commands"
    root.mkdir(parents=True)
    try:
        (root / "review.md").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")
    with pytest.raises(PromptCommandError):
        commands.save(data(source="workspace"))
    assert outside.read_text() == "unchanged"
    with pytest.raises(PromptCommandError, match="64 KiB"):
        commands.save(data(body="x" * 65536))
    assert list((tmp_path / "instance/commands").glob("*.md")) == []


@pytest.mark.asyncio
async def test_normal_turn_queue_and_system_boundaries(commands, tmp_path):
    commands.save(data(body="/stop\nReview $ARGUMENTS"))
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="Done", finish_reason="stop"))
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path / "project",
                     model="test-model", tools_config=ToolsConfig())
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/review hello")
    try:
        expanded = await loop._expand_prompt_command(msg)
        assert expanded is not msg
        assert loop._can_inject_message(expanded)
        assert await loop._expand_prompt_command(expanded) is expanded
        system = InboundMessage(channel="system", sender_id="subagent", chat_id="test", content="/review secret")
        assert await loop._expand_prompt_command(system) is system
        result = await loop._process_message(msg)
        assert result and result.content == "Done"
        sent = provider.chat_stream_with_retry.call_args.kwargs["messages"]
        assert any("/stop\nReview hello" in str(item.get("content")) for item in sent)
    finally:
        await loop.aclose()
