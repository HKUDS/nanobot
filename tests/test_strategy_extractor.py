"""Tests for StrategyExtractor — procedural memory from guardrail recoveries."""

from __future__ import annotations

import sqlite3

import pytest

from nanobot.agent.turn_types import ToolAttempt
from nanobot.memory.strategy import StrategyAccess
from nanobot.memory.strategy_extractor import StrategyExtractor


def _create_schema(conn: sqlite3.Connection) -> None:
    """Create the strategies table (normally owned by UnifiedMemoryDB)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS strategies (
            id            TEXT PRIMARY KEY,
            domain        TEXT NOT NULL,
            task_type     TEXT NOT NULL,
            strategy      TEXT NOT NULL,
            context       TEXT NOT NULL,
            source        TEXT NOT NULL DEFAULT 'guardrail_recovery',
            confidence    REAL NOT NULL DEFAULT 0.5,
            created_at    TEXT NOT NULL,
            last_used     TEXT NOT NULL,
            use_count     INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_strategies_domain ON strategies(domain);
        CREATE INDEX IF NOT EXISTS idx_strategies_task_type ON strategies(task_type);
    """)


@pytest.fixture()
def strategy_store() -> StrategyAccess:
    conn = sqlite3.connect(":memory:")
    _create_schema(conn)
    return StrategyAccess(conn)


@pytest.fixture()
def extractor(strategy_store: StrategyAccess) -> StrategyExtractor:
    """Extractor without LLM provider (fallback text generation)."""
    return StrategyExtractor(store=strategy_store)


def _make_attempt(
    tool_name: str,
    *,
    success: bool = True,
    output_empty: bool = False,
    iteration: int = 1,
) -> ToolAttempt:
    return ToolAttempt(
        tool_name=tool_name,
        arguments={"path": "/test"},
        success=success,
        output_empty=output_empty,
        output_snippet="some output",
        iteration=iteration,
    )


@pytest.mark.asyncio
async def test_extracts_from_successful_recovery(
    extractor: StrategyExtractor, strategy_store: StrategyAccess
) -> None:
    """When a guardrail fires with strategy_tag and a subsequent tool succeeds,
    a strategy is extracted and saved."""
    tool_log = [
        _make_attempt("obsidian_search", success=True, output_empty=True, iteration=1),
        _make_attempt("read_file", success=True, output_empty=False, iteration=3),
    ]
    guardrail_activations = [
        {
            "source": "empty_result_recovery",
            "severity": "directive",
            "iteration": 2,
            "message": "Try a different tool.",
            "strategy_tag": "empty_recovery:obsidian_search",
        }
    ]

    strategies = await extractor.extract_from_turn(
        tool_results_log=tool_log,
        guardrail_activations=guardrail_activations,
        user_text="Find my meeting notes",
    )

    assert len(strategies) == 1
    assert strategies[0].task_type == "empty_recovery:obsidian_search"
    assert strategies[0].confidence == 0.5
    assert strategies[0].source == "guardrail_recovery"

    # Verify it was persisted
    stored = strategy_store.retrieve(limit=10)
    assert len(stored) == 1
    assert stored[0].id == strategies[0].id


@pytest.mark.asyncio
async def test_no_extraction_when_no_strategy_tag(
    extractor: StrategyExtractor, strategy_store: StrategyAccess
) -> None:
    """Guardrail activations without strategy_tag are skipped."""
    tool_log = [
        _make_attempt("read_file", success=True, output_empty=False, iteration=2),
    ]
    guardrail_activations = [
        {
            "source": "failure_escalation",
            "severity": "override",
            "iteration": 1,
            "message": "Too many failures.",
            # No strategy_tag
        }
    ]

    strategies = await extractor.extract_from_turn(
        tool_results_log=tool_log,
        guardrail_activations=guardrail_activations,
        user_text="Do something",
    )

    assert len(strategies) == 0
    assert len(strategy_store.retrieve(limit=10)) == 0


@pytest.mark.asyncio
async def test_no_extraction_when_recovery_failed(
    extractor: StrategyExtractor, strategy_store: StrategyAccess
) -> None:
    """When subsequent tool calls all fail or return empty, no strategy is saved."""
    tool_log = [
        _make_attempt("obsidian_search", success=True, output_empty=True, iteration=1),
        _make_attempt("read_file", success=False, output_empty=False, iteration=3),
    ]
    guardrail_activations = [
        {
            "source": "empty_result_recovery",
            "severity": "directive",
            "iteration": 2,
            "message": "Try a different tool.",
            "strategy_tag": "empty_recovery:obsidian_search",
        }
    ]

    strategies = await extractor.extract_from_turn(
        tool_results_log=tool_log,
        guardrail_activations=guardrail_activations,
        user_text="Find my notes",
    )

    assert len(strategies) == 0


@pytest.mark.asyncio
async def test_confidence_update_on_success(
    extractor: StrategyExtractor, strategy_store: StrategyAccess
) -> None:
    """When strategies were in context and no guardrails fired, confidence increases."""
    # Save a strategy first
    tool_log = [
        _make_attempt("read_file", success=True, output_empty=False, iteration=3),
    ]
    guardrail_activations = [
        {
            "source": "empty_result_recovery",
            "severity": "directive",
            "iteration": 2,
            "message": "Try different tool.",
            "strategy_tag": "empty_recovery:test",
        }
    ]
    strategies = await extractor.extract_from_turn(
        tool_results_log=tool_log,
        guardrail_activations=guardrail_activations,
        user_text="test",
    )
    assert len(strategies) == 1
    assert strategies[0].confidence == 0.5

    # Update confidence (no guardrail activations = success)
    extractor.update_confidence(strategies, had_guardrail_activations=False)

    updated = strategy_store.retrieve(limit=1)
    assert len(updated) == 1
    assert updated[0].confidence == pytest.approx(0.6)
    assert updated[0].use_count == 1
    assert updated[0].success_count == 1


@pytest.mark.asyncio
async def test_confidence_update_on_failure(
    extractor: StrategyExtractor, strategy_store: StrategyAccess
) -> None:
    """When strategies were in context and guardrails fired, confidence decreases."""
    tool_log = [
        _make_attempt("read_file", success=True, output_empty=False, iteration=3),
    ]
    guardrail_activations = [
        {
            "source": "empty_result_recovery",
            "severity": "directive",
            "iteration": 2,
            "message": "Try different tool.",
            "strategy_tag": "empty_recovery:test",
        }
    ]
    strategies = await extractor.extract_from_turn(
        tool_results_log=tool_log,
        guardrail_activations=guardrail_activations,
        user_text="test",
    )
    assert len(strategies) == 1

    extractor.update_confidence(strategies, had_guardrail_activations=True)

    updated = strategy_store.retrieve(limit=1, min_confidence=0.0)
    assert len(updated) == 1
    assert updated[0].confidence == pytest.approx(0.45)
    assert updated[0].use_count == 1
    assert updated[0].success_count == 0
