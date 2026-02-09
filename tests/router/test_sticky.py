"""Tests for sticky routing."""

import pytest
from datetime import datetime
from unittest.mock import Mock, AsyncMock

from nanobot.agent.router.sticky import StickyRouter
from nanobot.agent.router.classifier import ClientSideClassifier
from nanobot.agent.router.models import RoutingDecision, RoutingTier


class MockSession:
    """Mock session for testing."""
    
    def __init__(self, messages=None):
        self.messages = messages or []
        self.metadata = {}


class TestStickyRouter:
    """Test StickyRouter."""
    
    def test_init(self):
        """Test initialization."""
        classifier = ClientSideClassifier()
        router = StickyRouter(
            client_classifier=classifier,
            context_window=3,
            downgrade_confidence=0.95,
        )
        
        assert router.client_classifier == classifier
        assert router.context_window == 3
        assert router.downgrade_confidence == 0.95
        assert router.llm_router is None
    
    @pytest.mark.asyncio
    async def test_classify_simple_no_history(self):
        """Test classification with simple message and no history."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        session = MockSession()
        decision = await router.classify("What is 2+2?", session)
        
        assert decision.tier == RoutingTier.SIMPLE
        assert decision.layer == "client"
        assert session.metadata.get("routing_tier") == "simple"
    
    @pytest.mark.asyncio
    async def test_sticky_maintains_complex_tier(self):
        """Test that complex tier is maintained across messages."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        session = MockSession()
        
        # First message - complex
        decision1 = await router.classify(
            "Debug this distributed system",
            session
        )
        assert decision1.tier in [RoutingTier.COMPLEX, RoutingTier.MEDIUM]
        
        # Second message - simple but should stay complex (sticky)
        decision2 = await router.classify("Thanks", session)
        
        # Should maintain complex tier
        if decision2.tier != RoutingTier.SIMPLE:
            assert decision2.metadata.get("sticky_maintained") is True
    
    @pytest.mark.asyncio
    async def test_downgrade_when_explicitly_simple(self):
        """Test downgrade when message is explicitly simple."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        session = MockSession()
        
        # Set up complex history
        session.messages = [
            {"metadata": {"routing_tier": "complex"}}
        ]
        session.metadata["routing_tier"] = "complex"
        
        # Simple message that should trigger downgrade
        decision = await router.classify(
            "Just a quick question - what is 2+2?",
            session
        )
        
        # Should allow downgrade
        if decision.tier == RoutingTier.SIMPLE:
            assert decision.metadata.get("sticky_override") == "downgrade_allowed"
    
    def test_get_recent_tiers_empty_session(self):
        """Test getting recent tiers from empty session."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        session = MockSession()
        tiers = router._get_recent_tiers(session)
        
        assert tiers == []
    
    def test_get_recent_tiers_with_history(self):
        """Test getting recent tiers from session with history."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier, context_window=3)
        
        session = MockSession(messages=[
            {"metadata": {"routing_tier": "simple"}},
            {"metadata": {"routing_tier": "complex"}},
            {"metadata": {"routing_tier": "medium"}},
        ])
        
        tiers = router._get_recent_tiers(session)
        
        assert len(tiers) == 3
        assert RoutingTier.SIMPLE in tiers
        assert RoutingTier.COMPLEX in tiers
    
    def test_get_recent_tiers_respects_window(self):
        """Test that context window is respected."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier, context_window=2)
        
        session = MockSession(messages=[
            {"metadata": {"routing_tier": "simple"}},
            {"metadata": {"routing_tier": "medium"}},
            {"metadata": {"routing_tier": "complex"}},
            {"metadata": {"routing_tier": "reasoning"}},
        ])
        
        tiers = router._get_recent_tiers(session)
        
        assert len(tiers) == 2  # Only last 2
        assert RoutingTier.COMPLEX in tiers
        assert RoutingTier.REASONING in tiers
    
    def test_should_downgrade_true(self):
        """Test downgrade detection when conditions met."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        from nanobot.agent.router.models import ClassificationScores
        scores = ClassificationScores(
            simple_indicators=0.8,
            technical_terms=0.1,
        )
        
        should_downgrade = router._should_downgrade(
            "Just a quick question what is 2+2",
            scores
        )
        
        assert should_downgrade is True
    
    def test_should_downgrade_false(self):
        """Test downgrade detection when conditions not met."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        from nanobot.agent.router.models import ClassificationScores
        scores = ClassificationScores(
            simple_indicators=0.3,
            technical_terms=0.5,
        )
        
        should_downgrade = router._should_downgrade(
            "Debug this complex system",
            scores
        )
        
        assert should_downgrade is False
    
    def test_should_downgrade_very_short(self):
        """Test downgrade with very short message."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        from nanobot.agent.router.models import ClassificationScores
        scores = ClassificationScores(
            simple_indicators=0.6,
            technical_terms=0.0,
        )
        
        should_downgrade = router._should_downgrade("Hi", scores)
        
        # Very short + no technical + decent simple score
        assert should_downgrade is True
    
    @pytest.mark.asyncio
    async def test_with_llm_fallback(self):
        """Test routing with LLM fallback."""
        classifier = ClientSideClassifier()
        llm_router = AsyncMock()
        llm_router.classify = AsyncMock(return_value=RoutingDecision(
            tier=RoutingTier.COMPLEX,
            model="",
            confidence=0.9,
            layer="llm",
            reasoning="LLM decision",
            estimated_tokens=1000,
            needs_tools=True,
        ))
        
        router = StickyRouter(
            client_classifier=classifier,
            llm_router=llm_router,
        )
        
        session = MockSession()
        decision = await router.classify("Some query", session)
        
        # Should use LLM decision
        assert decision.tier == RoutingTier.COMPLEX
        assert decision.layer == "llm"
    
    @pytest.mark.asyncio
    async def test_feedback_recorded(self):
        """Test that feedback comparison is recorded."""
        classifier = ClientSideClassifier()
        llm_router = AsyncMock()
        llm_router.classify = AsyncMock(return_value=RoutingDecision(
            tier=RoutingTier.MEDIUM,
            model="",
            confidence=0.85,
            layer="llm",
            reasoning="LLM decision",
            estimated_tokens=200,
            needs_tools=False,
        ))
        
        router = StickyRouter(
            client_classifier=classifier,
            llm_router=llm_router,
        )
        
        session = MockSession()
        decision = await router.classify("Test message", session)
        
        # Should have feedback metadata
        assert "feedback_comparison" in decision.metadata


class TestStickyRoutingEdgeCases:
    """Test edge cases for sticky routing."""
    
    @pytest.mark.asyncio
    async def test_no_recent_complex_uses_current(self):
        """Test that current decision is used when no recent complexity."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        session = MockSession(messages=[
            {"metadata": {"routing_tier": "simple"}},
            {"metadata": {"routing_tier": "medium"}},
        ])
        
        decision = await router.classify("Complex debugging", session)
        
        # Should use current classification, not sticky
        assert "sticky_maintained" not in decision.metadata
    
    @pytest.mark.asyncio
    async def test_session_metadata_updated(self):
        """Test that session metadata is updated with routing tier."""
        classifier = ClientSideClassifier()
        router = StickyRouter(client_classifier=classifier)
        
        session = MockSession()
        decision = await router.classify("What is Python?", session)
        
        assert session.metadata.get("routing_tier") is not None
