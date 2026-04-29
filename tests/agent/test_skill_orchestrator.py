"""Tests for Skill Orchestrator functionality.

Covers:
- Skill selection based on user input (Chinese/English)
- Top-k skill limit
- Orchestrator toggle (disabled = old behavior)
- Structured selection records
- Validation warnings
- Backward compatibility with existing tests
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.orchestrator import (
    SkillCandidate,
    SkillOrchestrator,
    SkillSelectionRecord,
    SkillSkipped,
    _detect_language,
    _is_chinese_char,
    _tokenize,
)
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.registry import ToolRegistry


def _write_skill(
    base: Path,
    name: str,
    *,
    description: str = "",
    triggers: list[str] | None = None,
    related_tools: list[str] | None = None,
    always: bool = False,
    body: str = "# Skill\n",
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Create ``base / name / SKILL.md`` with optional metadata."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    frontmatter: dict[str, Any] = {"name": name}
    if description:
        frontmatter["description"] = description
    if always:
        frontmatter["always"] = True

    if triggers or related_tools or metadata:
        nanobot_meta: dict[str, Any] = metadata or {}
        if triggers:
            nanobot_meta["triggers"] = triggers
        if related_tools:
            nanobot_meta["related_tools"] = related_tools
        if nanobot_meta:
            frontmatter["metadata"] = json.dumps({"nanobot": nanobot_meta}, separators=(",", ":"))

    import yaml

    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, str) and "\n" in value:
            lines.append(f"{key}: |")
            for line in value.split("\n"):
                lines.append(f"  {line}")
        else:
            lines.append(yaml.dump({key: value}, allow_unicode=True).strip())
    lines.extend(["---", "", body])

    path = skill_dir / "SKILL.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


class TestLanguageDetection:
    """Tests for Chinese/English language detection."""

    def test_is_chinese_char(self) -> None:
        assert _is_chinese_char("中") is True
        assert _is_chinese_char("文") is True
        assert _is_chinese_char("a") is False
        assert _is_chinese_char("1") is False
        assert _is_chinese_char(" ") is False

    def test_detect_language_english(self) -> None:
        assert _detect_language("Hello world") == "en"
        assert _detect_language("What is the weather today?") == "en"
        assert _detect_language("") == "en"

    def test_detect_language_chinese(self) -> None:
        assert _detect_language("今天天气怎么样") == "zh"
        assert _detect_language("我需要帮助") == "zh"

    def test_detect_language_mixed(self) -> None:
        assert _detect_language("今天 weather 怎么样") == "zh"
        assert _detect_language("Hello 世界") == "en"

    def test_tokenize_english(self) -> None:
        tokens = _tokenize("What is the weather today?")
        assert "what" in tokens
        assert "weather" in tokens
        assert "today" in tokens
        assert "the" not in tokens

    def test_tokenize_chinese(self) -> None:
        tokens = _tokenize("今天天气")
        assert "今" in tokens
        assert "天" in tokens
        assert "气" in tokens


class TestSkillOrchestrator:
    """Tests for SkillOrchestrator core functionality."""

    def test_orchestrator_disabled_by_default(self, tmp_path: Path) -> None:
        """Orchestrator should be disabled by default for backward compatibility."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        builtin.mkdir()

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader)

        assert orchestrator.enabled is False

    def test_orchestrator_enabled(self, tmp_path: Path) -> None:
        """Orchestrator can be enabled explicitly."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        builtin.mkdir()

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True)

        assert orchestrator.enabled is True

    def test_select_skills_when_disabled(self, tmp_path: Path) -> None:
        """When disabled, select_skills should return a record with enabled=False."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        _write_skill(builtin, "weather", description="Weather forecasts")

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=False)

        record = orchestrator.select_skills("What is the weather?")

        assert record.enabled is False
        assert record.status == "disabled"
        assert record.selected == []

    def test_trigger_matching(self, tmp_path: Path) -> None:
        """Skills with matching triggers should be selected."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        _write_skill(
            builtin,
            "weather",
            description="Weather forecasts",
            triggers=["weather", "天气", "temperature", "气温"],
        )
        _write_skill(
            builtin,
            "cron",
            description="Schedule tasks",
            triggers=["cron", "schedule", "reminder", "定时", "提醒"],
        )

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("What is the weather today?")

        assert record.enabled is True
        assert "weather" in record.selected
        assert "cron" not in record.selected

    def test_trigger_matching_chinese(self, tmp_path: Path) -> None:
        """Chinese triggers should match Chinese user input."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        _write_skill(
            builtin,
            "weather",
            description="天气预报",
            triggers=["weather", "天气", "temperature", "气温"],
        )
        _write_skill(
            builtin,
            "cron",
            description="定时任务",
            triggers=["cron", "schedule", "reminder", "定时", "提醒"],
        )

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("今天天气怎么样？")

        assert "weather" in record.selected
        assert "cron" not in record.selected

    def test_description_similarity(self, tmp_path: Path) -> None:
        """Skills with description matching user input should be selected."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        _write_skill(
            builtin,
            "weather",
            description="Get current weather and forecasts for any city",
        )
        _write_skill(
            builtin,
            "summarize",
            description="Summarize long text and documents concisely",
        )

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("Can you give me a forecast for London?")

        assert "weather" in record.selected

    def test_top_k_limit(self, tmp_path: Path) -> None:
        """Only top-k skills should be selected."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        _write_skill(builtin, "skill1", description="weather forecast", triggers=["weather"])
        _write_skill(builtin, "skill2", description="temperature check", triggers=["temperature"])
        _write_skill(builtin, "skill3", description="wind speed", triggers=["wind"])
        _write_skill(builtin, "skill4", description="humidity level", triggers=["humidity"])

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("weather temperature wind humidity")

        assert len(record.selected) == 2

        skipped_by_limit = [s for s in record.skipped if s.reason == "exceeded max_skills limit"]
        assert len(skipped_by_limit) > 0

    def test_always_skills_always_included(self, tmp_path: Path) -> None:
        """Always skills should be in always_skills list regardless of matching."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        _write_skill(builtin, "memory", description="Memory system", always=True)
        _write_skill(builtin, "weather", description="Weather", triggers=["weather"])

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("Tell me something")

        assert "memory" in record.always_skills

    def test_related_tools_matching(self, tmp_path: Path) -> None:
        """Skills with related_tools matching user input should be selected."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        _write_skill(
            builtin,
            "weather",
            description="Weather using curl",
            related_tools=["exec", "web_fetch"],
        )
        _write_skill(
            builtin,
            "summarize",
            description="Summarize using grep",
            related_tools=["grep", "read_file"],
        )

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("Can you execute a command to check?")

        assert "weather" in record.selected


