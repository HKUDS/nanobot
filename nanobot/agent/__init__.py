"""Agent core module."""

from __future__ import annotations

from nanobot.agent.agent_factory import build_agent
from nanobot.agent.callbacks import (
    DelegateEndEvent,
    DelegateStartEvent,
    ProgressCallback,
    ProgressEvent,
    StatusEvent,
    TextChunk,
    ToolCallEvent,
    ToolResultEvent,
)
from nanobot.agent.consolidation import ConsolidationOrchestrator
from nanobot.agent.context import ContextBuilder
from nanobot.agent.coordinator import ClassificationResult, Coordinator
from nanobot.agent.delegation import DelegationDispatcher
from nanobot.agent.delegation_advisor import DelegationAdvisor
from nanobot.agent.loop import AgentLoop
from nanobot.agent.message_processor import MessageProcessor
from nanobot.agent.mission import MissionManager
from nanobot.agent.observability import init_langfuse
from nanobot.agent.observability import shutdown as shutdown_langfuse
from nanobot.agent.prompt_loader import PromptLoader
from nanobot.agent.registry import AgentRegistry
from nanobot.agent.scratchpad import Scratchpad
from nanobot.agent.skills import SkillsLoader
from nanobot.agent.streaming import StreamingLLMCaller
from nanobot.agent.tool_executor import ToolExecutor
from nanobot.agent.turn_types import TurnResult
from nanobot.agent.verifier import AnswerVerifier

__all__ = [
    "AgentLoop",
    "AgentRegistry",
    "AnswerVerifier",
    "ClassificationResult",
    "ConsolidationOrchestrator",
    "ContextBuilder",
    "Coordinator",
    "DelegateEndEvent",
    "DelegateStartEvent",
    "DelegationAdvisor",
    "DelegationDispatcher",
    "MessageProcessor",
    "MissionManager",
    "ProgressCallback",
    "ProgressEvent",
    "PromptLoader",
    "Scratchpad",
    "SkillsLoader",
    "StatusEvent",
    "StreamingLLMCaller",
    "TextChunk",
    "ToolCallEvent",
    "ToolExecutor",
    "ToolResultEvent",
    "TurnResult",
    "build_agent",
    "init_langfuse",
    "shutdown_langfuse",
]
