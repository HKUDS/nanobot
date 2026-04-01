"""Tests for skill filtering by sender/channel."""

from pathlib import Path

import pytest
from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import filter_skill_names, resolve_skill_filter
from nanobot.config.schema import AgentDefaults, SkillsConfig, SkillsFilterConfig


class TestSkillsFilterConfig:
    def test_default_includes_all(self):
        cfg = SkillsFilterConfig()
        assert cfg.include == ["*"]
        assert cfg.exclude == []

    def test_custom_include_exclude(self):
        cfg = SkillsFilterConfig(include=["coding-*"], exclude=["ljg-*"])
        assert cfg.include == ["coding-*"]
        assert cfg.exclude == ["ljg-*"]


class TestSkillsConfig:
    def test_defaults_empty(self):
        cfg = SkillsConfig()
        assert cfg.senders == {}
        assert cfg.channels == {}
        assert cfg.include == ["*"]
        assert cfg.exclude == []

    def test_sender_config(self):
        cfg = SkillsConfig(senders={"petch": SkillsFilterConfig(exclude=["coding-*"])})
        assert "petch" in cfg.senders
        assert cfg.senders["petch"].exclude == ["coding-*"]

    def test_channel_config(self):
        cfg = SkillsConfig(channels={"develop": SkillsFilterConfig(include=["coding-*"])})
        assert cfg.channels["develop"].include == ["coding-*"]


class TestAgentDefaultsSkills:
    def test_has_skills_config(self):
        defaults = AgentDefaults()
        assert isinstance(defaults.skills, SkillsConfig)

    def test_from_dict(self):
        data = {
            "skills": {
                "exclude": ["peppa-*"],
                "senders": {
                    "petch": {"exclude": ["coding-*", "ljg-*"]}
                },
                "channels": {
                    "develop": {"include": ["coding-*"]}
                }
            }
        }
        defaults = AgentDefaults.model_validate(data)
        assert defaults.skills.exclude == ["peppa-*"]
        assert "petch" in defaults.skills.senders


class TestFilterSkillNames:
    def test_include_all_no_exclude(self):
        names = ["coding", "weather", "ljg-card"]
        assert filter_skill_names(names, ["*"], []) == ["coding", "weather", "ljg-card"]

    def test_exclude_glob(self):
        names = ["coding", "weather", "ljg-card", "ljg-learn"]
        result = filter_skill_names(names, ["*"], ["ljg-*"])
        assert result == ["coding", "weather"]

    def test_include_glob(self):
        names = ["coding", "coding-agent", "weather", "ljg-card"]
        result = filter_skill_names(names, ["coding*"], [])
        assert result == ["coding", "coding-agent"]

    def test_include_and_exclude(self):
        names = ["coding", "coding-agent", "weather"]
        result = filter_skill_names(names, ["*"], ["weather"])
        assert result == ["coding", "coding-agent"]

    def test_exact_match(self):
        names = ["coding", "weather"]
        result = filter_skill_names(names, ["coding"], [])
        assert result == ["coding"]

    def test_empty_input(self):
        assert filter_skill_names([], ["*"], ["ljg-*"]) == []

    def test_exclude_overrides_include(self):
        names = ["coding", "coding-agent"]
        result = filter_skill_names(names, ["coding*"], ["coding-agent"])
        assert result == ["coding"]


