"""AgentScope monitoring integration for nanobot.

This module provides comprehensive monitoring for nanobot's internal workings.
"""

import time
import json
from typing import Any, Optional, Dict, List
from contextvars import ContextVar

from loguru import logger

# AgentScope integration
try:
    from agentscope import init_monitor
    from agentscope.models import TraceEvent, ExecutionStep, StepType, Status, ToolCall
    from agentscope.monitor import get_current_trace, set_current_trace, _send_trace
    _AGENTSCOPE_AVAILABLE = True
except ImportError:
    _AGENTSCOPE_AVAILABLE = False

# Current trace context
_current_trace: ContextVar[Optional[TraceEvent]] = ContextVar('nanobot_trace', default=None)


def get_trace() -> Optional[TraceEvent]:
    """Get current trace from context."""
    if not _AGENTSCOPE_AVAILABLE:
        return None
    return get_current_trace()


def start_trace(name: str, tags: List[str], input_query: str) -> Optional[TraceEvent]:
    """Start a new trace for message processing."""
    if not _AGENTSCOPE_AVAILABLE:
        return None
    
    try:
        trace = TraceEvent(name=name, tags=tags)
        trace.input_query = input_query[:1000]
        set_current_trace(trace)
        
        # Add input step
        trace.add_step(ExecutionStep(
            type=StepType.INPUT,
            content=input_query[:500],
            status=Status.SUCCESS,
        ))
        
        logger.debug(f"AgentScope: Started trace {trace.id} for {name}")
        return trace
    except Exception as e:
        logger.warning(f"AgentScope: Failed to start trace: {e}")
        return None


def finish_trace(trace: Optional[TraceEvent], output: Optional[str], error: Optional[Exception] = None):
    """Finish and send trace to AgentScope."""
    if not trace or not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        if error:
            trace.add_step(ExecutionStep(
                type=StepType.ERROR,
                content=str(error)[:500],
                status=Status.ERROR,
            ))
            trace.finish(Status.ERROR)
            logger.debug(f"AgentScope: Trace {trace.id} finished with error")
        else:
            output_str = output[:1000] if output else ""
            trace.output_result = output_str
            trace.add_step(ExecutionStep(
                type=StepType.OUTPUT,
                content=output_str[:500],
                status=Status.SUCCESS,
            ))
            trace.finish(Status.SUCCESS)
            logger.debug(f"AgentScope: Trace {trace.id} finished successfully")
        
        _send_trace(trace)
    except Exception as e:
        logger.warning(f"AgentScope: Failed to finish trace: {e}")


def add_context_building_step(session_key: str, history_count: int, skills_used: List[str]):
    """Record context building step."""
    trace = get_trace()
    if not trace:
        return
    
    try:
        content = f"Building context for session {session_key[:20]}...\n"
        content += f"- History messages: {history_count}\n"
        content += f"- Skills loaded: {', '.join(skills_used) if skills_used else 'None'}"
        
        trace.add_step(ExecutionStep(
            type=StepType.THINKING,
            content=content,
            status=Status.SUCCESS,
        ))
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add context step: {e}")


def add_llm_call_step(
    model: str,
    messages_count: int,
    tools_count: int,
    response_content: Optional[str],
    tool_calls: List[Dict],
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: float = 0
):
    """Record LLM call step."""
    trace = get_trace()
    if not trace:
        return
    
    try:
        content = f"Model: {model}\n"
        content += f"Messages: {messages_count}, Tools: {tools_count}\n"
        
        if tool_calls:
            content += f"Tool calls requested: {len(tool_calls)}\n"
            for tc in tool_calls:
                content += f"  - {tc.get('name', 'unknown')}\n"
        
        if response_content:
            content += f"Response preview: {response_content[:200]}..."
        
        trace.add_step(ExecutionStep(
            type=StepType.LLM_CALL,
            content=content,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latency_ms=latency_ms,
            status=Status.SUCCESS,
        ))
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add LLM step: {e}")


def add_tool_execution_step(
    tool_name: str,
    arguments: Dict[str, Any],
    result: Any,
    error: Optional[str] = None,
    latency_ms: float = 0
):
    """Record tool execution step."""
    trace = get_trace()
    if not trace:
        return
    
    try:
        result_str = str(result)[:500] if result is not None else "None"
        
        tool_call = ToolCall(
            name=tool_name,
            arguments=arguments,
            result=result_str if not error else None,
            error=error,
            latency_ms=latency_ms,
        )
        
        trace.add_step(ExecutionStep(
            type=StepType.TOOL_CALL,
            content=f"Tool: {tool_name}",
            tool_call=tool_call,
            latency_ms=latency_ms,
            status=Status.ERROR if error else Status.SUCCESS,
        ))
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add tool step: {e}")


def add_skill_trigger_step(skill_name: str, trigger_reason: str):
    """Record skill triggering."""
    trace = get_trace()
    if not trace:
        return
    
    try:
        trace.add_step(ExecutionStep(
            type=StepType.THINKING,
            content=f"Skill triggered: {skill_name}\nReason: {trigger_reason}",
            status=Status.SUCCESS,
        ))
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add skill step: {e}")


def add_memory_step(action: str, details: str):
    """Record memory operation."""
    trace = get_trace()
    if not trace:
        return
    
    try:
        trace.add_step(ExecutionStep(
            type=StepType.THINKING,
            content=f"Memory {action}: {details}",
            status=Status.SUCCESS,
        ))
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add memory step: {e}")


class TraceContext:
    """Context manager for tracing."""
    
    def __init__(self, name: str, tags: List[str], input_query: str):
        self.name = name
        self.tags = tags
        self.input_query = input_query
        self.trace: Optional[TraceEvent] = None
    
    def __enter__(self):
        self.trace = start_trace(self.name, self.tags, self.input_query)
        return self.trace
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        finish_trace(self.trace, None, exc_val)
        return False
    
    async def __aenter__(self):
        self.trace = start_trace(self.name, self.tags, self.input_query)
        return self.trace
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        finish_trace(self.trace, None, exc_val)
        return False
