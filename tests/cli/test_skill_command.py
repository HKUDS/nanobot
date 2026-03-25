"""Tests for /skills listing and $skill inline activation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_skill_list, intercept_skill_refs
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


def _make_ctx(content: str, loop=None):
    """Build a CommandContext for testing."""
    if loop is None:
        loop, _ = _make_loop()
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=content)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=content, loop=loop)


def _mock_skills_loader(skills=None, skill_content=None):
    """Return a mock SkillsLoader with configurable data."""
    loader = MagicMock()
    loader.list_skills.return_value = skills or []
    loader.load_skill.side_effect = lambda name: (skill_content or {}).get(name)
    loader._get_skill_description.side_effect = lambda name: f"{name} description"
    loader._get_skill_meta.return_value = {}
    loader._check_requirements.return_value = True
    loader._strip_frontmatter.side_effect = lambda c: c
    return loader


WEATHER_SKILLS = [
    {"name": "weather", "path": "/skills/weather/SKILL.md", "source": "builtin"},
]
MULTI_SKILLS = [
    {"name": "weather", "path": "/skills/weather/SKILL.md", "source": "builtin"},
    {"name": "github", "path": "/skills/github/SKILL.md", "source": "builtin"},
]


class TestSkillList:
    @pytest.mark.asyncio
    async def test_lists_available_skills(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skills=MULTI_SKILLS)
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skills", loop=loop)
        result = await cmd_skill_list(ctx)

        assert result is not None
        assert "weather" in result.content
        assert "github" in result.content
        assert "✓" in result.content
        assert "$" in result.content  # hints about $ usage

    @pytest.mark.asyncio
    async def test_shows_unavailable_mark(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=[{"name": "tmux", "path": "/skills/tmux/SKILL.md", "source": "builtin"}]
        )
        loader._check_requirements.return_value = False
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skills", loop=loop)
        result = await cmd_skill_list(ctx)

        assert "✗" in result.content
        assert "tmux" in result.content

    @pytest.mark.asyncio
    async def test_no_skills(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skills=[])
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("/skills", loop=loop)
        result = await cmd_skill_list(ctx)

        assert "No skills found" in result.content


class TestSkillInterceptor:
    @pytest.mark.asyncio
    async def test_injects_single_skill(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=WEATHER_SKILLS,
            skill_content={"weather": "Use the weather API."},
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("$weather what is the forecast", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None  # falls through to LLM
        assert '<skill-content name="weather">' in ctx.msg.content
        assert "Use the weather API." in ctx.msg.content
        assert "what is the forecast" in ctx.msg.content

    @pytest.mark.asyncio
    async def test_injects_multiple_skills(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=MULTI_SKILLS,
            skill_content={
                "weather": "Weather skill content.",
                "github": "GitHub skill content.",
            },
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("$weather $github do something", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None
        assert '<skill-content name="weather">' in ctx.msg.content
        assert '<skill-content name="github">' in ctx.msg.content
        assert "do something" in ctx.msg.content
        # Both skills wrapped in a single system-reminder
        assert ctx.msg.content.count("<system-reminder>") == 1

    @pytest.mark.asyncio
    async def test_skill_ref_anywhere_in_message(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=WEATHER_SKILLS,
            skill_content={"weather": "Weather skill content."},
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("tell me $weather the forecast for NYC", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None
        assert '<skill-content name="weather">' in ctx.msg.content
        assert (
            "tell me  the forecast for NYC" in ctx.msg.content
            or "tell me the forecast for NYC" in ctx.msg.content
        )

    @pytest.mark.asyncio
    async def test_no_match_passes_through(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skills=WEATHER_SKILLS)
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("just a normal message", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None
        assert ctx.msg.content == "just a normal message"

    @pytest.mark.asyncio
    async def test_unknown_ref_ignored(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skills=WEATHER_SKILLS)
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("$nonexistent do something", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None
        assert ctx.msg.content == "$nonexistent do something"

    @pytest.mark.asyncio
    async def test_deduplicates_refs(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(
            skills=WEATHER_SKILLS,
            skill_content={"weather": "Weather skill content."},
        )
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("$weather $weather forecast", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None
        assert ctx.msg.content.count('<skill-content name="weather">') == 1

    @pytest.mark.asyncio
    async def test_dollar_amount_not_matched(self):
        loop, _ = _make_loop()
        loader = _mock_skills_loader(skills=WEATHER_SKILLS)
        loop.context = MagicMock()
        loop.context.skills = loader

        ctx = _make_ctx("I have $100 in my account", loop=loop)
        result = await intercept_skill_refs(ctx)

        assert result is None
        assert ctx.msg.content == "I have $100 in my account"


class TestHelpIncludesSkill:
    @pytest.mark.asyncio
    async def test_help_shows_skill_commands(self):
        loop, _ = _make_loop()
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/help")
        response = await loop._process_message(msg)

        assert response is not None
        assert "/skills" in response.content
        assert "$" in response.content
