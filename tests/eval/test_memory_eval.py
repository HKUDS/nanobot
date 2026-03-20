"""Memory consolidation evaluation tests.

Runs consolidation scenarios and asserts quality metrics.
Uses ScriptedProvider for deterministic, CI-safe execution.
"""

from pathlib import Path

import pytest

from tests.eval.eval_memory_consolidation import (
    ALL_SCENARIOS,
    evaluate_scenario,
    scenario_buried_important_info,
    scenario_consolidation_failure,
    scenario_empty_conversation,
    scenario_multi_turn_tools,
    scenario_scattered_facts,
)


class TestConsolidationQuality:
    """Evaluate whether consolidation preserves key facts."""

    @pytest.mark.asyncio
    async def test_multi_turn_tools_retains_all_facts(self, tmp_path: Path) -> None:
        """Multi-turn conversation with tools should retain all key facts."""
        scenario = scenario_multi_turn_tools()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.success is True
        assert result.retention_rate == 1.0, f"Missed facts: {result.missed_facts}"
        assert result.compression_ratio > 0

    @pytest.mark.asyncio
    async def test_scattered_facts_retains_all_facts(self, tmp_path: Path) -> None:
        """Scattered facts across conversation should all be preserved."""
        scenario = scenario_scattered_facts()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.success is True
        assert result.retention_rate == 1.0, f"Missed facts: {result.missed_facts}"

    @pytest.mark.asyncio
    async def test_buried_info_retains_critical_facts(self, tmp_path: Path) -> None:
        """Critical safety info buried in noise must be preserved."""
        scenario = scenario_buried_important_info()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.success is True
        assert result.retention_rate == 1.0, f"Critical facts missed: {result.missed_facts}"
        # Verify the safety-critical fact specifically
        assert "zeus-prod-01" in result.retained_facts

    @pytest.mark.asyncio
    async def test_consolidation_failure_degrades_gracefully(self, tmp_path: Path) -> None:
        """When LLM doesn't call save_memory, consolidation should return False."""
        scenario = scenario_consolidation_failure()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.success is False
        # No facts retained since nothing was written
        assert result.retention_rate == 0.0

    @pytest.mark.asyncio
    async def test_empty_conversation_succeeds(self, tmp_path: Path) -> None:
        """Empty message list should succeed trivially."""
        scenario = scenario_empty_conversation()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.success is True
        assert result.retention_rate == 1.0  # No facts to retain


class TestConsolidationMetrics:
    """Validate the metrics collection itself."""

    @pytest.mark.asyncio
    async def test_compression_ratio_is_positive(self, tmp_path: Path) -> None:
        """Successful consolidation should have positive compression ratio."""
        scenario = scenario_multi_turn_tools()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.compression_ratio > 0
        assert result.input_chars > 0
        assert result.output_chars > 0

    @pytest.mark.asyncio
    async def test_result_contains_all_fields(self, tmp_path: Path) -> None:
        """ConsolidationResult should have all expected fields populated."""
        scenario = scenario_scattered_facts()
        result = await evaluate_scenario(scenario, tmp_path)

        assert result.scenario_name == "scattered_facts"
        assert isinstance(result.retained_facts, list)
        assert isinstance(result.missed_facts, list)
        assert 0 <= result.retention_rate <= 1.0
        assert result.input_chars > 0


class TestAllScenarios:
    """Run all built-in scenarios and verify they execute without error."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario_fn", ALL_SCENARIOS, ids=lambda fn: fn.__name__)
    async def test_scenario_runs_without_error(self, tmp_path: Path, scenario_fn) -> None:
        """Each scenario should run to completion without raising."""
        scenario = scenario_fn()
        result = await evaluate_scenario(scenario, tmp_path / scenario.name)

        assert result.scenario_name == scenario.name
        assert isinstance(result.success, bool)
        assert isinstance(result.retention_rate, float)


class TestBenchmarkReport:
    """Generate a summary report across all scenarios."""

    @pytest.mark.asyncio
    async def test_benchmark_summary(self, tmp_path: Path) -> None:
        """Run all scenarios and produce a metrics summary."""
        results = []
        for scenario_fn in ALL_SCENARIOS:
            scenario = scenario_fn()
            result = await evaluate_scenario(scenario, tmp_path / scenario.name)
            results.append(result)

        # Verify we ran all scenarios
        assert len(results) == len(ALL_SCENARIOS)

        # Calculate aggregate metrics
        successful = [r for r in results if r.success]

        # At least the successful scenarios should have good retention
        for r in successful:
            if r.retained_facts or r.missed_facts:  # skip empty conversation
                assert r.retention_rate >= 0.5, (
                    f"Scenario {r.scenario_name} has low retention: {r.retention_rate:.0%}"
                )
