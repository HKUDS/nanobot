"""Tests for nanobot.soul.workspace module."""

import pytest
from pathlib import Path

from nanobot.soul.workspace import (
    AgentWorkspace,
    truncate_bootstrap,
    load_bootstrap_files,
    BOOTSTRAP_MAX_CHARS,
    BOOTSTRAP_TOTAL_MAX_CHARS,
    SAMPLE_SOUL,
)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws_dir = tmp_path / "test-agent"
    return AgentWorkspace(agent_id="test-agent", workspace_dir=ws_dir)


class TestAgentWorkspace:
    """Tests for AgentWorkspace dataclass."""

    def test_creates_directories(self, tmp_path):
        ws_dir = tmp_path / "agent-alpha"
        ws = AgentWorkspace(agent_id="alpha", workspace_dir=ws_dir)
        assert ws_dir.exists()
        assert (ws_dir / "memory").exists()

    def test_default_paths(self, tmp_workspace):
        assert tmp_workspace.soul_path == tmp_workspace.workspace_dir / "SOUL.md"
        assert tmp_workspace.memory_md_path == tmp_workspace.workspace_dir / "MEMORY.md"
        assert tmp_workspace.memory_dir == tmp_workspace.workspace_dir / "memory"

    def test_ensure_soul_creates_file(self, tmp_workspace):
        assert not tmp_workspace.soul_path.exists()
        tmp_workspace.ensure_soul()
        assert tmp_workspace.soul_path.exists()
        content = tmp_workspace.soul_path.read_text(encoding="utf-8")
        assert "SOUL.md" in content
        assert "Core Truths" in content

    def test_ensure_soul_does_not_overwrite(self, tmp_workspace):
        tmp_workspace.soul_path.write_text("custom soul", encoding="utf-8")
        tmp_workspace.ensure_soul()
        assert tmp_workspace.soul_path.read_text(encoding="utf-8") == "custom soul"

    def test_read_soul(self, tmp_workspace):
        tmp_workspace.soul_path.write_text("  I am a test soul  \n", encoding="utf-8")
        assert tmp_workspace.read_soul() == "I am a test soul"

    def test_read_soul_missing(self, tmp_workspace):
        assert tmp_workspace.read_soul() == ""

    def test_has_soul(self, tmp_workspace):
        assert not tmp_workspace.has_soul()
        tmp_workspace.ensure_soul()
        assert tmp_workspace.has_soul()

    def test_has_soul_rejects_symlinks(self, tmp_workspace):
        real_file = tmp_workspace.workspace_dir / "real_soul.md"
        real_file.write_text("soul content", encoding="utf-8")
        tmp_workspace.soul_path.symlink_to(real_file)
        assert not tmp_workspace.has_soul()


class TestTruncateBootstrap:
    """Tests for truncate_bootstrap function."""

    def test_short_content_unchanged(self):
        content = "Hello world"
        assert truncate_bootstrap(content) == content

    def test_long_content_truncated(self):
        content = "x" * 30_000
        result = truncate_bootstrap(content, max_chars=1000)
        assert len(result) < len(content)
        assert "[...truncated...]" in result

    def test_preserves_head_and_tail(self):
        head = "HEAD" * 100
        middle = "MID" * 100
        tail = "TAIL" * 100
        content = head + middle + tail
        result = truncate_bootstrap(content, max_chars=500)
        # Head portion should be preserved
        assert result.startswith("HEAD")
        # Tail portion should be preserved
        assert result.endswith("TAIL" * (100 // 4))  # rough check

    def test_exact_limit_not_truncated(self):
        content = "a" * BOOTSTRAP_MAX_CHARS
        assert truncate_bootstrap(content) == content


class TestLoadBootstrapFiles:
    """Tests for load_bootstrap_files function."""

    def test_loads_soul_and_memory(self, tmp_path):
        ws_dir = tmp_path / "agent"
        ws_dir.mkdir()
        (ws_dir / "SOUL.md").write_text("I am soul", encoding="utf-8")
        (ws_dir / "MEMORY.md").write_text("I remember things", encoding="utf-8")

        files = load_bootstrap_files(ws_dir)
        assert len(files) == 2
        assert files[0]["name"] == "SOUL.md"
        assert files[0]["content"] == "I am soul"
        assert files[1]["name"] == "MEMORY.md"
        assert files[1]["content"] == "I remember things"

    def test_skips_missing_files(self, tmp_path):
        ws_dir = tmp_path / "agent"
        ws_dir.mkdir()
        files = load_bootstrap_files(ws_dir)
        assert files == []

    def test_skips_empty_files(self, tmp_path):
        ws_dir = tmp_path / "agent"
        ws_dir.mkdir()
        (ws_dir / "SOUL.md").write_text("", encoding="utf-8")
        files = load_bootstrap_files(ws_dir)
        assert files == []

    def test_skips_symlinks(self, tmp_path):
        ws_dir = tmp_path / "agent"
        ws_dir.mkdir()
        real = tmp_path / "real_soul.md"
        real.write_text("real content", encoding="utf-8")
        (ws_dir / "SOUL.md").symlink_to(real)
        files = load_bootstrap_files(ws_dir)
        assert files == []

    def test_respects_total_char_limit(self, tmp_path):
        ws_dir = tmp_path / "agent"
        ws_dir.mkdir()
        # Create files that together exceed total limit
        (ws_dir / "SOUL.md").write_text("s" * 20_000, encoding="utf-8")
        (ws_dir / "MEMORY.md").write_text("m" * 20_000, encoding="utf-8")
        files = load_bootstrap_files(ws_dir)
        total = sum(len(f["content"]) for f in files)
        assert total <= BOOTSTRAP_TOTAL_MAX_CHARS
