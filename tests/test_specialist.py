"""Tests for specialist agents: loader, runner, delegate tool, skill isolation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nanobot.agent.specialist import SpecialistLoader, SpecialistRunner
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.tools.delegate import DelegateTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_specialist(workspace: Path, name: str, description: str = "A test specialist",
                       model: str | None = None, max_iterations: int = 25,
                       body: str = "You are a test specialist.") -> Path:
    """Create a specialist SOUL.md in the workspace and return its directory."""
    spec_dir = workspace / "specialists" / name
    spec_dir.mkdir(parents=True, exist_ok=True)
    frontmatter_lines = [
        "---",
        f"name: {name}",
        f'description: "{description}"',
    ]
    if model:
        frontmatter_lines.append(f"model: {model}")
    frontmatter_lines.append(f"max_iterations: {max_iterations}")
    frontmatter_lines.append("---")
    frontmatter_lines.append("")
    frontmatter_lines.append(body)
    (spec_dir / "SOUL.md").write_text("\n".join(frontmatter_lines), encoding="utf-8")
    return spec_dir


def _create_skill(base_dir: Path, name: str, description: str = "A skill",
                  shared: bool | None = None) -> Path:
    """Create a SKILL.md under base_dir/{name}/ and return the skill directory."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}", f'description: "{description}"']
    if shared is not None:
        lines.append(f"shared: {str(shared).lower()}")
    lines += ["---", "", f"# {name} skill instructions"]
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")
    return skill_dir


# ===========================================================================
# SpecialistLoader
# ===========================================================================

class TestSpecialistLoader:
    def test_list_empty_when_no_dir(self, tmp_path: Path) -> None:
        loader = SpecialistLoader(tmp_path)
        assert loader.list_specialists() == []

    def test_list_empty_when_dir_exists_but_no_specialists(self, tmp_path: Path) -> None:
        (tmp_path / "specialists").mkdir()
        loader = SpecialistLoader(tmp_path)
        assert loader.list_specialists() == []

    def test_list_discovers_specialist(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "ventas", description="Experto en ventas")
        loader = SpecialistLoader(tmp_path)
        specs = loader.list_specialists()
        assert len(specs) == 1
        assert specs[0]["name"] == "ventas"
        assert specs[0]["description"] == "Experto en ventas"
        assert specs[0]["max_iterations"] == 25
        assert specs[0]["model"] is None

    def test_list_discovers_multiple_sorted(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "ventas")
        _create_specialist(tmp_path, "almacen")
        loader = SpecialistLoader(tmp_path)
        names = [s["name"] for s in loader.list_specialists()]
        assert names == ["almacen", "ventas"]

    def test_load_specialist_returns_none_when_missing(self, tmp_path: Path) -> None:
        (tmp_path / "specialists").mkdir()
        loader = SpecialistLoader(tmp_path)
        assert loader.load_specialist("nonexistent") is None

    def test_load_specialist_returns_data(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "compras", model="gpt-4o", max_iterations=10)
        loader = SpecialistLoader(tmp_path)
        spec = loader.load_specialist("compras")
        assert spec is not None
        assert spec["name"] == "compras"
        assert spec["model"] == "gpt-4o"
        assert spec["max_iterations"] == 10
        assert "You are a test specialist" in spec["soul_content"]

    def test_build_summary_empty(self, tmp_path: Path) -> None:
        loader = SpecialistLoader(tmp_path)
        assert loader.build_specialists_summary() == ""

    def test_build_summary_xml(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "ventas", description="Experto en ventas")
        loader = SpecialistLoader(tmp_path)
        summary = loader.build_specialists_summary()
        assert "<specialists>" in summary
        assert "<name>ventas</name>" in summary
        assert "<description>Experto en ventas</description>" in summary
        assert "</specialists>" in summary

    def test_build_summary_escapes_xml(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "test", description="Uses <tags> & stuff")
        loader = SpecialistLoader(tmp_path)
        summary = loader.build_specialists_summary()
        assert "&lt;tags&gt;" in summary
        assert "&amp; stuff" in summary

    def test_skips_dir_without_soul(self, tmp_path: Path) -> None:
        (tmp_path / "specialists" / "empty").mkdir(parents=True)
        _create_specialist(tmp_path, "valid")
        loader = SpecialistLoader(tmp_path)
        assert len(loader.list_specialists()) == 1

    def test_skips_specialist_without_required_fields(self, tmp_path: Path) -> None:
        """A SOUL.md missing name or description should be skipped."""
        spec_dir = tmp_path / "specialists" / "bad"
        spec_dir.mkdir(parents=True)
        (spec_dir / "SOUL.md").write_text("---\nname: bad\n---\nNo description field.", encoding="utf-8")
        loader = SpecialistLoader(tmp_path)
        assert loader.list_specialists() == []

    def test_parse_frontmatter_no_frontmatter(self) -> None:
        meta, body = SpecialistLoader._parse_frontmatter("Just plain content")
        assert meta == {}
        assert body == "Just plain content"


