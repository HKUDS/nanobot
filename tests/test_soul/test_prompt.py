"""Tests for nanobot.soul.prompt module."""

import pytest
from pathlib import Path
from datetime import date

from nanobot.soul.workspace import AgentWorkspace
from nanobot.soul.prompt import (
    SoulPromptBuilder,
    create_default_prompt_builder,
    build_soul_system_prompt,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with soul and memory files."""
    ws_dir = tmp_path / "agent"
    ws = AgentWorkspace(agent_id="test", workspace_dir=ws_dir)
    ws.ensure_soul()
    (ws_dir / "MEMORY.md").write_text(
        "# Long-term Memory\n\nUser prefers dark mode.\n", encoding="utf-8"
    )
    return ws


@pytest.fixture
def bare_workspace(tmp_path):
    """Create a workspace without soul or memory."""
    ws_dir = tmp_path / "bare"
    return AgentWorkspace(agent_id="bare", workspace_dir=ws_dir)


class TestSoulPromptBuilder:
    """Tests for SoulPromptBuilder."""

    def test_empty_builder(self):
        pb = SoulPromptBuilder()
        ws = AgentWorkspace.__new__(AgentWorkspace)
        ws.agent_id = "test"
        ws.workspace_dir = Path("/tmp/test")
        result = pb.build(ws, "base prompt")
        assert result == ""

    def test_single_section(self):
        pb = SoulPromptBuilder()
        pb.add_section("test", lambda ws, base: f"Hello {base}")
        ws = AgentWorkspace.__new__(AgentWorkspace)
        ws.agent_id = "test"
        ws.workspace_dir = Path("/tmp/test")
        result = pb.build(ws, "world")
        assert result == "Hello world"

    def test_multiple_sections(self):
        pb = SoulPromptBuilder()
        pb.add_section("a", lambda ws, base: "Section A")
        pb.add_section("b", lambda ws, base: "Section B")
        ws = AgentWorkspace.__new__(AgentWorkspace)
        ws.agent_id = "test"
        ws.workspace_dir = Path("/tmp/test")
        result = pb.build(ws, "")
        assert "Section A" in result
        assert "Section B" in result

    def test_empty_section_skipped(self):
        pb = SoulPromptBuilder()
        pb.add_section("a", lambda ws, base: "Content")
        pb.add_section("b", lambda ws, base: "")
        pb.add_section("c", lambda ws, base: "More")
        ws = AgentWorkspace.__new__(AgentWorkspace)
        ws.agent_id = "test"
        ws.workspace_dir = Path("/tmp/test")
        result = pb.build(ws, "")
        assert "Content" in result
        assert "More" in result

    def test_section_error_handled(self):
        pb = SoulPromptBuilder()
        pb.add_section("ok", lambda ws, base: "OK")
        pb.add_section("bad", lambda ws, base: 1 / 0)  # raises
        pb.add_section("ok2", lambda ws, base: "Also OK")
        ws = AgentWorkspace.__new__(AgentWorkspace)
        ws.agent_id = "test"
        ws.workspace_dir = Path("/tmp/test")
        result = pb.build(ws, "")
        assert "OK" in result
        assert "Also OK" in result


class TestCreateDefaultPromptBuilder:
    """Tests for create_default_prompt_builder."""

    def test_includes_base_prompt(self, workspace):
        pb = create_default_prompt_builder()
        result = pb.build(workspace, "You are helpful.")
        assert "You are helpful." in result

    def test_includes_personality(self, workspace):
        pb = create_default_prompt_builder(personality="Friendly and warm")
        result = pb.build(workspace, "base")
        assert "Friendly and warm" in result

    def test_includes_memory_recall(self, workspace):
        pb = create_default_prompt_builder()
        result = pb.build(workspace, "base")
        assert "Memory Recall" in result
        assert "memory_search" in result

    def test_includes_current_date(self, workspace):
        pb = create_default_prompt_builder()
        result = pb.build(workspace, "base")
        assert date.today().isoformat() in result

    def test_includes_workspace_path(self, workspace):
        pb = create_default_prompt_builder()
        result = pb.build(workspace, "base")
        assert str(workspace.workspace_dir) in result

    def test_includes_soul_content(self, workspace):
        pb = create_default_prompt_builder()
        result = pb.build(workspace, "base")
        assert "SOUL.md" in result
        assert "Core Truths" in result

    def test_includes_memory_content(self, workspace):
        pb = create_default_prompt_builder()
        result = pb.build(workspace, "base")
        assert "dark mode" in result

    def test_bare_workspace_minimal(self, bare_workspace):
        pb = create_default_prompt_builder()
        result = pb.build(bare_workspace, "base")
        assert "base" in result
        assert "Memory Recall" in result
        # No context files section when no soul/memory
        assert "Project Context Files" not in result


class TestBuildSoulSystemPrompt:
    """Tests for build_soul_system_prompt convenience function."""

    def test_basic_output(self, workspace):
        prompt = build_soul_system_prompt(workspace, "You are a helpful AI.")
        assert "You are a helpful AI." in prompt
        assert "Memory Recall" in prompt
        assert "SOUL.md" in prompt

    def test_with_personality(self, workspace):
        prompt = build_soul_system_prompt(
            workspace, "base", personality="Sarcastic but kind"
        )
        assert "Sarcastic but kind" in prompt

    def test_output_type(self, workspace):
        prompt = build_soul_system_prompt(workspace, "base")
        assert isinstance(prompt, str)
        assert len(prompt) > 100  # Should be substantial
