"""Tests for /skill and /skills slash commands."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_skill_activate, cmd_skill_list
from nanobot.command.router import CommandContext


def _make_loop():
    """Create a minimal AgentLoop with mocked dependencies."""
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    with (
        patch("nanobot.agent.loop.ContextBuilder"),
        patch("nanobot.agent.loop.SessionManager"),
        patch("nanobot.agent.loop.SubagentManager"),
    ):
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


def _make_ctx(content: str, args: str = "", loop=None):
    """Build a CommandContext for testing."""
    if loop is None:
        loop, _ = _make_loop()
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=content)
    return CommandContext(
        msg=msg, session=None, key=msg.session_key, raw=content, args=args, loop=loop
    )


def _mock_skills_loader(skills=None, skill_content=None):
    """Return a mock SkillsLoader with configurable data."""
    loader = MagicMock()
    loader.list_skills.return_value = skills or []
    loader.load_skill.side_effect = lambda name: (skill_content or {}).get(name)
    loader._get_skill_description.side_effect = lambda name: f"{name} description"
    loader._get_skill_meta.return_value = {}
    loader._check_requirements.return_value = True
    loader._strip_frontmatter.side_effect = lambda c: c.replace("---\nname: test\n---\n", "")
    return loader


class TestSkillList:
    @pytest.mark.asyncio
    async def test_lists_available_skills(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=[
                {"name": "weather", "path": "/skills/weather/SKILL.md", "source": "builtin"},
                {"name": "github", "path": "/skills/github/SKILL.md", "source": "builtin"},
            ]
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skill", loop=loop)
        result = await cmd_skill_list(ctx)

        assert result is not None
        assert "weather" in result.content
        assert "github" in result.content
        assert "✓" in result.content

    @pytest.mark.asyncio
    async def test_shows_unavailable_mark(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=[
                {"name": "tmux", "path": "/skills/tmux/SKILL.md", "source": "builtin"},
            ]
        )
        loader._check_requirements.return_value = False
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skill", loop=loop)
        result = await cmd_skill_list(ctx)

        assert "✗" in result.content
        assert "tmux" in result.content

    @pytest.mark.asyncio
    async def test_no_skills(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skills=[])
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skill", loop=loop)
        result = await cmd_skill_list(ctx)

        assert "No skills found" in result.content


class TestSkillActivate:
    @pytest.mark.asyncio
    async def test_injects_skill_content_with_message(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skill_content={"weather": "Use the weather API to get forecasts."}
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx(
            "/skill weather what is the forecast", args="weather what is the forecast", loop=loop
        )
        result = await cmd_skill_activate(ctx)

        assert result is None  # falls through to LLM
        assert '<activated-skill name="weather">' in ctx.msg.content
        assert "Use the weather API" in ctx.msg.content
        assert "what is the forecast" in ctx.msg.content
        assert ctx.msg.content.endswith("what is the forecast")

    @pytest.mark.asyncio
    async def test_injects_skill_content_without_message(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skill_content={"weather": "Use the weather API to get forecasts."}
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skill weather", args="weather", loop=loop)
        result = await cmd_skill_activate(ctx)

        assert result is None
        assert '<activated-skill name="weather">' in ctx.msg.content
        assert "</activated-skill>" in ctx.msg.content
        # No trailing message
        assert ctx.msg.content.endswith("</activated-skill>")

    @pytest.mark.asyncio
    async def test_skill_not_found(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skill_content={})
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skill nonexistent", args="nonexistent", loop=loop)
        result = await cmd_skill_activate(ctx)

        assert result is not None
        assert "not found" in result.content
        assert "/skills" in result.content

    @pytest.mark.asyncio
    async def test_empty_name_falls_back_to_list(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=[
                {"name": "weather", "path": "/skills/weather/SKILL.md", "source": "builtin"},
            ]
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skill ", args="", loop=loop)
        result = await cmd_skill_activate(ctx)

        assert result is not None
        assert "weather" in result.content


class TestHelpIncludesSkill:
    @pytest.mark.asyncio
    async def test_help_shows_skill_commands(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/help")
        response = await loop._process_message(msg)

        assert response is not None
        assert "/skill" in response.content
        assert "/skills" in response.content
