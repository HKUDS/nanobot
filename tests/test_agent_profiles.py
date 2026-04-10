"""Tests for named agent profiles."""

import pytest
from nanobot.config.schema import AgentProfile, AgentsConfig, Config


class TestAgentProfileSchema:
    """Test AgentProfile schema."""

    def test_default_profile(self):
        profile = AgentProfile()
        assert profile.system_prompt == ""
        assert profile.model is None
        assert profile.provider is None
        assert profile.temperature is None
        assert profile.max_tokens is None

    def test_profile_with_values(self):
        profile = AgentProfile(
            system_prompt="You are a trader",
            model="gemini/gemini-2.0-flash",
            provider="openrouter",
            temperature=0.7,
        )
        assert profile.system_prompt == "You are a trader"
        assert profile.model == "gemini/gemini-2.0-flash"
        assert profile.provider == "openrouter"
        assert profile.temperature == 0.7

    def test_agents_config_profiles(self):
        agents = AgentsConfig(profiles={
            "trader": AgentProfile(system_prompt="Trade crypto"),
            "writer": AgentProfile(system_prompt="Write articles", model="gpt-4"),
        })
        assert "trader" in agents.profiles
        assert "writer" in agents.profiles
        assert agents.profiles["trader"].system_prompt == "Trade crypto"
        assert agents.profiles["writer"].model == "gpt-4"

    def test_agents_config_empty_profiles(self):
        agents = AgentsConfig()
        assert agents.profiles == {}

    def test_profile_camel_case(self):
        """Profiles should accept camelCase keys."""
        profile = AgentProfile(**{"systemPrompt": "Hello", "maxTokens": 1000})
        assert profile.system_prompt == "Hello"
        assert profile.max_tokens == 1000


class TestContextBuilderPrefix:
    """Test system_prompt_prefix in ContextBuilder."""

    def test_build_system_prompt_without_prefix(self, tmp_path):
        from nanobot.agent.context import ContextBuilder
        ctx = ContextBuilder(tmp_path)
        prompt = ctx.build_system_prompt()
        assert "Agent Profile" not in prompt

    def test_build_system_prompt_with_prefix(self, tmp_path):
        from nanobot.agent.context import ContextBuilder
        ctx = ContextBuilder(tmp_path)
        prompt = ctx.build_system_prompt(system_prompt_prefix="You are a trader")
        assert "Agent Profile" in prompt
        assert "You are a trader" in prompt

    def test_build_messages_with_prefix(self, tmp_path):
        from nanobot.agent.context import ContextBuilder
        ctx = ContextBuilder(tmp_path)
        messages = ctx.build_messages(
            history=[],
            current_message="Hello",
            system_prompt_prefix="Custom persona",
        )
        system_msg = messages[0]["content"]
        assert "Custom persona" in system_msg


class TestCronPayloadAgent:
    """Test agent field in CronPayload."""

    def test_cron_payload_agent_default(self):
        from nanobot.cron.types import CronPayload
        payload = CronPayload()
        assert payload.agent is None

    def test_cron_payload_agent_set(self):
        from nanobot.cron.types import CronPayload
        payload = CronPayload(agent="trader")
        assert payload.agent == "trader"


class TestCronServiceAgent:
    """Test agent field persistence in CronService."""

    def test_add_job_with_agent(self, tmp_path):
        from nanobot.cron.service import CronService
        from nanobot.cron.types import CronSchedule

        store_path = tmp_path / "jobs.json"
        svc = CronService(store_path)

        job = svc.add_job(
            name="test",
            schedule=CronSchedule(kind="every", every_ms=60000),
            message="Do something",
            agent="trader",
            channel="cli",
            to="direct",
        )
        assert job.payload.agent == "trader"

        # Verify persistence
        svc2 = CronService(store_path)
        jobs = svc2.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].payload.agent == "trader"

    def test_add_job_without_agent(self, tmp_path):
        from nanobot.cron.service import CronService
        from nanobot.cron.types import CronSchedule

        store_path = tmp_path / "jobs.json"
        svc = CronService(store_path)

        job = svc.add_job(
            name="test",
            schedule=CronSchedule(kind="every", every_ms=60000),
            message="Do something",
            channel="cli",
            to="direct",
        )
        assert job.payload.agent is None
