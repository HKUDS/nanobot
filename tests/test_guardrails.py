"""Tests for the guardrail layer (turn_guardrails.py)."""

from __future__ import annotations

import pytest

from nanobot.agent.turn_types import ToolAttempt


def _attempt(
    tool: str = "exec",
    args: dict | None = None,
    success: bool = True,
    empty: bool = False,
    snippet: str = "data",
    iteration: int = 1,
) -> ToolAttempt:
    return ToolAttempt(
        tool_name=tool,
        arguments=args or {},
        success=success,
        output_empty=empty,
        output_snippet=snippet,
        iteration=iteration,
    )


# ---------------------------------------------------------------------------
# Intervention
# ---------------------------------------------------------------------------


class TestIntervention:
    def test_creation(self) -> None:
        from nanobot.agent.turn_guardrails import Intervention

        iv = Intervention(source="test", message="hello", severity="hint", strategy_tag="tag1")
        assert iv.source == "test"
        assert iv.message == "hello"
        assert iv.severity == "hint"
        assert iv.strategy_tag == "tag1"

    def test_frozen(self) -> None:
        from nanobot.agent.turn_guardrails import Intervention

        iv = Intervention(source="test", message="hello", severity="hint")
        with pytest.raises(AttributeError):
            iv.source = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GuardrailChain
# ---------------------------------------------------------------------------


class TestGuardrailChain:
    def test_returns_none_when_empty(self) -> None:
        from nanobot.agent.turn_guardrails import GuardrailChain

        chain = GuardrailChain([])
        assert chain.check([], []) is None

    def test_first_intervention_wins(self) -> None:
        from nanobot.agent.turn_guardrails import (
            GuardrailChain,
            Intervention,
        )

        class AlwaysFires:
            name = "always"

            def check(self, all_attempts, latest_results, *, iteration=0) -> Intervention:
                return Intervention(source=self.name, message="fired", severity="hint")

        class NeverReached:
            name = "never"

            def check(self, all_attempts, latest_results, *, iteration=0) -> Intervention:
                return Intervention(source=self.name, message="should not appear", severity="hint")

        chain = GuardrailChain([AlwaysFires(), NeverReached()])
        result = chain.check([], [])
        assert result is not None
        assert result.source == "always"

    def test_skips_non_firing(self) -> None:
        from nanobot.agent.turn_guardrails import (
            GuardrailChain,
            Intervention,
        )

        class NoFire:
            name = "nope"

            def check(self, all_attempts, latest_results, *, iteration=0) -> None:
                return None

        class Fires:
            name = "yes"

            def check(self, all_attempts, latest_results, *, iteration=0) -> Intervention:
                return Intervention(source=self.name, message="got it", severity="directive")

        chain = GuardrailChain([NoFire(), Fires()])
        result = chain.check([], [])
        assert result is not None
        assert result.source == "yes"


# ---------------------------------------------------------------------------
# EmptyResultRecovery
# ---------------------------------------------------------------------------


class TestEmptyResultRecovery:
    def test_no_fire_on_success_with_data(self) -> None:
        from nanobot.agent.turn_guardrails import EmptyResultRecovery

        g = EmptyResultRecovery()
        latest = [_attempt(success=True, empty=False)]
        assert g.check(latest, latest) is None

    def test_no_fire_on_failure(self) -> None:
        from nanobot.agent.turn_guardrails import EmptyResultRecovery

        g = EmptyResultRecovery()
        latest = [_attempt(success=False, empty=True)]
        assert g.check(latest, latest) is None

    def test_hint_on_first_empty(self) -> None:
        from nanobot.agent.turn_guardrails import EmptyResultRecovery

        g = EmptyResultRecovery()
        latest = [_attempt(tool="exec", success=True, empty=True)]
        result = g.check(latest, latest)
        assert result is not None
        assert result.severity == "hint"

    def test_directive_on_second_empty_same_tool(self) -> None:
        from nanobot.agent.turn_guardrails import EmptyResultRecovery

        g = EmptyResultRecovery()
        first = _attempt(tool="exec", success=True, empty=True, iteration=1)
        second = _attempt(tool="exec", success=True, empty=True, iteration=2)
        all_attempts = [first, second]
        result = g.check(all_attempts, [second])
        assert result is not None
        assert result.severity == "directive"

    def test_strategy_tag_present(self) -> None:
        from nanobot.agent.turn_guardrails import EmptyResultRecovery

        g = EmptyResultRecovery()
        latest = [_attempt(tool="exec", success=True, empty=True)]
        result = g.check(latest, latest)
        assert result is not None
        assert result.strategy_tag is not None


