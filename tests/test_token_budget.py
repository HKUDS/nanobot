"""Tests for TokenBudgetAllocator and SectionBudget."""

from __future__ import annotations

import pytest

from nanobot.memory.token_budget import (
    DEFAULT_SECTION_WEIGHTS,
    SectionBudget,
    TokenBudgetAllocator,
)


class TestTokenBudgetAllocator:
    def test_allocate_returns_section_budget_instance(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result = allocator.allocate(900, "fact_lookup")
        assert isinstance(result, SectionBudget)

    def test_allocate_total_does_not_exceed_budget(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result = allocator.allocate(900, "fact_lookup")
        total = (
            result.long_term
            + result.profile
            + result.semantic
            + result.episodic
            + result.reflection
            + result.graph
            + result.unresolved
        )
        assert total <= 900

    def test_allocate_all_sections_non_negative(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        for intent in DEFAULT_SECTION_WEIGHTS:
            result = allocator.allocate(500, intent)
            for field in (
                "long_term",
                "profile",
                "semantic",
                "episodic",
                "reflection",
                "graph",
                "unresolved",
            ):
                assert getattr(result, field) >= 0, f"{field} negative for intent={intent}"

    def test_unknown_intent_falls_back_to_fact_lookup(self):
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result_unknown = allocator.allocate(900, "nonexistent_intent")
        result_fact = allocator.allocate(900, "fact_lookup")
        assert result_unknown == result_fact

    def test_config_override_replaces_intent_weights(self):
        custom_weights = {
            **DEFAULT_SECTION_WEIGHTS,
            "fact_lookup": {
                "long_term": 1.0,
                "profile": 0.0,
                "semantic": 0.0,
                "episodic": 0.0,
                "reflection": 0.0,
                "graph": 0.0,
                "unresolved": 0.0,
            },
        }
        allocator = TokenBudgetAllocator(custom_weights)
        result = allocator.allocate(900, "fact_lookup")
        assert result.long_term > 0
        assert result.profile == 0

    def test_section_budget_is_frozen_dataclass(self):
        budget = SectionBudget(
            long_term=100,
            profile=50,
            semantic=80,
            episodic=20,
            reflection=0,
            graph=60,
            unresolved=10,
        )
        with pytest.raises((AttributeError, TypeError)):
            budget.long_term = 999  # type: ignore[misc]

    def test_allocate_proportional_higher_weight_gets_more_tokens(self):
        # fact_lookup: long_term=0.28 > profile=0.23
        allocator = TokenBudgetAllocator(DEFAULT_SECTION_WEIGHTS)
        result = allocator.allocate(1000, "fact_lookup")
        assert result.long_term >= result.profile
