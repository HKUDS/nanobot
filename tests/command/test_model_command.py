from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.goal_permission import goal_mutation_allowed
from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.application import (
    build_help_text,
    builtin_command_palette,
    register_builtin_commands,
)
from nanobot.command.builtin import cmd_model
from nanobot.command.router import CommandContext, CommandExpansion, CommandInput, CommandRouter
from nanobot.config.schema import ModelPresetConfig
from nanobot.goal.command import cmd_goal, register_goal_command
from nanobot.session.history_visibility import HIDDEN_HISTORY_META
from nanobot.session.model_selection import (
    SESSION_MODEL_PRESET_METADATA_KEY,
    model_preset_from_metadata,
)


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(
        max_tokens=max_tokens,
        temperature=0.1,
        reasoning_effort=None,
    )
    return provider


def _make_loop(tmp_path, *, preset_snapshot_loader=None, model_presets=None) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_provider("base-model", max_tokens=123),
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets=model_presets or {
            "default": ModelPresetConfig(
                model="base-model",
                max_tokens=123,
                context_window_tokens=1000,
            ),
            "fast": ModelPresetConfig(
                model="openai/gpt-4.1",
                max_tokens=4096,
                context_window_tokens=32_768,
            ),
        },
        preset_snapshot_loader=preset_snapshot_loader,
    )


