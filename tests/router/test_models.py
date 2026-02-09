"""Tests for routing models."""

import pytest
from datetime import datetime

from nanobot.agent.router.models import (
    ClassificationScores,
    RoutingDecision,
    RoutingPattern,
    RoutingTier,
)


class TestRoutingTier:
    """Test RoutingTier enum."""
    
    def test_tier_values(self):
        """Test tier enum values."""
        assert RoutingTier.SIMPLE.value == "simple"
        assert RoutingTier.MEDIUM.value == "medium"
        assert RoutingTier.COMPLEX.value == "complex"
        assert RoutingTier.REASONING.value == "reasoning"
    
    def test_tier_from_string(self):
        """Test creating tier from string."""
        assert RoutingTier("simple") == RoutingTier.SIMPLE
        assert RoutingTier("medium") == RoutingTier.MEDIUM
        assert RoutingTier("complex") == RoutingTier.COMPLEX
        assert RoutingTier("reasoning") == RoutingTier.REASONING


class TestClassificationScores:
    """Test ClassificationScores dataclass."""
    
    def test_default_values(self):
        """Test default score values are zero."""
        scores = ClassificationScores()
        assert scores.reasoning_markers == 0.0
        assert scores.code_presence == 0.0
        assert scores.simple_indicators == 0.0
    
    def test_calculate_weighted_sum(self):
        """Test weighted sum calculation."""
        scores = ClassificationScores(
            reasoning_markers=1.0,
            code_presence=0.5,
            simple_indicators=0.0,
        )
        weights = {
            "reasoning_markers": 0.5,
            "code_presence": 0.3,
            "simple_indicators": 0.2,
        }
        result = scores.calculate_weighted_sum(weights)
        expected = (1.0 * 0.5) + (0.5 * 0.3) + (0.0 * 0.2)
        assert result == pytest.approx(expected)
    
    def test_calculate_weighted_sum_missing_field(self):
        """Test weighted sum ignores missing fields."""
        scores = ClassificationScores(reasoning_markers=1.0)
        weights = {
            "reasoning_markers": 0.5,
            "nonexistent_field": 0.5,
        }
        result = scores.calculate_weighted_sum(weights)
        assert result == pytest.approx(0.5)
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        scores = ClassificationScores(reasoning_markers=0.8, code_presence=0.3)
        result = scores.to_dict()
        
        assert isinstance(result, dict)
        assert result["reasoning_markers"] == 0.8
        assert result["code_presence"] == 0.3
        assert "simple_indicators" in result


class TestRoutingDecision:
    """Test RoutingDecision dataclass."""
    
    def test_creation(self):
        """Test creating a routing decision."""
        decision = RoutingDecision(
            tier=RoutingTier.MEDIUM,
            model="gpt-4o-mini",
            confidence=0.85,
            layer="client",
            reasoning="Good match",
            estimated_tokens=200,
            needs_tools=True,
        )
        
        assert decision.tier == RoutingTier.MEDIUM
        assert decision.model == "gpt-4o-mini"
        assert decision.confidence == 0.85
        assert decision.metadata == {}
    
    def test_creation_with_metadata(self):
        """Test creating decision with metadata."""
        decision = RoutingDecision(
            tier=RoutingTier.SIMPLE,
            model="deepseek-chat",
            confidence=0.92,
            layer="client",
            reasoning="Simple query",
            estimated_tokens=50,
            needs_tools=False,
            metadata={"scores": {"simple": 0.9}},
        )
        
        assert decision.metadata["scores"]["simple"] == 0.9


class TestRoutingPattern:
    """Test RoutingPattern dataclass."""
    
    def test_creation(self):
        """Test creating a routing pattern."""
        pattern = RoutingPattern(
            regex=r"\b(prove|theorem)\b",
            tier=RoutingTier.REASONING,
            confidence=0.95,
            examples=["Prove that..."],
            added_at=datetime.now().isoformat(),
        )
        
        assert pattern.tier == RoutingTier.REASONING
        assert pattern.confidence == 0.95
        assert pattern.success_rate == 0.0  # Default
        assert pattern.usage_count == 0  # Default
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        pattern = RoutingPattern(
            regex=r"test",
            tier=RoutingTier.SIMPLE,
            confidence=0.8,
            examples=["example1"],
            added_at="2026-02-09T10:00:00",
            success_rate=0.9,
            usage_count=10,
        )
        
        data = pattern.to_dict()
        assert data["regex"] == r"test"
        assert data["tier"] == "simple"
        assert data["success_rate"] == 0.9
        assert data["usage_count"] == 10
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "regex": r"\b(debug)\b",
            "tier": "complex",
            "confidence": 0.85,
            "examples": ["Debug this"],
            "added_at": "2026-02-09T10:00:00",
            "success_rate": 0.75,
            "usage_count": 20,
        }
        
        pattern = RoutingPattern.from_dict(data)
        assert pattern.tier == RoutingTier.COMPLEX
        assert pattern.confidence == 0.85
        assert pattern.usage_count == 20
    
    def test_from_dict_defaults(self):
        """Test from_dict with missing optional fields."""
        data = {
            "regex": r"test",
            "tier": "simple",
            "confidence": 0.8,
            "examples": [],
            "added_at": "2026-02-09T10:00:00",
        }
        
        pattern = RoutingPattern.from_dict(data)
        assert pattern.success_rate == 0.0  # Default
        assert pattern.usage_count == 0  # Default