# ===========================================================================
# SkillsLoader: shared_only and extra_skills_dirs
# ===========================================================================

class TestSkillsSharedIsolation:
    def test_shared_only_excludes_non_shared_workspace_skills(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "public-skill", shared=True)
        _create_skill(skills_dir, "private-skill", shared=False)
        _create_skill(skills_dir, "default-skill")  # no shared field → shared by default

        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins", shared_only=True)
        names = [s["name"] for s in loader.list_skills(filter_unavailable=False)]

        assert "public-skill" in names
        assert "default-skill" in names
        assert "private-skill" not in names

    def test_main_agent_sees_all_skills(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "public-skill")
        _create_skill(skills_dir, "private-skill", shared=False)

        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins", shared_only=False)
        names = [s["name"] for s in loader.list_skills(filter_unavailable=False)]

        assert "public-skill" in names
        assert "private-skill" in names

    def test_extra_skills_dirs_highest_priority(self, tmp_path: Path) -> None:
        workspace_skills = tmp_path / "skills"
        _create_skill(workspace_skills, "shared-skill", description="workspace version")

        extra = tmp_path / "extra"
        _create_skill(extra, "private-skill", description="specialist private")
        _create_skill(extra, "shared-skill", description="overridden by extra")

        loader = SkillsLoader(
            tmp_path,
            builtin_skills_dir=tmp_path / "no-builtins",
            extra_skills_dirs=[extra],
        )
        skills = loader.list_skills(filter_unavailable=False)
        by_name = {s["name"]: s for s in skills}

        assert "private-skill" in by_name
        assert by_name["private-skill"]["source"] == "extra"
        # extra overrides workspace when same name
        assert by_name["shared-skill"]["source"] == "extra"

    def test_extra_skills_not_filtered_by_shared(self, tmp_path: Path) -> None:
        """Extra (specialist-private) skills are never filtered by shared_only."""
        extra = tmp_path / "extra"
        _create_skill(extra, "my-private", shared=False)

        loader = SkillsLoader(
            tmp_path,
            builtin_skills_dir=tmp_path / "no-builtins",
            extra_skills_dirs=[extra],
            shared_only=True,
        )
        names = [s["name"] for s in loader.list_skills(filter_unavailable=False)]
        assert "my-private" in names

    def test_load_skill_respects_shared_only(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "private-skill", shared=False)

        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins", shared_only=True)
        assert loader.load_skill("private-skill") is None

        loader_main = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins", shared_only=False)
        assert loader_main.load_skill("private-skill") is not None

    def test_load_skill_finds_extra_first(self, tmp_path: Path) -> None:
        workspace_skills = tmp_path / "skills"
        _create_skill(workspace_skills, "overlap", description="workspace")

        extra = tmp_path / "extra"
        _create_skill(extra, "overlap", description="extra version")

        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins", extra_skills_dirs=[extra])
        content = loader.load_skill("overlap")
        assert content is not None
        assert "extra version" in content

    def test_is_shared_defaults_true(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "normal")
        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins")
        assert loader._is_shared("normal") is True

    def test_is_shared_false_top_level(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "secret", shared=False)
        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins")
        assert loader._is_shared("secret") is False

    def test_is_shared_false_via_metadata(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills" / "meta-secret"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(
            '---\nname: meta-secret\ndescription: "test"\n'
            'metadata: \'{"nanobot": {"shared": false}}\'\n---\nContent\n',
            encoding="utf-8",
        )
        loader = SkillsLoader(tmp_path, builtin_skills_dir=tmp_path / "no-builtins")
        assert loader._is_shared("meta-secret") is False

    def test_specialist_cannot_see_other_specialist_skills(self, tmp_path: Path) -> None:
        """Specialist A's private skills should not appear for specialist B."""
        spec_a_skills = tmp_path / "specialists" / "A" / "skills"
        _create_skill(spec_a_skills, "a-only", description="A's private")

        spec_b_skills = tmp_path / "specialists" / "B" / "skills"
        _create_skill(spec_b_skills, "b-only", description="B's private")

        loader_a = SkillsLoader(
            tmp_path, builtin_skills_dir=tmp_path / "no-builtins",
            extra_skills_dirs=[spec_a_skills], shared_only=True,
        )
        loader_b = SkillsLoader(
            tmp_path, builtin_skills_dir=tmp_path / "no-builtins",
            extra_skills_dirs=[spec_b_skills], shared_only=True,
        )

        names_a = [s["name"] for s in loader_a.list_skills(filter_unavailable=False)]
        names_b = [s["name"] for s in loader_b.list_skills(filter_unavailable=False)]

        assert "a-only" in names_a
        assert "b-only" not in names_a
        assert "b-only" in names_b
        assert "a-only" not in names_b