# ---------------------------------------------------------------------------
# RepeatedStrategyDetection
# ---------------------------------------------------------------------------


class TestRepeatedStrategyDetection:
    def test_no_fire_on_first(self) -> None:
        from nanobot.agent.turn_guardrails import RepeatedStrategyDetection

        g = RepeatedStrategyDetection()
        a = _attempt(tool="exec", args={"cmd": "ls"})
        assert g.check([a], [a]) is None

    def test_no_fire_different_args(self) -> None:
        from nanobot.agent.turn_guardrails import RepeatedStrategyDetection

        g = RepeatedStrategyDetection()
        attempts = [
            _attempt(tool="exec", args={"cmd": "ls"}),
            _attempt(tool="exec", args={"cmd": "cat foo"}),
            _attempt(tool="exec", args={"cmd": "pwd"}),
        ]
        assert g.check(attempts, [attempts[-1]]) is None

    def test_fires_on_third_similar(self) -> None:
        from nanobot.agent.turn_guardrails import RepeatedStrategyDetection

        g = RepeatedStrategyDetection()
        attempts = [
            _attempt(tool="exec", args={"cmd": "ls"}),
            _attempt(tool="exec", args={"cmd": "ls"}),
            _attempt(tool="exec", args={"cmd": "ls"}),
        ]
        result = g.check(attempts, [attempts[-1]])
        assert result is not None
        assert result.severity == "override"
        assert result.strategy_tag == "repeated_strategy"

    def test_mixed_type_args_no_crash(self) -> None:
        """Real tool arguments have mixed types (str, int, None, list, dict)."""
        from nanobot.agent.turn_guardrails import RepeatedStrategyDetection

        g = RepeatedStrategyDetection()
        real_args = {
            "command": 'obsidian search query="DS10540"',
            "working_dir": None,
            "timeout": 60,
        }
        attempts = [
            _attempt(tool="exec", args=real_args),
            _attempt(tool="exec", args=real_args),
            _attempt(tool="exec", args=real_args),
        ]
        result = g.check(attempts, [attempts[-1]])
        assert result is not None
        assert result.severity == "override"

    def test_nested_dict_args_no_crash(self) -> None:
        """Tool arguments may contain nested dicts and lists."""
        from nanobot.agent.turn_guardrails import RepeatedStrategyDetection

        g = RepeatedStrategyDetection()
        nested_args = {
            "options": {"recursive": True, "depth": 3},
            "tags": ["urgent", "bug"],
            "path": "/foo",
        }
        attempts = [
            _attempt(tool="exec", args=nested_args),
            _attempt(tool="exec", args=nested_args),
            _attempt(tool="exec", args=nested_args),
        ]
        result = g.check(attempts, [attempts[-1]])
        assert result is not None

    def test_empty_args(self) -> None:
        from nanobot.agent.turn_guardrails import RepeatedStrategyDetection

        g = RepeatedStrategyDetection()
        attempts = [
            _attempt(tool="list_dir", args={}),
            _attempt(tool="list_dir", args={}),
            _attempt(tool="list_dir", args={}),
        ]
        result = g.check(attempts, [attempts[-1]])
        assert result is not None


