"""
Test-Driven Development for Model-Agnostic Buffered Image Generation

This module contains tests that drive the development of:
1. Model-agnostic buffer (works with any LLM provider)
2. Trigger function (decides when to use which agent)
3. Agent 1: Conversation Analyzer
4. Agent 2: Style Extractor
5. Agent 3: Cultural Adapter

Run tests: pytest tests/tools/buffered_tools/test_tdd_image_gen.py -v
"""

import pytest
from dataclasses import dataclass, field
from typing import Optional, Any


# ============================================================================
# PART 1: Model-Agnostic Buffer Tests
# ============================================================================

class TestModelAgnosticBuffer:
    """
    TDD: Model-Agnostic Buffer
    
    The buffer should:
    - Work with any LLM provider (OpenAI, Claude, Gemini, etc.)
    - Store conversation context independently of model
    - Provide unified interface for all agents
    """

    def test_buffer_creation(self):
        """[TDD-1] Buffer should be creatable without model specification"""
        # This test will FAIL initially - implement to make it pass
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_buffer import (
            ModelAgnosticBuffer
        )
        
        buffer = ModelAgnosticBuffer()
        
        assert buffer is not None
        assert buffer.conversation_history == []
        assert buffer.bot_profile is None

    def test_buffer_stores_conversation_turns(self):
        """[TDD-2] Buffer should store conversation turns with role"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_buffer import (
            ModelAgnosticBuffer,
            ConversationTurn
        )
        
        buffer = ModelAgnosticBuffer()
        
        # Add user message
        buffer.add_turn("user", "I want a beautiful mountain landscape")
        
        assert len(buffer.conversation_history) == 1
        assert buffer.conversation_history[0].role == "user"
        assert "mountain" in buffer.conversation_history[0].content

    def test_buffer_stores_bot_profile(self):
        """[TDD-3] Buffer should store bot profile for style extraction"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_buffer import (
            ModelAgnosticBuffer
        )
        
        buffer = ModelAgnosticBuffer()
        buffer.bot_profile = {
            "name": "Artistic Bot",
            "style": "traditional Chinese painting",
            "preferences": ["warm colors", "nature scenes"]
        }
        
        assert buffer.bot_profile["name"] == "Artistic Bot"
        assert buffer.bot_profile["style"] == "traditional Chinese painting"

    def test_buffer_provider_agnostic(self):
        """[TDD-4] Buffer should work with any provider"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_buffer import (
            ModelAgnosticBuffer
        )
        
        buffer = ModelAgnosticBuffer()
        
        # Set provider dynamically
        buffer.set_provider_config("openai", "gpt-4")
        assert buffer.current_provider == "openai"
        assert buffer.current_model == "gpt-4"
        
        # Switch provider
        buffer.set_provider_config("anthropic", "claude-sonnet-4-6")
        assert buffer.current_provider == "anthropic"
        assert buffer.current_model == "claude-sonnet-4-6"

    def test_buffer_builds_universal_prompt(self):
        """[TDD-5] Buffer should build prompts that work across models"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_buffer import (
            ModelAgnosticBuffer
        )
        
        buffer = ModelAgnosticBuffer()
        buffer.add_turn("user", "Generate a mountain scene")
        buffer.analysis_results = {
            "subject": "mountain landscape",
            "style": "realistic",
            "mood": "serene"
        }
        
        prompt = buffer.build_universal_prompt()
        
        assert "mountain" in prompt
        assert isinstance(prompt, str)
        assert len(prompt) > 0


# ============================================================================
# PART 2: Trigger Function Tests
# ============================================================================

class TestTriggerFunction:
    """
    TDD: Trigger Function
    
    The trigger function should:
    - Decide which agent to invoke based on context
    - Route requests appropriately
    - Handle edge cases
    """

    def test_trigger_exists(self):
        """[TDD-6] Trigger function should exist"""
        # This test will FAIL initially
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_trigger import (
            TriggerFunction
        )
        
        trigger = TriggerFunction()
        assert trigger is not None

    def test_trigger_routes_to_conversation_analyzer(self):
        """[TDD-7] Trigger should route new conversations to Agent 1"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_trigger import (
            TriggerFunction,
            AgentRoute
        )
        
        trigger = TriggerFunction()
        
        # New conversation with image request
        result = trigger.route_request(
            conversation_length=0,
            has_image_request=True,
            has_style_info=False
        )
        
        assert result == AgentRoute.CONVERSATION_ANALYZER

    def test_trigger_routes_to_style_extractor(self):
        """[TDD-8] Trigger should route to Agent 2 after analysis"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_trigger import (
            TriggerFunction,
            AgentRoute
        )
        
        trigger = TriggerFunction()
        
        # Conversation analyzed, need style
        result = trigger.route_request(
            conversation_length=5,
            has_image_request=True,
            has_style_info=False,
            has_analysis=True
        )
        
        assert result == AgentRoute.STYLE_EXTRACTOR

    def test_trigger_routes_to_cultural_adapter(self):
        """[TDD-9] Trigger should route to Agent 3 for cultural adaptation"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_trigger import (
            TriggerFunction,
            AgentRoute
        )
        
        trigger = TriggerFunction()
        
        # Style extracted, need cultural adaptation
        result = trigger.route_request(
            conversation_length=5,
            has_image_request=True,
            has_style_info=True,
            has_analysis=True,
            needs_cultural_adaptation=True
        )
        
        assert result == AgentRoute.CULTURAL_ADAPTER

    def test_trigger_routes_to_generation(self):
        """[TDD-10] Trigger should route to generation when all agents complete"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_trigger import (
            TriggerFunction,
            AgentRoute
        )
        
        trigger = TriggerFunction()
        
        # All agents completed
        result = trigger.route_request(
            conversation_length=5,
            has_image_request=True,
            has_style_info=True,
            has_analysis=True,
            needs_cultural_adaptation=False
        )
        
        assert result == AgentRoute.IMAGE_GENERATION