# ===========================================================================
# DelegateTool
# ===========================================================================

class TestDelegateTool:
    def test_schema(self) -> None:
        runner = MagicMock()
        tool = DelegateTool(runner=runner)
        assert tool.name == "delegate"
        assert "specialist" in tool.parameters["properties"]
        assert "task" in tool.parameters["properties"]
        assert tool.parameters["required"] == ["specialist", "task"]

    def test_set_context(self) -> None:
        runner = MagicMock()
        tool = DelegateTool(runner=runner)
        tool.set_context("telegram", "12345")
        assert tool._session_key == "telegram:12345"

    @pytest.mark.asyncio
    async def test_execute_calls_runner(self) -> None:
        runner = MagicMock()
        runner.run = AsyncMock(return_value="specialist result")
        tool = DelegateTool(runner=runner)
        tool.set_context("cli", "direct")

        result = await tool.execute(specialist="ventas", task="price of X?")

        runner.run.assert_called_once_with(
            name="ventas", task="price of X?", session_key="cli:direct",
        )
        assert result == "specialist result"

    @pytest.mark.asyncio
    async def test_execute_catches_exception(self) -> None:
        runner = MagicMock()
        runner.run = AsyncMock(side_effect=RuntimeError("boom"))
        tool = DelegateTool(runner=runner)

        result = await tool.execute(specialist="bad", task="fail")
        assert "Error" in result
        assert "boom" in result


# ===========================================================================
# SpecialistRunner
# ===========================================================================

