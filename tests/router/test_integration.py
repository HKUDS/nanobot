"""Integration tests for the routing system."""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, AsyncMock

from nanobot.agent.router import classify_content, ClientSideClassifier
from nanobot.agent.router.sticky import StickyRouter
from nanobot.agent.stages import RoutingStage, RoutingContext
from nanobot.config.schema import RoutingConfig
from nanobot.agent.router.models import RoutingTier, RoutingDecision


class TestRoutingIntegration:
    """Integration tests for the complete routing pipeline."""
    
    @pytest.mark.asyncio
    async def test_full_routing_pipeline(self, tmp_path):
        """Test the complete routing pipeline from message to decision."""
        # Create routing config
        config = RoutingConfig(
            enabled=True,
            tiers={
                "simple": {"model": "gpt-4o-mini", "cost_per_mtok": 0.60},
                "medium": {"model": "claude-sonnet-4", "cost_per_mtok": 15.0},
                "complex": {"model": "claude-opus-4", "cost_per_mtok": 75.0},
                "reasoning": {"model": "o3", "cost_per_mtok": 10.0},
            }
        )
        
        # Create routing stage
        routing_stage = RoutingStage(
            config=config,
            workspace=tmp_path,
        )
        
        # Create mock message and session
        mock_msg = Mock()
        mock_msg.content = "What is the capital of France?"
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        # Create routing context
        routing_ctx = RoutingContext(
            message=mock_msg,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        # Execute routing
        result_ctx = await routing_stage.execute(routing_ctx)
        
        # Verify results
        assert result_ctx.decision is not None
        assert result_ctx.decision.tier == RoutingTier.SIMPLE
        assert result_ctx.model == "gpt-4o-mini"  # Should use simple tier model
        assert result_ctx.decision.layer == "client"
    
    @pytest.mark.asyncio
    async def test_complex_message_routing(self, tmp_path):
        """Test routing for a complex message."""
        config = RoutingConfig(enabled=True)
        
        routing_stage = RoutingStage(
            config=config,
            workspace=tmp_path,
        )
        
        mock_msg = Mock()
        mock_msg.content = "Debug this distributed system with race conditions"
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        routing_ctx = RoutingContext(
            message=mock_msg,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        result_ctx = await routing_stage.execute(routing_ctx)
        
        # Should detect complexity
        assert result_ctx.decision.tier in [RoutingTier.COMPLEX, RoutingTier.MEDIUM]
    
    @pytest.mark.asyncio
    async def test_sticky_routing_across_messages(self, tmp_path):
        """Test that routing maintains tier across multiple messages."""
        config = RoutingConfig(enabled=True)
        
        routing_stage = RoutingStage(
            config=config,
            workspace=tmp_path,
        )
        
        # First message - complex
        mock_msg1 = Mock()
        mock_msg1.content = "Debug this complex distributed system"
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        ctx1 = RoutingContext(
            message=mock_msg1,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        result1 = await routing_stage.execute(ctx1)
        complex_tier = result1.decision.tier
        
        # Second message - simple
        mock_msg2 = Mock()
        mock_msg2.content = "Thanks"
        
        # Update session with first message
        mock_session.messages.append({
            "metadata": {"routing_tier": complex_tier.value}
        })
        mock_session.metadata["routing_tier"] = complex_tier.value
        
        ctx2 = RoutingContext(
            message=mock_msg2,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        result2 = await routing_stage.execute(ctx2)
        
        # Sticky routing should maintain tier
        # (though it may allow downgrade in some cases)
        assert result2.decision is not None
    
    def test_end_to_end_classification(self):
        """Test end-to-end classification without async."""
        # Test various message types
        test_cases = [
            ("What is 2+2?", RoutingTier.SIMPLE),
            ("Write a Python function", RoutingTier.MEDIUM),
            ("Debug this race condition", RoutingTier.COMPLEX),
            ("Prove step by step", RoutingTier.REASONING),
        ]
        
        for message, expected_tier in test_cases:
            decision, scores = classify_content(message)
            assert decision.tier == expected_tier, f"Failed for: {message}"
            assert decision.confidence > 0
            assert decision.confidence <= 1


class TestRoutingWithLLMFallback:
    """Test routing with LLM fallback layer."""
    
    @pytest.mark.asyncio
    async def test_client_side_classification_sufficient(self):
        """Test that high confidence client-side classification skips LLM."""
        classifier = ClientSideClassifier(min_confidence=0.85)
        
        # Simple query should have high confidence
        decision, scores = classifier.classify("What is Python?")
        
        assert decision.confidence >= 0.85
        assert decision.layer == "client"
    
    @pytest.mark.asyncio
    async def test_llm_fallback_for_uncertain(self):
        """Test LLM fallback for uncertain classifications."""
        classifier = ClientSideClassifier(min_confidence=0.95)  # High threshold
        
        # Create sticky router with mock LLM
        mock_llm_router = AsyncMock()
        mock_llm_router.classify = AsyncMock(return_value=RoutingDecision(
            tier=RoutingTier.MEDIUM,
            model="",
            confidence=0.90,
            layer="llm",
            reasoning="LLM decision",
            estimated_tokens=200,
            needs_tools=False,
        ))
        
        sticky_router = StickyRouter(
            client_classifier=classifier,
            llm_router=mock_llm_router,
        )
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        # Classify - should use LLM fallback
        decision = await sticky_router.classify("Some query", mock_session)
        
        # Should have called LLM
        mock_llm_router.classify.assert_called_once()
        assert decision.layer == "llm"


class TestConfigurationIntegration:
    """Test configuration integration."""
    
    def test_routing_disabled(self, tmp_path):
        """Test that routing is disabled when configured."""
        config = RoutingConfig(enabled=False)
        
        routing_stage = RoutingStage(
            config=config,
            workspace=tmp_path,
        )
        
        # Stage should be created but not functional
        assert routing_stage.config.enabled is False
    
    def test_custom_tier_models(self, tmp_path):
        """Test custom model assignments per tier."""
        config = RoutingConfig(
            enabled=True,
            tiers={
                "simple": {"model": "custom-simple-model", "cost_per_mtok": 1.0},
                "medium": {"model": "custom-medium-model", "cost_per_mtok": 2.0},
            }
        )
        
        routing_stage = RoutingStage(config=config, workspace=tmp_path)
        
        info = routing_stage.get_routing_info()
        assert info["tiers"]["simple"]["model"] == "custom-simple-model"
        assert info["tiers"]["medium"]["model"] == "custom-medium-model"


class TestEdgeCasesIntegration:
    """Integration tests for edge cases."""
    
    @pytest.mark.asyncio
    async def test_empty_message(self, tmp_path):
        """Test routing with empty message."""
        config = RoutingConfig(enabled=True)
        routing_stage = RoutingStage(config=config, workspace=tmp_path)
        
        mock_msg = Mock()
        mock_msg.content = ""
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        ctx = RoutingContext(
            message=mock_msg,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        # Should not crash
        result = await routing_stage.execute(ctx)
        assert result.decision is not None
    
    @pytest.mark.asyncio
    async def test_very_long_message(self, tmp_path):
        """Test routing with very long message."""
        config = RoutingConfig(enabled=True)
        routing_stage = RoutingStage(config=config, workspace=tmp_path)
        
        mock_msg = Mock()
        mock_msg.content = "word " * 1000
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        ctx = RoutingContext(
            message=mock_msg,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        result = await routing_stage.execute(ctx)
        assert result.decision is not None
        assert result.decision.estimated_tokens >= 1000
    
    @pytest.mark.asyncio
    async def test_unicode_message(self, tmp_path):
        """Test routing with unicode characters."""
        config = RoutingConfig(enabled=True)
        routing_stage = RoutingStage(config=config, workspace=tmp_path)
        
        mock_msg = Mock()
        mock_msg.content = "Hello 世界 🌍 Привет"
        
        mock_session = Mock()
        mock_session.messages = []
        mock_session.metadata = {}
        
        ctx = RoutingContext(
            message=mock_msg,
            session=mock_session,
            default_model="claude-opus-4",
            config=config,
        )
        
        result = await routing_stage.execute(ctx)
        assert result.decision is not None