class TestSkillValidationWarnings:
    """Tests for skill validation warnings."""

    def test_empty_skill_content_warning(self, tmp_path: Path) -> None:
        """Skills with empty content after frontmatter should generate warning."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        skill_dir = builtin / "empty_skill"
        skill_dir.mkdir(parents=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text("---\nname: empty_skill\n---\n", encoding="utf-8")

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        record = orchestrator.select_skills("test")

        empty_warnings = [w for w in record.warnings if "empty content" in w.lower()]
        assert len(empty_warnings) > 0

    def test_unknown_tool_reference_warning(self, tmp_path: Path) -> None:
        """Skills referencing unknown tools should generate warning."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        _write_skill(
            builtin,
            "test_skill",
            description="Test skill",
            related_tools=["nonexistent_tool"],
        )

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        registry = ToolRegistry()
        record = orchestrator.select_skills("test", tool_registry=registry)

        tool_warnings = [w for w in record.warnings if "unknown tool" in w.lower() or "nonexistent_tool" in w]
        assert len(tool_warnings) > 0

    def test_known_tool_no_warning(self, tmp_path: Path) -> None:
        """Skills referencing known tools should NOT generate warning."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        _write_skill(
            builtin,
            "test_skill",
            description="Test skill",
            related_tools=["read_file"],
        )

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True, max_skills=2)

        class FakeTool:
            name = "read_file"
            concurrency_safe = True

            def to_schema(self) -> dict:
                return {"name": "read_file"}

            def cast_params(self, params: dict) -> dict:
                return params

            def validate_params(self, params: dict) -> list[str]:
                return []

            async def execute(self, **kwargs: Any) -> Any:
                pass

        registry = ToolRegistry()
        registry.register(FakeTool())

        record = orchestrator.select_skills("test", tool_registry=registry)

        tool_warnings = [w for w in record.warnings if "unknown tool" in w.lower()]
        assert len(tool_warnings) == 0


class TestStructuredRecord:
    """Tests for SkillSelectionRecord structured recording."""

    def test_record_to_dict(self, tmp_path: Path) -> None:
        """Selection record should be serializable to dict."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        _write_skill(builtin, "weather", description="Weather", triggers=["weather"])

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True)

        record = orchestrator.select_skills("What is the weather?")
        record.tools_used = ["read_file"]

        data = record.to_dict()

        assert data["user_input"] == "What is the weather?"
        assert data["enabled"] is True
        assert "weather" in data["selected"]
        assert data["tools_used"] == ["read_file"]
        assert data["status"] == "completed"

    def test_record_tools_used(self, tmp_path: Path) -> None:
        """Tools used can be recorded after selection."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"
        _write_skill(builtin, "weather", description="Weather")

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)
        orchestrator = SkillOrchestrator(loader, enabled=True)

        orchestrator.select_skills("test")
        orchestrator.record_tools_used(["exec", "read_file"])

        assert orchestrator.last_record is not None
        assert orchestrator.last_record.tools_used == ["exec", "read_file"]


class TestContextBuilderIntegration:
    """Tests for ContextBuilder integration with SkillOrchestrator."""

    def test_context_builder_default_disabled(self, tmp_path: Path) -> None:
        """ContextBuilder should have orchestrator disabled by default."""
        workspace = tmp_path / "ws"
        workspace.mkdir()

        ctx = ContextBuilder(workspace)

        assert ctx.skill_orchestrator_enabled is False
        assert ctx.last_skill_selection is None

    def test_context_builder_orchestrator_enabled(self, tmp_path: Path) -> None:
        """ContextBuilder can enable orchestrator."""
        workspace = tmp_path / "ws"
        workspace.mkdir()

        ctx = ContextBuilder(workspace, skill_orchestrator_enabled=True)

        assert ctx.skill_orchestrator_enabled is True

    def test_context_builder_build_system_prompt_with_orchestrator(self, tmp_path: Path) -> None:
        """When orchestrator is enabled and user_input provided, skills should be selected."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        _write_skill(
            skills_dir,
            "weather",
            description="Weather forecasts",
            triggers=["weather"],
            body="# Weather Skill\nThis is how to check weather.",
        )
        _write_skill(
            skills_dir,
            "cron",
            description="Schedule tasks",
            triggers=["cron"],
            body="# Cron Skill\nThis is how to schedule.",
        )

        ctx = ContextBuilder(workspace, skill_orchestrator_enabled=True, skill_orchestrator_max_skills=2)

        prompt = ctx.build_system_prompt(user_input="What is the weather?")

        assert ctx.last_skill_selection is not None
        assert ctx.last_skill_selection.enabled is True
        assert "weather" in ctx.last_skill_selection.selected

        assert "Weather Skill" in prompt or "weather" in prompt.lower()

    def test_context_builder_build_system_prompt_disabled(self, tmp_path: Path) -> None:
        """When orchestrator is disabled, behavior should be unchanged."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        _write_skill(
            skills_dir,
            "weather",
            description="Weather forecasts",
            triggers=["weather"],
            body="# Weather Skill\nThis is how to check weather.",
        )

        ctx_enabled = ContextBuilder(workspace, skill_orchestrator_enabled=True)
        ctx_disabled = ContextBuilder(workspace, skill_orchestrator_enabled=False)

        prompt_enabled = ctx_enabled.build_system_prompt(user_input="What is the weather?")
        prompt_disabled = ctx_disabled.build_system_prompt(user_input="What is the weather?")

        assert ctx_enabled.last_skill_selection is not None
        assert ctx_enabled.last_skill_selection.enabled is True

        assert ctx_disabled.last_skill_selection is None


class TestBackwardCompatibility:
    """Tests to ensure backward compatibility with existing behavior."""

    def test_skills_loader_unchanged(self, tmp_path: Path) -> None:
        """SkillsLoader should work exactly as before."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        builtin = tmp_path / "builtin"

        _write_skill(builtin, "always_skill", description="Always skill", always=True)
        _write_skill(builtin, "regular_skill", description="Regular skill")

        loader = SkillsLoader(workspace, builtin_skills_dir=builtin)

        always = loader.get_always_skills()
        assert "always_skill" in always
        assert "regular_skill" not in always

        skills = loader.list_skills(filter_unavailable=False)
        assert len(skills) == 2

    def test_context_builder_unchanged_when_disabled(self, tmp_path: Path) -> None:
        """ContextBuilder behavior should be unchanged when orchestrator is disabled."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        skills_dir = workspace / "skills"
        skills_dir.mkdir()

        _write_skill(skills_dir, "always_skill", description="Always", always=True, body="# Always\n")
        _write_skill(skills_dir, "regular_skill", description="Regular", body="# Regular\n")

        ctx = ContextBuilder(workspace)

        prompt = ctx.build_system_prompt()

        assert "always_skill" in prompt.lower() or "Always" in prompt
        assert ctx.last_skill_selection is None


class TestSkillCandidate:
    """Tests for SkillCandidate dataclass."""

    def test_skill_candidate_defaults(self) -> None:
        """SkillCandidate should have sensible defaults."""
        candidate = SkillCandidate(name="test", path="/test/SKILL.md")

        assert candidate.name == "test"
        assert candidate.path == "/test/SKILL.md"
        assert candidate.description == ""
        assert candidate.triggers == []
        assert candidate.related_tools == []
        assert candidate.score == 0.0
        assert candidate.match_reason == ""
        assert candidate.is_always is False
        assert candidate.is_available is True
        assert candidate.validation_warnings == []


class TestSkillSkipped:
    """Tests for SkillSkipped dataclass."""

    def test_skill_skipped_defaults(self) -> None:
        """SkillSkipped should have sensible defaults."""
        skipped = SkillSkipped(name="test", reason="no match")

        assert skipped.name == "test"
        assert skipped.reason == "no match"
        assert skipped.score == 0.0
