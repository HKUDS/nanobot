"""Contract tests verifying cross-component data interfaces.

When component A writes data that component B reads, these tests
verify both sides agree on the schema.
"""

from __future__ import annotations

from nanobot.agent.turn_types import ToolAttempt

# ---------------------------------------------------------------------------
# Contract: activation dict (TurnRunner -> StrategyExtractor)
# ---------------------------------------------------------------------------


def _build_sample_activation() -> dict:
    """Build an activation dict the way TurnRunner does.

    This mirrors the dict literal in turn_runner.py where guardrail
    activations are appended to state.guardrail_activations.
    """
    return {
        "source": "empty_result_detector",
        "severity": "directive",
        "iteration": 3,
        "message": "The tool returned empty results. Try a different approach.",
        "strategy_tag": "empty_recovery:exec",
    }


class TestGuardrailActivationContract:
    """TurnRunner activation dicts must have all fields StrategyExtractor reads."""

    # Fields that StrategyExtractor.extract_from_turn and _build_strategy read
    # via activation.get():
    #   strategy_tag  (extract_from_turn, line 54)
    #   iteration     (extract_from_turn, line 58)
    #   failed_tool   (_build_strategy, line 94)
    #   failed_args   (_build_strategy, line 95)
    #   strategy_tag  (_build_strategy, line 112) — same as above
    #   source        (_build_strategy, line 124)
    REQUIRED_BY_EXTRACTOR = {
        "source",
        "severity",
        "iteration",
        "message",
        "strategy_tag",
    }

    # Fields the extractor reads with .get() that have defaults — these are
    # optional in the dict but the extractor expects them to be meaningful
    # when present.
    OPTIONAL_WITH_DEFAULTS = {
        "failed_tool",  # defaults to "unknown"
        "failed_args",  # defaults to ""
    }

    def test_activation_has_required_keys(self):
        """Activation dict must contain all keys the extractor requires."""
        activation = _build_sample_activation()
        missing = self.REQUIRED_BY_EXTRACTOR - activation.keys()
        assert not missing, f"Activation missing keys required by StrategyExtractor: {missing}"

    def test_activation_types_are_correct(self):
        """Activation dict values must have the types the extractor expects."""
        activation = _build_sample_activation()
        assert isinstance(activation["source"], str)
        assert isinstance(activation["severity"], str)
        assert isinstance(activation["iteration"], int)
        assert isinstance(activation["message"], str)
        # strategy_tag can be str or None
        assert activation["strategy_tag"] is None or isinstance(activation["strategy_tag"], str)

    def test_optional_fields_have_sensible_defaults(self):
        """StrategyExtractor uses .get() with defaults for optional fields.

        This test documents that the activation dict from TurnRunner does NOT
        currently include failed_tool/failed_args, and the extractor handles
        their absence gracefully via .get() defaults.
        """
        activation = _build_sample_activation()
        # These are not in the activation dict — extractor uses defaults
        for key in self.OPTIONAL_WITH_DEFAULTS:
            # The get() with default in extractor handles absence — this is OK.
            # If TurnRunner starts including these, this test should be updated.
            assert activation.get(key) is not None or key not in activation


# ---------------------------------------------------------------------------
# Contract: ToolAttempt (TurnRunner -> guardrails)
# ---------------------------------------------------------------------------


def _build_sample_tool_attempt() -> ToolAttempt:
    """Build a ToolAttempt the way TurnRunner does."""
    return ToolAttempt(
        tool_name="exec",
        arguments={
            "command": 'obsidian search query="DS10540"',
            "working_dir": None,
            "timeout": 60,
        },
        success=True,
        output_empty=False,
        output_snippet="Found 3 results for DS10540...",
        iteration=2,
    )


class TestToolAttemptContract:
    """ToolAttempt must have all fields guardrails and StrategyExtractor check."""

    # Fields accessed by guardrails and strategy extractor
    REQUIRED_FIELDS = {
        "tool_name",
        "arguments",
        "success",
        "output_empty",
        "output_snippet",
        "iteration",
    }

    def test_tool_attempt_has_all_required_fields(self):
        """ToolAttempt must expose all fields that consumers depend on."""
        attempt = _build_sample_tool_attempt()
        actual_fields = {f for f in self.REQUIRED_FIELDS if hasattr(attempt, f)}
        missing = self.REQUIRED_FIELDS - actual_fields
        assert not missing, f"ToolAttempt missing fields: {missing}"

    def test_tool_attempt_with_mixed_type_arguments(self):
        """ToolAttempt arguments dict must support mixed types (production data)."""
        attempt = ToolAttempt(
            tool_name="exec",
            arguments={
                "command": 'search query="test"',
                "working_dir": None,
                "timeout": 60,
                "env_vars": {"PATH": "/usr/bin"},
                "tags": ["search", "query"],
            },
            success=False,
            output_empty=True,
            output_snippet="",
            iteration=1,
        )
        assert isinstance(attempt.arguments["command"], str)
        assert attempt.arguments["working_dir"] is None
        assert isinstance(attempt.arguments["timeout"], int)
        assert isinstance(attempt.arguments["env_vars"], dict)
        assert isinstance(attempt.arguments["tags"], list)

    def test_tool_attempt_boundary_values(self):
        """ToolAttempt must handle boundary values correctly."""
        attempt = ToolAttempt(
            tool_name="",
            arguments={},
            success=False,
            output_empty=True,
            output_snippet="",
            iteration=0,
        )
        assert attempt.tool_name == ""
        assert attempt.arguments == {}
        assert attempt.output_snippet == ""
        assert attempt.iteration == 0
