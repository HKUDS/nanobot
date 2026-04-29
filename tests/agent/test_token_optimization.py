"""Tests for token optimization features."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import AgentDefaults, TokenOptimizationConfig
from nanobot.session.manager import Session


def _mk_loop(token_optimization=None) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop.max_tool_result_chars = AgentDefaults().max_tool_result_chars
    loop._token_optimization = token_optimization
    return loop


def _make_session() -> Session:
    return Session(key="test:token-opt")


# ── hide_successful_tool_results ─────────────────────────────────────────


class TestHideSuccessfulToolResults:
    def test_hides_ok_result(self) -> None:
        topt = TokenOptimizationConfig(hide_successful_tool_results=True)
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        loop._save_turn(session, [
            {"role": "tool", "content": '{"result":"ok"}'},
        ], skip=0)

        assert len(session.messages) == 1
        assert session.messages[0]["content"] == "✓"

    def test_hides_ok_with_spaces(self) -> None:
        topt = TokenOptimizationConfig(hide_successful_tool_results=True)
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        loop._save_turn(session, [
            {"role": "tool", "content": '{"result": "ok"}'},
        ], skip=0)

        assert session.messages[0]["content"] == "✓"

    def test_does_not_hide_error(self) -> None:
        topt = TokenOptimizationConfig(hide_successful_tool_results=True)
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        loop._save_turn(session, [
            {"role": "tool", "content": '{"error":"disk full"}'},
        ], skip=0)

        assert session.messages[0]["content"] == '{"error":"disk full"}'

    def test_disabled_by_default(self) -> None:
        topt = TokenOptimizationConfig()
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        loop._save_turn(session, [
            {"role": "tool", "content": '{"result":"ok"}'},
        ], skip=0)

        assert session.messages[0]["content"] == '{"result":"ok"}'


# ── truncate_tool_results ────────────────────────────────────────────────


class TestTruncateToolResults:
    def test_truncates_long_result(self) -> None:
        topt = TokenOptimizationConfig(truncate_tool_results=100)
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        long_content = "x" * 500
        loop._save_turn(session, [
            {"role": "tool", "content": long_content},
        ], skip=0)

        saved = session.messages[0]["content"]
        assert len(saved) <= 120  # truncate_text adds "...(truncated)" suffix

    def test_does_not_truncate_short_result(self) -> None:
        topt = TokenOptimizationConfig(truncate_tool_results=100)
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        loop._save_turn(session, [
            {"role": "tool", "content": "short"},
        ], skip=0)

        assert session.messages[0]["content"] == "short"

    def test_zero_means_disabled(self) -> None:
        topt = TokenOptimizationConfig(truncate_tool_results=0)
        loop = _mk_loop(token_optimization=topt)
        session = _make_session()

        long_content = "x" * 500
        loop._save_turn(session, [
            {"role": "tool", "content": long_content},
        ], skip=0)

        # Should still be truncated by max_tool_result_chars (16000) if at all
        assert len(session.messages[0]["content"]) == 500


# ── output_style in context ──────────────────────────────────────────────


class TestOutputStyleInContext:
    def test_terse_adds_instruction(self, tmp_path: Path) -> None:
        topt = TokenOptimizationConfig(output_style="terse")
        ctx = ContextBuilder(tmp_path, token_optimization=topt)
        prompt = ctx.build_system_prompt(skill_names=None)
        assert "Terse" in prompt
        assert "maximally concise" in prompt

    def test_verbose_adds_instruction(self, tmp_path: Path) -> None:
        topt = TokenOptimizationConfig(output_style="verbose")
        ctx = ContextBuilder(tmp_path, token_optimization=topt)
        prompt = ctx.build_system_prompt(skill_names=None)
        assert "Verbose" in prompt

    def test_normal_adds_nothing(self, tmp_path: Path) -> None:
        topt = TokenOptimizationConfig(output_style="normal")
        ctx = ContextBuilder(tmp_path, token_optimization=topt)
        prompt = ctx.build_system_prompt(skill_names=None)
        assert "Terse" not in prompt
        assert "Verbose" not in prompt

    def test_none_adds_nothing(self, tmp_path: Path) -> None:
        ctx = ContextBuilder(tmp_path, token_optimization=None)
        prompt = ctx.build_system_prompt(skill_names=None)
        assert "Terse" not in prompt


# ── config defaults ──────────────────────────────────────────────────────


class TestConfigDefaults:
    def test_defaults(self) -> None:
        cfg = TokenOptimizationConfig()
        assert cfg.output_style == "normal"
        assert cfg.truncate_tool_results == 0
        assert cfg.compact_after_messages == 0
        assert cfg.hide_successful_tool_results is False

    def test_in_agent_defaults(self) -> None:
        defaults = AgentDefaults()
        assert defaults.token_optimization.output_style == "normal"

    def test_custom_config(self) -> None:
        cfg = TokenOptimizationConfig(
            output_style="terse",
            truncate_tool_results=500,
            compact_after_messages=20,
            hide_successful_tool_results=True,
        )
        assert cfg.output_style == "terse"
        assert cfg.truncate_tool_results == 500
        assert cfg.compact_after_messages == 20
        assert cfg.hide_successful_tool_results is True