class TestResolveSkillFilter:
    def test_default_only(self):
        cfg = SkillsConfig(exclude=["peppa-*"])
        inc, exc = resolve_skill_filter(cfg)
        assert inc == ["*"]
        assert exc == ["peppa-*"]

    def test_sender_merges_with_default(self):
        cfg = SkillsConfig(
            exclude=["peppa-*"],
            senders={"petch": SkillsFilterConfig(exclude=["coding-*", "ljg-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="petch")
        assert inc == ["*"]
        assert set(exc) == {"peppa-*", "coding-*", "ljg-*"}

    def test_sender_include_replaces_default(self):
        cfg = SkillsConfig(
            senders={"petch": SkillsFilterConfig(include=["weather", "peppa-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="petch")
        assert inc == ["weather", "peppa-*"]

    def test_channel_overrides_everything(self):
        cfg = SkillsConfig(
            exclude=["peppa-*"],
            senders={"haibin": SkillsFilterConfig(exclude=["ljg-*"])},
            channels={"develop": SkillsFilterConfig(include=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="haibin", channel_name="develop")
        assert inc == ["coding-*"]
        assert exc == []

    def test_unknown_sender_uses_default(self):
        cfg = SkillsConfig(
            exclude=["peppa-*"],
            senders={"petch": SkillsFilterConfig(exclude=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="stranger")
        assert inc == ["*"]
        assert exc == ["peppa-*"]

    def test_unknown_channel_falls_to_sender(self):
        cfg = SkillsConfig(
            senders={"haibin": SkillsFilterConfig(exclude=["peppa-*"])},
            channels={"develop": SkillsFilterConfig(include=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="haibin", channel_name="general")
        assert inc == ["*"]
        assert exc == ["peppa-*"]

    def test_no_sender_no_channel(self):
        cfg = SkillsConfig()
        inc, exc = resolve_skill_filter(cfg)
        assert inc == ["*"]
        assert exc == []

    def test_case_insensitive_sender(self):
        cfg = SkillsConfig(
            senders={"petch": SkillsFilterConfig(exclude=["coding-*"])}
        )
        inc, exc = resolve_skill_filter(cfg, sender_name="Petch")
        assert "coding-*" in exc


class TestSkillFilteringIntegration:
    """Integration: ContextBuilder respects skills filtering."""

    def _make_workspace(self, tmp_path: Path, skill_names: list[str]) -> Path:
        ws = tmp_path / "workspace"
        ws.mkdir()
        skills_dir = ws / "skills"
        skills_dir.mkdir()
        for name in skill_names:
            skill_dir = skills_dir / name
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: {name} skill\n---\n# {name}\nDo {name} stuff.\n"
            )
        (ws / "memory").mkdir()
        return ws

    def test_no_config_includes_all(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        ctx = ContextBuilder(ws)
        prompt = ctx.build_system_prompt()
        assert "coding" in prompt
        assert "weather" in prompt
        assert "ljg-card" in prompt

    def test_exclude_filters_skills(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card", "ljg-learn"])
        cfg = SkillsConfig(exclude=["ljg-*"])
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt()
        assert "coding" in prompt
        assert "weather" in prompt
        assert "ljg-card" not in prompt
        assert "ljg-learn" not in prompt

    def test_sender_exclude(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        cfg = SkillsConfig(
            senders={"petch": SkillsFilterConfig(exclude=["coding*", "ljg-*"])}
        )
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt(sender_name="petch")
        assert "weather" in prompt
        assert "ljg-card" not in prompt

    def test_channel_override(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        cfg = SkillsConfig(
            channels={"develop": SkillsFilterConfig(include=["coding*"])}
        )
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt(sender_name="haibin", channel_name="develop")
        assert "coding" in prompt
        assert "weather" not in prompt
        assert "ljg-card" not in prompt

    def test_sender_with_no_matching_channel_uses_sender(self, tmp_path):
        ws = self._make_workspace(tmp_path, ["coding", "weather", "ljg-card"])
        cfg = SkillsConfig(
            senders={"haibin": SkillsFilterConfig(exclude=["ljg-*"])},
            channels={"develop": SkillsFilterConfig(include=["coding*"])}
        )
        ctx = ContextBuilder(ws, skills_config=cfg)
        prompt = ctx.build_system_prompt(sender_name="haibin", channel_name="general")
        assert "coding" in prompt
        assert "weather" in prompt
        assert "ljg-card" not in prompt
