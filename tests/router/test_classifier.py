"""Tests for client-side classifier."""

import pytest
from pathlib import Path
from nanobot.agent.router.classifier import (
    ClientSideClassifier,
    classify_content,
    DEFAULT_WEIGHTS,
)
from nanobot.agent.router.models import RoutingTier, ClassificationScores


class TestClientSideClassifier:
    """Test ClientSideClassifier."""
    
    def test_init_defaults(self):
        """Test initialization with defaults."""
        classifier = ClientSideClassifier()
        assert classifier.min_confidence == 0.85
        assert classifier.weights == DEFAULT_WEIGHTS
        assert len(classifier._patterns) > 0  # Default patterns loaded
    
    def test_init_custom_params(self):
        """Test initialization with custom parameters."""
        classifier = ClientSideClassifier(
            min_confidence=0.9,
            weights={"reasoning_markers": 0.5},
        )
        assert classifier.min_confidence == 0.9
        assert classifier.weights["reasoning_markers"] == 0.5
    
    def test_classify_simple_query(self):
        """Test classification of simple queries."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify("What is 2+2?")
        
        assert decision.tier == RoutingTier.SIMPLE
        assert decision.layer == "client"
        assert decision.confidence >= 0.5
        assert isinstance(scores, ClassificationScores)
    
    def test_classify_complex_query(self):
        """Test classification of complex queries."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify(
            "Debug this distributed system with race conditions"
        )
        
        # Should detect complexity
        assert decision.tier in [RoutingTier.COMPLEX, RoutingTier.MEDIUM]
        assert scores.technical_terms > 0.3
    
    def test_classify_reasoning_query(self):
        """Test classification of reasoning queries."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify(
            "Prove step by step that the sum of angles is 180 degrees"
        )
        
        assert decision.tier == RoutingTier.REASONING
        assert scores.reasoning_markers > 0.5
    
    def test_classify_code_query(self):
        """Test classification of code-related queries."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify(
            "Write a Python function to parse JSON"
        )
        
        assert scores.code_presence > 0.3
        assert decision.needs_tools is True
    
    def test_classify_returns_metadata(self):
        """Test that classification returns metadata."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify("Test message")
        
        assert "scores" in decision.metadata
        assert decision.estimated_tokens > 0
    
    def test_score_patterns(self):
        """Test pattern scoring."""
        classifier = ClientSideClassifier()
        
        content = "what is the meaning of life"
        patterns = ["what is", "meaning", "life"]
        score = classifier._score_patterns(content, patterns)
        
        assert score > 0
        assert score <= 1.0
    
    def test_score_patterns_empty(self):
        """Test pattern scoring with empty patterns."""
        classifier = ClientSideClassifier()
        score = classifier._score_patterns("test", [])
        assert score == 0.0
    
    def test_sigmoid_function(self):
        """Test sigmoid calculation."""
        classifier = ClientSideClassifier()
        
        # Test various inputs
        assert classifier._sigmoid(0) == pytest.approx(0.5, rel=1e-6)
        assert classifier._sigmoid(10) > 0.99
        assert classifier._sigmoid(-10) < 0.01
    
    def test_determine_tier_thresholds(self):
        """Test tier determination based on thresholds."""
        classifier = ClientSideClassifier()
        
        # Test each tier
        assert classifier._determine_tier(0.98, "test") == RoutingTier.REASONING
        assert classifier._determine_tier(0.90, "test") == RoutingTier.COMPLEX
        assert classifier._determine_tier(0.70, "test") == RoutingTier.MEDIUM
        assert classifier._determine_tier(0.30, "test") == RoutingTier.SIMPLE
    
    def test_determine_tier_reasoning_override(self):
        """Test reasoning override with markers."""
        classifier = ClientSideClassifier()
        
        content = "Prove step by step this theorem"
        tier = classifier._determine_tier(0.96, content)
        assert tier == RoutingTier.REASONING
    
    def test_estimate_tokens(self):
        """Test token estimation."""
        classifier = ClientSideClassifier()
        
        simple_tokens = classifier._estimate_tokens("Hi", RoutingTier.SIMPLE)
        complex_tokens = classifier._estimate_tokens("Hi", RoutingTier.COMPLEX)
        
        assert simple_tokens < complex_tokens
        assert simple_tokens >= 50  # Base for SIMPLE
        assert complex_tokens >= 1000  # Base for COMPLEX
    
    def test_needs_tools(self):
        """Test tool requirement detection."""
        classifier = ClientSideClassifier()
        
        # Should need tools
        assert classifier._needs_tools("Search the web for Python docs", RoutingTier.MEDIUM) is True
        assert classifier._needs_tools("Execute this command", RoutingTier.SIMPLE) is True
        
        # Should not need tools
        assert classifier._needs_tools("Hello", RoutingTier.SIMPLE) is False
    
    def test_calculate_scores_reasoning_markers(self):
        """Test reasoning markers score calculation."""
        classifier = ClientSideClassifier()
        
        scores = classifier._calculate_scores("Prove this theorem step by step")
        assert scores.reasoning_markers > 0.5
    
    def test_calculate_scores_code_presence(self):
        """Test code presence score calculation."""
        classifier = ClientSideClassifier()
        
        scores = classifier._calculate_scores("def function(): pass")
        assert scores.code_presence > 0.3
        
        # Code blocks boost score
        scores_with_block = classifier._calculate_scores("```python\ndef test():\n    pass\n```")
        assert scores_with_block.code_presence > scores.code_presence
    
    def test_calculate_scores_token_count(self):
        """Test token count score calculation."""
        classifier = ClientSideClassifier()
        
        short = classifier._calculate_scores("Hi")
        long = classifier._calculate_scores(" ".join(["word"] * 1000))
        
        assert short.token_count < long.token_count
        assert long.token_count == 1.0  # Max for long content


class TestClassifyContentFunction:
    """Test classify_content convenience function."""
    
    def test_classify_content_basic(self):
        """Test basic classification."""
        decision, scores = classify_content("What is Python?")
        
        assert isinstance(decision.tier, RoutingTier)
        assert 0 <= decision.confidence <= 1
        assert isinstance(scores, ClassificationScores)
    
    def test_classify_content_custom_confidence(self):
        """Test classification with custom confidence threshold."""
        decision, scores = classify_content(
            "Complex debugging task",
            min_confidence=0.95
        )
        
        # With higher threshold, should still work
        assert isinstance(decision.tier, RoutingTier)


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_message(self):
        """Test classification of empty message."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify("")
        
        assert isinstance(decision.tier, RoutingTier)
        assert decision.confidence >= 0
    
    def test_very_long_message(self):
        """Test classification of very long message."""
        classifier = ClientSideClassifier()
        long_message = "word " * 10000
        decision, scores = classifier.classify(long_message)
        
        assert isinstance(decision.tier, RoutingTier)
        assert scores.token_count == 1.0  # Should be maxed out
    
    def test_unicode_content(self):
        """Test classification with unicode content."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify("Hello 世界 🌍")
        
        assert isinstance(decision.tier, RoutingTier)
    
    def test_special_characters(self):
        """Test classification with special characters."""
        classifier = ClientSideClassifier()
        decision, scores = classifier.classify("Test @#$%^&*() <script>alert('xss')</script>")
        
        assert isinstance(decision.tier, RoutingTier)
        assert decision.confidence >= 0
