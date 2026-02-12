"""Tests for safeish_search system prompt flag."""

from pathlib import Path

import pytest

from nanobot.agent.context import ContextBuilder


class TestSafeishSearch:
    """Tests that safeish_search controls web safety system prompt section."""

    def test_web_safety_included_when_enabled(self, tmp_path: Path) -> None:
        builder = ContextBuilder(workspace=tmp_path, safeish_search=True)
        prompt = builder.build_system_prompt()
        assert "## Web Safety" in prompt
        assert "untrusted external data" in prompt

    def test_web_safety_excluded_by_default(self, tmp_path: Path) -> None:
        builder = ContextBuilder(workspace=tmp_path)
        prompt = builder.build_system_prompt()
        assert "## Web Safety" not in prompt

    def test_web_safety_excluded_when_disabled(self, tmp_path: Path) -> None:
        builder = ContextBuilder(workspace=tmp_path, safeish_search=False)
        prompt = builder.build_system_prompt()
        assert "## Web Safety" not in prompt