# ============================================================================
# PART 3: Agent 1 - Conversation Analyzer Tests
# ============================================================================

class TestAgent1ConversationAnalyzer:
    """
    TDD: Agent 1 - Conversation Analyzer
    
    This agent should:
    - Analyze conversation history
    - Extract user intent
    - Identify key visual elements
    - Work with any LLM provider
    """

    def test_agent1_exists(self):
        """[TDD-11] Agent 1 should exist"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent1ConversationAnalyzer
        )
        
        agent = Agent1ConversationAnalyzer()
        assert agent is not None

    def test_agent1_extracts_intent(self):
        """[TDD-12] Agent 1 should extract user intent from conversation"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent1ConversationAnalyzer,
            AnalysisResult
        )
        
        agent = Agent1ConversationAnalyzer()
        
        result = agent.analyze("I want a beautiful mountain landscape at sunset")
        
        assert isinstance(result, AnalysisResult)
        assert "mountain" in result.intent.lower() or "landscape" in result.intent.lower()

    def test_agent1_identifies_elements(self):
        """[TDD-13] Agent 1 should identify key visual elements"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent1ConversationAnalyzer
        )
        
        agent = Agent1ConversationAnalyzer()
        
        result = agent.analyze(
            "Generate a scene with mountains, trees, and a lake"
        )
        
        assert len(result.elements) > 0
        # Check that elements are identified (trees, water, etc.)
        elements_text = " ".join(result.elements).lower()
        assert any(word in elements_text for word in ["tree", "water", "vegetation", "lake"])

    def test_agent1_detects_emotional_tone(self):
        """[TDD-14] Agent 1 should detect emotional tone"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent1ConversationAnalyzer
        )
        
        agent = Agent1ConversationAnalyzer()
        
        result = agent.analyze(
            "I want a peaceful, serene mountain scene"
        )
        
        assert result.tone is not None
        assert "peaceful" in result.tone.lower() or "serene" in result.tone.lower()

    def test_agent1_model_agnostic(self):
        """[TDD-15] Agent 1 should work with any LLM provider"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent1ConversationAnalyzer
        )
        
        agent = Agent1ConversationAnalyzer()
        
        # Test with different provider configs
        agent.set_provider("openai")
        assert agent.current_provider == "openai"
        
        agent.set_provider("anthropic")
        assert agent.current_provider == "anthropic"


# ============================================================================
# PART 4: Agent 2 - Style Extractor Tests
# ============================================================================

class TestAgent2StyleExtractor:
    """
    TDD: Agent 2 - Style Extractor
    
    This agent should:
    - Extract artistic style preferences
    - Identify color palettes
    - Determine composition style
    - Work with any LLM provider
    """

    def test_agent2_exists(self):
        """[TDD-16] Agent 2 should exist"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent2StyleExtractor
        )
        
        agent = Agent2StyleExtractor()
        assert agent is not None

    def test_agent2_extracts_style_from_bot_profile(self):
        """[TDD-17] Agent 2 should extract style from bot profile"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent2StyleExtractor
        )
        
        agent = Agent2StyleExtractor()
        
        bot_profile = {
            "name": "Artistic Bot",
            "style": "impressionist painting",
            "preferences": ["vibrant colors", "nature"]
        }
        
        result = agent.extract_style(bot_profile)
        
        # Style should be returned (may be translated or kept as-is)
        assert result.style
        assert len(result.style) > 0

    def test_agent2_infers_color_palette(self):
        """[TDD-18] Agent 2 should infer color palette"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent2StyleExtractor
        )
        
        agent = Agent2StyleExtractor()
        
        bot_profile = {
            "name": "Warm Bot",
            "preferences": ["warm colors", "sunset scenes"]
        }
        
        result = agent.extract_style(bot_profile)
        
        assert result.color_palette is not None

    def test_agent2_determines_composition(self):
        """[TDD-19] Agent 2 should determine composition style"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent2StyleExtractor
        )
        
        agent = Agent2StyleExtractor()
        
        bot_profile = {
            "name": "Classical Bot",
            "style": "classical art"
        }
        
        result = agent.extract_style(bot_profile)
        
        assert result.composition is not None


# ============================================================================
# PART 5: Agent 3 - Cultural Adapter Tests
# ============================================================================

class TestAgent3CulturalAdapter:
    """
    TDD: Agent 3 - Cultural Adapter
    
    This agent should:
    - Add cultural appropriateness
    - Include cultural symbolism
    - Avoid taboos
    - Work with any LLM provider
    """

    def test_agent3_exists(self):
        """[TDD-20] Agent 3 should exist"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent3CulturalAdapter
        )
        
        agent = Agent3CulturalAdapter()
        assert agent is not None

    def test_agent3_adds_cultural_elements(self):
        """[TDD-21] Agent 3 should add cultural elements for Chinese context"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent3CulturalAdapter
        )
        
        agent = Agent3CulturalAdapter()
        
        result = agent.adapt("mountain landscape", target_culture="chinese")
        
        assert len(result.cultural_elements) > 0
        assert any("中国" in e or "Chinese" in e or "东方" in e 
                   for e in result.cultural_elements)

    def test_agent3_identifies_symbolism(self):
        """[TDD-22] Agent 3 should identify cultural symbolism"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent3CulturalAdapter
        )
        
        agent = Agent3CulturalAdapter()
        
        result = agent.adapt("pine tree and crane", target_culture="chinese")
        
        assert len(result.symbolism) > 0
        # Pine and crane symbolize longevity in Chinese culture

    def test_agent3_avoids_taboos(self):
        """[TDD-23] Agent 3 should identify cultural taboos"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent3CulturalAdapter
        )
        
        agent = Agent3CulturalAdapter()
        
        result = agent.adapt("funeral scene", target_culture="chinese")
        
        assert hasattr(result, 'taboos_to_avoid')
        assert len(result.taboos_to_avoid) > 0


# ============================================================================
# PART 6: Integration Tests
# ============================================================================

class TestIntegration:
    """
    Integration Tests
    
    Test the complete flow from trigger to generation
    """

    def test_full_agent_pipeline(self):
        """[TDD-24] Full pipeline should work end-to-end"""
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_buffer import (
            ModelAgnosticBuffer
        )
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_trigger import (
            TriggerFunction,
            AgentRoute
        )
        from nanobot.agent.tools.buffered_tools.image_gen.tdd_agents import (
            Agent1ConversationAnalyzer,
            Agent2StyleExtractor,
            Agent3CulturalAdapter
        )
        
        # Create buffer
        buffer = ModelAgnosticBuffer()
        buffer.add_turn("user", "I want a beautiful Chinese mountain painting")
        
        # Create trigger
        trigger = TriggerFunction()
        
        # Route to Agent 1
        route = trigger.route_request(
            conversation_length=1,
            has_image_request=True,
            has_style_info=False
        )
        assert route == AgentRoute.CONVERSATION_ANALYZER
        
        # Agent 1 analyzes
        agent1 = Agent1ConversationAnalyzer()
        analysis = agent1.analyze(buffer.conversation_history[0].content)
        buffer.analysis_results = analysis.to_dict()
        
        # Route to Agent 2
        route = trigger.route_request(
            conversation_length=1,
            has_image_request=True,
            has_style_info=False,
            has_analysis=True
        )
        assert route == AgentRoute.STYLE_EXTRACTOR
        
        # Agent 2 extracts style
        agent2 = Agent2StyleExtractor()
        style = agent2.extract_style({"name": "Artistic Bot"})
        buffer.style_results = style.to_dict()
        
        # Route to Agent 3
        route = trigger.route_request(
            conversation_length=1,
            has_image_request=True,
            has_style_info=True,
            has_analysis=True,
            needs_cultural_adaptation=True
        )
        assert route == AgentRoute.CULTURAL_ADAPTER
        
        # Agent 3 adapts culturally
        agent3 = Agent3CulturalAdapter()
        cultural = agent3.adapt(analysis.intent, target_culture="chinese")
        buffer.cultural_results = cultural.to_dict()
        
        # Final route to generation
        route = trigger.route_request(
            conversation_length=1,
            has_image_request=True,
            has_style_info=True,
            has_analysis=True,
            needs_cultural_adaptation=False
        )
        assert route == AgentRoute.IMAGE_GENERATION
        
        # Build final prompt
        final_prompt = buffer.build_universal_prompt()
        assert len(final_prompt) > 0


# ============================================================================
# Helper Classes for Tests (Will be moved to implementation)
# ============================================================================

@dataclass
class AnalysisResult:
    """Result from agent analysis"""
    intent: str = ""
    elements: list[str] = field(default_factory=list)
    tone: str = ""
    
    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "elements": self.elements,
            "tone": self.tone
        }


@dataclass
class StyleResult:
    """Result from style extraction"""
    style: str = ""
    color_palette: str = ""
    composition: str = ""
    
    def to_dict(self) -> dict:
        return {
            "style": self.style,
            "color_palette": self.color_palette,
            "composition": self.composition
        }


@dataclass
class CulturalResult:
    """Result from cultural adaptation"""
    cultural_elements: list[str] = field(default_factory=list)
    symbolism: list[str] = field(default_factory=list)
    taboos_to_avoid: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "cultural_elements": self.cultural_elements,
            "symbolism": self.symbolism,
            "taboos_to_avoid": self.taboos_to_avoid
        }