class TestSpecialistRunner:
    @pytest.mark.asyncio
    async def test_run_returns_error_for_missing_specialist(self, tmp_path: Path) -> None:
        (tmp_path / "specialists").mkdir()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        runner = SpecialistRunner(provider=provider, workspace=tmp_path)

        result = await runner.run("nonexistent", "do something")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_run_executes_llm_loop(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "test-spec", description="Test specialist")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        from nanobot.providers.base import LLMResponse
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="specialist answer", tool_calls=[])
        )

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        result = await runner.run("test-spec", "what is the answer?")

        assert result == "specialist answer"
        provider.chat_with_retry.assert_called_once()

        # Verify system prompt contains specialist identity
        call_kwargs = provider.chat_with_retry.call_args
        messages = call_kwargs.kwargs["messages"]
        system_msg = messages[0]["content"]
        assert "test-spec" in system_msg
        assert "You are a test specialist" in system_msg

    @pytest.mark.asyncio
    async def test_run_uses_specialist_model_override(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "custom-model", model="gpt-4o")

        provider = MagicMock()
        provider.get_default_model.return_value = "default-model"

        from nanobot.providers.base import LLMResponse
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="done", tool_calls=[])
        )

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        await runner.run("custom-model", "task")

        call_kwargs = provider.chat_with_retry.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o"

    @pytest.mark.asyncio
    async def test_run_includes_shared_memory(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "mem-spec")
        # Create memory
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "MEMORY.md").write_text("User prefers Spanish.", encoding="utf-8")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        from nanobot.providers.base import LLMResponse
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[])
        )

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        await runner.run("mem-spec", "task")

        system_msg = provider.chat_with_retry.call_args.kwargs["messages"][0]["content"]
        assert "User prefers Spanish" in system_msg

    @pytest.mark.asyncio
    async def test_run_includes_session_history(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "hist-spec")

        from nanobot.session.manager import SessionManager
        sessions = SessionManager(tmp_path)
        session = sessions.get_or_create("cli:direct")
        session.add_message("user", "Hello specialist world")
        sessions.save(session)

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        from nanobot.providers.base import LLMResponse
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[])
        )

        runner = SpecialistRunner(
            provider=provider, workspace=tmp_path, session_manager=sessions,
        )
        await runner.run("hist-spec", "task", session_key="cli:direct")

        system_msg = provider.chat_with_retry.call_args.kwargs["messages"][0]["content"]
        assert "Hello specialist world" in system_msg

    @pytest.mark.asyncio
    async def test_run_catches_exception(self, tmp_path: Path) -> None:
        _create_specialist(tmp_path, "fail-spec")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("LLM exploded"))

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        result = await runner.run("fail-spec", "task")
        assert "Error" in result
        assert "LLM exploded" in result

    @pytest.mark.asyncio
    async def test_run_with_tool_calls(self, tmp_path: Path, monkeypatch) -> None:
        """Verify the specialist executes tool calls and loops."""
        _create_specialist(tmp_path, "tool-spec")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        from nanobot.providers.base import LLMResponse, ToolCallRequest

        call_count = {"n": 0}

        async def scripted_chat(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
                )
            return LLMResponse(content="final answer", tool_calls=[])

        provider.chat_with_retry = scripted_chat

        async def fake_execute(self, name, arguments):
            return "file1.txt\nfile2.txt"

        monkeypatch.setattr("nanobot.agent.tools.registry.ToolRegistry.execute", fake_execute)

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        result = await runner.run("tool-spec", "list files")
        assert result == "final answer"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_specialist_sees_shared_skills_only(self, tmp_path: Path) -> None:
        """Specialist prompt should include shared skills but not private ones."""
        _create_specialist(tmp_path, "skill-spec")
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "public-tool", description="Everyone can use")
        _create_skill(skills_dir, "secret-tool", description="Main agent only", shared=False)

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        from nanobot.providers.base import LLMResponse
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[])
        )

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        await runner.run("skill-spec", "task")

        system_msg = provider.chat_with_retry.call_args.kwargs["messages"][0]["content"]
        assert "public-tool" in system_msg
        assert "secret-tool" not in system_msg

    @pytest.mark.asyncio
    async def test_specialist_sees_own_private_skills(self, tmp_path: Path) -> None:
        """Specialist should see its own private skills."""
        spec_dir = _create_specialist(tmp_path, "priv-spec")
        spec_skills = spec_dir / "skills"
        _create_skill(spec_skills, "my-private-tool", description="Only for priv-spec")

        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        from nanobot.providers.base import LLMResponse
        provider.chat_with_retry = AsyncMock(
            return_value=LLMResponse(content="ok", tool_calls=[])
        )

        runner = SpecialistRunner(provider=provider, workspace=tmp_path)
        await runner.run("priv-spec", "task")

        system_msg = provider.chat_with_retry.call_args.kwargs["messages"][0]["content"]
        assert "my-private-tool" in system_msg


# ===========================================================================
# ContextBuilder integration
# ===========================================================================

class TestContextBuilderSpecialists:
    def test_system_prompt_includes_specialists_section(self, tmp_path: Path) -> None:
        from nanobot.agent.context import ContextBuilder

        _create_specialist(tmp_path, "ventas", description="Experto en ventas")
        ctx = ContextBuilder(tmp_path)
        prompt = ctx.build_system_prompt()

        assert "# Specialists" in prompt
        assert "delegate" in prompt
        assert "<name>ventas</name>" in prompt

    def test_system_prompt_no_specialists_section_when_empty(self, tmp_path: Path) -> None:
        from nanobot.agent.context import ContextBuilder

        ctx = ContextBuilder(tmp_path)
        prompt = ctx.build_system_prompt()

        assert "# Specialists" not in prompt
