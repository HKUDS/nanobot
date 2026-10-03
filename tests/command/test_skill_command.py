"""Tests for the /skill built-in command."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.skills import SkillsLoader
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import cmd_skill, register_builtin_commands
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.config.schema import ModelPresetConfig


def _provider(default_model: str = "test-model") -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = MagicMock()
    provider.generation.max_tokens = 4096
    provider.generation.temperature = 0.1
    provider.generation.reasoning_effort = None
    return provider


def _make_loop(tmp_path: Path) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_provider(),
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=8000,
        model_presets={
            "default": ModelPresetConfig(
                model="test-model",
                max_tokens=4096,
                context_window_tokens=8000,
            ),
        },
    )


def _ctx(loop: AgentLoop, raw: str = "/skill") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args="", loop=loop)


def _write_skill(base: Path, name: str, *, description: str = "", body: str = "# Skill\n") -> None:
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = f"---\nname: {name}\n"
    if description:
        frontmatter += f"description: {description}\n"
    frontmatter += "---\n\n"
    (skill_dir / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")


def _loop_with_skills(tmp_path: Path) -> AgentLoop:
    """Create a loop with an empty builtin dir so only workspace skills appear."""
    loop = _make_loop(tmp_path)
    empty_builtin = tmp_path / "empty_builtin"
    empty_builtin.mkdir()
    loop.context.skills = SkillsLoader(tmp_path, builtin_skills_dir=empty_builtin)
    return loop


@pytest.mark.asyncio
async def test_skill_command_no_skills(tmp_path: Path) -> None:
    loop = _loop_with_skills(tmp_path)
    out = await cmd_skill(_ctx(loop))
    assert out.content == "No skills available."


@pytest.mark.asyncio
async def test_skill_command_lists_names_and_descriptions(tmp_path: Path) -> None:
    ws_skills = tmp_path / "skills"
    ws_skills.mkdir()
    _write_skill(ws_skills, "weather", description="Get current weather and forecasts")
    _write_skill(ws_skills, "cron", description="Schedule recurring tasks")

    loop = _loop_with_skills(tmp_path)
    out = await cmd_skill(_ctx(loop))

    assert "Available skills (2):" in out.content
    assert "**weather** — Get current weather and forecasts" in out.content
    assert "**cron** — Schedule recurring tasks" in out.content
    # Must NOT contain file paths
    assert ".md" not in out.content
    assert "/skills/" not in out.content


@pytest.mark.asyncio
async def test_skill_command_excludes_disabled(tmp_path: Path) -> None:
    ws_skills = tmp_path / "skills"
    ws_skills.mkdir()
    _write_skill(ws_skills, "alpha", description="Alpha skill")
    _write_skill(ws_skills, "beta", description="Beta skill")

    loop = _make_loop(tmp_path)
    loop.context.skills.disabled_skills = {"alpha"}

    out = await cmd_skill(_ctx(loop))

    assert "alpha" not in out.content
    assert "**beta** — Beta skill" in out.content


@pytest.mark.asyncio
async def test_skill_command_fallback_description(tmp_path: Path) -> None:
    ws_skills = tmp_path / "skills"
    ws_skills.mkdir()
    _write_skill(ws_skills, "plain", description="", body="# Plain Skill\n")

    loop = _loop_with_skills(tmp_path)
    out = await cmd_skill(_ctx(loop))

    assert "**plain** — plain" in out.content


@pytest.mark.asyncio
async def test_skill_command_no_render_as_text(tmp_path: Path) -> None:
    """Output is markdown; CLI should render it (not forced as plain text)."""
    loop = _make_loop(tmp_path)
    out = await cmd_skill(_ctx(loop))
    assert out.metadata.get("render_as") != "text"


@pytest.mark.asyncio
async def test_skill_command_does_not_list_goal_runtime_protocol(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    out = await cmd_skill(_ctx(loop))

    assert "long-goal" not in out.content


@pytest.mark.asyncio
async def test_skill_command_registered_on_router(tmp_path: Path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    loop = _loop_with_skills(tmp_path)

    out = await router.dispatch(_ctx(loop, "/skill"))

    assert out is not None
    assert "No skills available." in out.content
