"""Deterministic, zero-LLM token optimization diagnostics."""

from __future__ import annotations

from typing import Any, cast

from nanobot.config.schema import EvolutionConfig


class TokenWasteDetector:
    """Estimate conservative optimization opportunities from usage telemetry.

    The detector is observation-only. It never edits prompts, memory, routing,
    configuration, or stored source records.
    """

    def __init__(self, config: EvolutionConfig) -> None:
        self.config = config

    @staticmethod
    def _usage_int(row: dict[str, Any], key: str) -> int:
        usage_value = row.get("usage")
        if not isinstance(usage_value, dict):
            return 0
        usage = cast(dict[str, object], usage_value)
        value = usage.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, int | float]:
        input_tokens = sum(self._usage_int(row, "input_tokens") for row in rows)
        output_tokens = sum(self._usage_int(row, "output_tokens") for row in rows)
        observed_tokens = sum(self._usage_int(row, "total_tokens") for row in rows)
        cache_read_tokens = sum(self._usage_int(row, "cache_read_tokens") for row in rows)
        runtime_context_chars = sum(
            value
            for row in rows
            if isinstance((value := row.get("runtime_context_chars", 0)), int)
            and not isinstance(value, bool)
            and value >= 0
        )

        round_overage_turns = 0
        output_overage_turns = 0
        estimated_avoidable_tokens = 0
        for row in rows:
            rounds = row.get("model_rounds", 0)
            if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 0:
                rounds = self._usage_int(row, "request_count")
            row_input = self._usage_int(row, "input_tokens")
            if rounds > self.config.target_model_rounds:
                round_overage_turns += 1
                # Average input per provider request is a deliberately
                # conservative proxy for removable rounds.
                estimated_avoidable_tokens += (
                    row_input * (rounds - self.config.target_model_rounds) // rounds
                )

            row_output = self._usage_int(row, "output_tokens")
            if row_output > self.config.target_output_tokens:
                output_overage_turns += 1
                estimated_avoidable_tokens += row_output - self.config.target_output_tokens

        estimated_avoidable_tokens = min(estimated_avoidable_tokens, observed_tokens)
        saving_pct = (
            (estimated_avoidable_tokens / observed_tokens) * 100 if observed_tokens else 0.0
        )
        return {
            "observations": len(rows),
            "observed_tokens": observed_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read_tokens,
            "runtime_context_chars": runtime_context_chars,
            "estimated_avoidable_tokens": estimated_avoidable_tokens,
            "estimated_saving_pct": saving_pct,
            "round_overage_turns": round_overage_turns,
            "output_overage_turns": output_overage_turns,
        }