def _ctx(loop: AgentLoop, raw: str, args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


def _ctx_session(loop: AgentLoop, raw: str, args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(
        msg=msg, session=loop.sessions.get_or_create(msg.session_key),
        key=msg.session_key, raw=raw, args=args, loop=loop,
        is_user_turn=True,
    )


def _saved_model_preset(loop: AgentLoop, session_key: str = "cli:direct") -> str | None:
    session = loop.sessions.get_or_create(session_key)
    return model_preset_from_metadata(session.metadata)


@pytest.mark.asyncio
async def test_model_command_lists_current_and_available_presets(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    out = await cmd_model(_ctx(loop, "/model"))

    assert "Current model: `base-model`" in out.content
    assert "Current preset: `default`" in out.content
    assert "Available presets: `default`, `fast`" in out.content
    assert "`fast`" in out.content
    assert out.metadata == {"render_as": "text"}


@pytest.mark.asyncio
async def test_model_command_switches_preset(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    assert loop.tools_config.my.allow_set is False

    out = await cmd_model(_ctx(loop, "/model fast", args="fast"))

    assert "Switched model preset to `fast`." in out.content
    assert "Scope: current session" in out.content
    assert "Model: `openai/gpt-4.1`" in out.content
    assert _saved_model_preset(loop) == "fast"
    assert loop.model_preset is None
    assert loop.model == "base-model"

    await loop.process_direct("/new", session_key="cli:direct")
    assert _saved_model_preset(loop) == "fast"
    status = await loop.process_direct("/status", session_key="cli:direct")
    assert status is not None and "openai/gpt-4.1" in status.content


@pytest.mark.asyncio
async def test_model_command_accepts_canonical_names_with_spaces(tmp_path) -> None:
    loop = _make_loop(
        tmp_path,
        model_presets={
            "default": ModelPresetConfig(model="base-model"),
            "Deep Research": ModelPresetConfig(model="deep-model"),
        },
    )

    out = await cmd_model(
        _ctx(loop, "/model deep research", args="deep research"),
    )

    assert "Switched model preset to `Deep Research`." in out.content
    assert _saved_model_preset(loop) == "Deep Research"


@pytest.mark.asyncio
async def test_model_command_switches_back_to_default(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    await cmd_model(_ctx(loop, "/model fast", args="fast"))

    out = await cmd_model(_ctx(loop, "/model default", args="default"))

    assert "Switched model preset to `default`." in out.content
    assert _saved_model_preset(loop) == "default"
    assert loop.model_preset is None
    assert loop.model == "base-model"
    assert loop.context_window_tokens == 1000


@pytest.mark.asyncio
async def test_model_command_unknown_preset_keeps_old_state(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    out = await cmd_model(_ctx(loop, "/model missing", args="missing"))

    assert "Could not switch model preset" in out.content
    assert "\"model_preset" not in out.content
    assert "Available presets: `default`, `fast`" in out.content
    assert loop.model_preset is None
    assert loop.model == "base-model"


@pytest.mark.asyncio
async def test_model_command_reports_provider_configuration_errors(tmp_path) -> None:
    def fail_preset(_name: str):
        raise ValueError("No API key configured for provider 'openai'.")

    loop = _make_loop(tmp_path, preset_snapshot_loader=fail_preset)

    switched = await cmd_model(_ctx(loop, "/model fast", args="fast"))
    session = loop.sessions.get_or_create("cli:direct")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "fast"
    loop.sessions.save(session)
    status = await cmd_model(_ctx(loop, "/model"))

    assert "Could not switch model preset" in switched.content
    assert "No API key configured for provider 'openai'." in switched.content
    assert "Current selection error" in status.content
    assert "No API key configured for provider 'openai'." in status.content


@pytest.mark.asyncio
async def test_model_command_registered_as_exact_and_prefix(tmp_path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    loop = _make_loop(tmp_path)

    out = await router.dispatch(_ctx(loop, "/model fast"))

    assert out is not None
    assert out.channel == "cli"
    assert out.chat_id == "direct"
    assert out.metadata == {"render_as": "text"}
    assert out.content == "\n".join([
        "Switched model preset to `fast`.",
        "- Scope: current session",
        "- Model: `openai/gpt-4.1`",
        "- Context window: 32768",
        "- Max output tokens: 4096",
    ])
    assert _saved_model_preset(loop) == "fast"


@pytest.mark.asyncio
async def test_model_command_does_not_change_another_session(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    await cmd_model(_ctx(loop, "/model fast", args="fast"))
    other = InboundMessage(channel="cli", sender_id="user", chat_id="other", content="/model")
    out = await cmd_model(
        CommandContext(msg=other, session=None, key=other.session_key, raw="/model", loop=loop)
    )

    assert "Current preset: `default`" in out.content
    assert _saved_model_preset(loop) == "fast"


@pytest.mark.asyncio
async def test_model_command_reports_and_recovers_removed_session_preset(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    session = loop.sessions.get_or_create("cli:direct")
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "removed"
    loop.sessions.save(session)

    status = await loop.process_direct("/model", session_key="cli:direct")
    switched = await loop.process_direct("/model default", session_key="cli:direct")

    assert status is not None
    assert "model_preset 'removed' not found" in status.content
    assert "Available presets: `default`, `fast`" in status.content
    assert "Switch with `/model <preset>`" in status.content
    assert switched is not None
    assert "Switched model preset to `default`." in switched.content
    assert _saved_model_preset(loop) == "default"


def test_model_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()

    model = next(item for item in palette if item["command"] == "/model")
    assert model["arg_hint"] == "[preset]"
    assert model["lifecycle"] == "side_channel"
    assert model["accepts_args"] is True
    assert "/model [preset]" in build_help_text()


@pytest.mark.asyncio
async def test_goal_command_shows_usage_without_args(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    ctx = _ctx(loop, "/goal")
    out = await cmd_goal(CommandInput(ctx.msg, ctx.args, ctx.is_user_turn))
    assert out is not None
    assert out.channel == "cli"
    assert out.chat_id == "direct"
    assert out.metadata == {"render_as": "text"}
    assert out.content == "Usage: /goal <long-running task description>"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_session", [False, True])
async def test_goal_command_preserves_task_and_visible_command(tmp_path, with_session) -> None:
    loop = _make_loop(tmp_path)
    task = "检查 /tmp/project\n保留现有文件。"
    command = f"/goal {task}"
    ctx = _ctx_session(loop, command, args=task)
    ctx.msg.media = ["attachment.png"]
    ctx.msg.metadata = {"request_id": "request-1"}
    ctx.session = await loop.sessions.state.get(ctx.key) if with_session else None
    expansion = await cmd_goal(CommandInput(ctx.msg, ctx.args, ctx.is_user_turn))
    assert isinstance(expansion, CommandExpansion)
    out = await loop._prepare_command_expansion(ctx, expansion)
    assert isinstance(out, InboundMessage)
    assert ctx.msg.content == command
    assert out.content == task
    assert out.media == ["attachment.png"]
    assert out.metadata["request_id"] == "request-1"
    assert out.metadata["original_command"] == "/goal"
    assert out.metadata["original_content"] == command
    assert out.metadata["goal_requested"] is True
    assert out.metadata[HIDDEN_HISTORY_META] == {"kind": "goal_request"}
    assert goal_mutation_allowed() is False
    session = loop.sessions.get_or_create(ctx.key)
    assert [(row["role"], row["content"]) for row in session.messages] == [
        ("user", command),
    ]
    assert session.messages[0]["_command"] is True
    assert session.messages[0]["media"] == ["attachment.png"]



@pytest.mark.asyncio
async def test_goal_command_registered_on_router(tmp_path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    loop = _make_loop(tmp_path)
    usage = await router.dispatch(_ctx(loop, "/goal"))
    assert isinstance(usage, OutboundMessage)
    assert usage.content == "Usage: /goal <long-running task description>"
    assert usage.metadata == {"render_as": "text"}
    ctx = _ctx_session(loop, "/goal ship it", args="ship it")
    ctx.session = await loop.sessions.state.get(ctx.key)
    out = await router.dispatch(ctx)
    assert isinstance(out, CommandExpansion)
    assert out.message.content == "ship it"
    assert out.message.metadata["goal_requested"] is True
    assert goal_mutation_allowed() is False



@pytest.mark.asyncio
async def test_goal_command_can_be_registered_independently(tmp_path) -> None:
    router = CommandRouter()
    register_goal_command(router)
    loop = _make_loop(tmp_path)

    usage = await router.dispatch(_ctx(loop, "/goal"))
    ctx = _ctx_session(loop, "/goal ship it")
    ctx.session = await loop.sessions.state.get(ctx.key)
    task = await router.dispatch(ctx)

    assert isinstance(usage, OutboundMessage)
    assert usage.content == "Usage: /goal <long-running task description>"
    assert isinstance(task, CommandExpansion)
    assert task.message.content == "ship it"
    assert task.message.metadata["goal_requested"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("with_session", [False, True])
async def test_goal_command_rejects_transient_session_without_changing_history(
    tmp_path, monkeypatch, with_session,
) -> None:
    loop = _make_loop(tmp_path)
    loop.provider.aclose = AsyncMock()
    ctx = _ctx(loop, "/goal keep going", args="keep going")
    ctx.is_user_turn = True
    ctx.msg.metadata = {"request_id": "request-1"}
    session = await loop.sessions.state.register_transient(ctx.key)
    session.add_message("user", "Earlier private message")
    await loop.sessions.state.prepare_input(session)
    ctx.session = session if with_session else None
    prepare_input = AsyncMock(wraps=loop.sessions.state.prepare_input)
    monkeypatch.setattr(loop.sessions.state, "prepare_input", prepare_input)
    try:
        expansion = await cmd_goal(CommandInput(ctx.msg, ctx.args, ctx.is_user_turn))
        assert isinstance(expansion, CommandExpansion)
        out = await loop._prepare_command_expansion(ctx, expansion)

        assert isinstance(out, OutboundMessage)
        assert out.content == "Goals can't start in a temporary session. Use a persistent session for `/goal`."
        assert out.metadata == {"request_id": "request-1", "render_as": "text"}
        prepare_input.assert_not_awaited()
        assert [row["content"] for row in session.messages] == ["Earlier private message"]
        current = await loop.sessions.state.read(ctx.key)
        assert current is not None and not current.policy.persist
        assert [row["content"] for row in current.messages] == ["Earlier private message"]
        assert loop.sessions.read_session_file(ctx.key) is None
    finally:
        await loop.aclose()


@pytest.mark.asyncio
async def test_goal_command_does_not_allow_internal_turn(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    ctx = CommandContext(
        msg=InboundMessage(
            channel="cli",
            sender_id="system",
            chat_id="direct",
            content="/goal internal work",
        ),
        session=MagicMock(),
        key="cli:direct",
        raw="/goal internal work",
        args="internal work",
        loop=loop,
        is_user_turn=False,
    )

    out = await cmd_goal(CommandInput(ctx.msg, ctx.args, ctx.is_user_turn))

    assert isinstance(out, OutboundMessage)
    assert "only be started by a user" in out.content


def test_goal_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()
    goal = next(item for item in palette if item["command"] == "/goal")
    assert goal == {
        "command": "/goal",
        "title": "Start long-running goal",
        "description": "Tell the agent to treat the request as a long-running goal.",
        "icon": "activity",
        "arg_hint": "<goal>",
        "lifecycle": "agent_turn_with_args",
        "accepts_args": True,
    }
    commands = [item["command"] for item in palette]
    goal_index = commands.index("/goal")
    assert commands[goal_index - 1:goal_index + 2] == ["/history", "/goal", "/trigger"]
    assert "/goal <goal>" in build_help_text()