# ---------------------------------------------------------------------------
# _canonical_args
# ---------------------------------------------------------------------------


class TestCanonicalArgs:
    def test_deterministic_key_order(self) -> None:
        from nanobot.agent.turn_guardrails import _canonical_args

        a = {"z": 1, "a": 2}
        b = {"a": 2, "z": 1}
        assert _canonical_args(a) == _canonical_args(b)

    def test_mixed_types(self) -> None:
        from nanobot.agent.turn_guardrails import _canonical_args

        args = {"command": "obsidian search", "working_dir": None, "timeout": 60}
        result = _canonical_args(args)
        assert isinstance(result, str)
        assert "null" in result  # None -> null in JSON

    def test_nested_structures(self) -> None:
        from nanobot.agent.turn_guardrails import _canonical_args

        args = {"options": {"recursive": True}, "tags": ["a", "b"]}
        result = _canonical_args(args)
        assert "recursive" in result
        assert '["a", "b"]' in result

    def test_empty_dict(self) -> None:
        from nanobot.agent.turn_guardrails import _canonical_args

        assert _canonical_args({}) == "{}"


# ---------------------------------------------------------------------------
# SkillTunnelVision
# ---------------------------------------------------------------------------


class TestSkillTunnelVision:
    def test_no_fire_before_iteration_3(self) -> None:
        from nanobot.agent.turn_guardrails import SkillTunnelVision

        g = SkillTunnelVision()
        attempts = [_attempt(tool="exec", empty=True)] * 6
        assert g.check(attempts, [attempts[-1]], iteration=2) is None

    def test_fires_all_exec_no_data(self) -> None:
        from nanobot.agent.turn_guardrails import SkillTunnelVision

        g = SkillTunnelVision()
        attempts = [_attempt(tool="exec", empty=True) for _ in range(6)]
        result = g.check(attempts, [attempts[-1]], iteration=3)
        assert result is not None
        assert result.severity == "directive"
        assert result.strategy_tag == "skill_tunnel_vision"

    def test_no_fire_when_data_returned(self) -> None:
        from nanobot.agent.turn_guardrails import SkillTunnelVision

        g = SkillTunnelVision()
        attempts = [_attempt(tool="exec", empty=True) for _ in range(5)]
        attempts.append(_attempt(tool="exec", empty=False))
        assert g.check(attempts, [attempts[-1]], iteration=3) is None

    def test_no_fire_mixed_tools(self) -> None:
        from nanobot.agent.turn_guardrails import SkillTunnelVision

        g = SkillTunnelVision()
        attempts = [_attempt(tool="exec", empty=True) for _ in range(5)]
        attempts.append(_attempt(tool="read_file", empty=True))
        assert g.check(attempts, [attempts[-1]], iteration=3) is None


# ---------------------------------------------------------------------------
# NoProgressBudget
# ---------------------------------------------------------------------------


class TestNoProgressBudget:
    def test_no_fire_before_4(self) -> None:
        from nanobot.agent.turn_guardrails import NoProgressBudget

        g = NoProgressBudget()
        attempts = [_attempt(success=True, empty=True)] * 4
        assert g.check(attempts, [attempts[-1]], iteration=3) is None

    def test_fires_no_useful_data(self) -> None:
        from nanobot.agent.turn_guardrails import NoProgressBudget

        g = NoProgressBudget()
        attempts = [_attempt(success=True, empty=True)] * 5
        result = g.check(attempts, [attempts[-1]], iteration=4)
        assert result is not None
        assert result.severity == "override"
        assert result.strategy_tag == "no_progress_budget"

    def test_no_fire_some_data(self) -> None:
        from nanobot.agent.turn_guardrails import NoProgressBudget

        g = NoProgressBudget()
        attempts = [_attempt(success=True, empty=True)] * 4
        attempts.append(_attempt(success=True, empty=False))
        assert g.check(attempts, [attempts[-1]], iteration=4) is None
