"""AgentScope monitoring integration for nanobot.

This module provides comprehensive monitoring for nanobot's internal workings.
Uses AgentScope Scheme 3: Context Manager + Context Propagation.
"""

import time
import json
from typing import Any, Optional, Dict, List
from contextvars import ContextVar

from loguru import logger

# AgentScope integration - Scheme 3
# Import both old APIs and new Scheme 3 APIs
try:
    from agentscope import (
        init_monitor,
        trace_scope,
        get_current_trace,
        add_step,
        add_llm_call,
        add_tool_call,
        add_thinking,
        add_memory,
        instrument_llm,
        instrumented_tool,
    )
    from agentscope.models import TraceEvent, ExecutionStep, StepType, Status, ToolCall
    # Keep backward compatibility
    from agentscope.monitor import set_current_trace as _set_trace, _send_trace
    _AGENTSCOPE_AVAILABLE = True
    _SCHEME3_AVAILABLE = True
    logger.info("AgentScope Scheme 3 monitoring available")
except ImportError as e:
    _AGENTSCOPE_AVAILABLE = False
    _SCHEME3_AVAILABLE = False
    logger.warning(f"AgentScope not available: {e}")
    # Define stubs when AgentScope is not available
    TraceEvent = None
    ExecutionStep = None
    StepType = None
    Status = None
    ToolCall = None
    
    def init_monitor(*args, **kwargs):
        pass
    
    def get_current_trace():
        return None
    
    def _set_trace(trace):
        pass
    
    def _send_trace(trace):
        pass
    
    def trace_scope(*args, **kwargs):
        """Dummy context manager."""
        from contextlib import nullcontext
        return nullcontext()
    
    def add_step(*args, **kwargs):
        pass
    
    def add_llm_call(*args, **kwargs):
        pass
    
    def add_tool_call(*args, **kwargs):
        pass
    
    def add_thinking(*args, **kwargs):
        pass
    
    def add_memory(*args, **kwargs):
        pass
    
    def instrument_llm(client):
        return client
    
    def instrumented_tool(func=None, **kwargs):
        if func:
            return func
        def decorator(f):
            return f
        return decorator

# Current trace context (for backward compatibility)
_current_trace: ContextVar[Optional[TraceEvent]] = ContextVar('nanobot_trace', default=None)


def get_trace() -> Optional[TraceEvent]:
    """Get current trace from context (Scheme 3 compatible)."""
    if not _AGENTSCOPE_AVAILABLE:
        return None
    # Use new Scheme 3 API first, fallback to context var
    return get_current_trace()


def start_trace(name: str, tags: List[str], input_query: str) -> Optional[TraceEvent]:
    """Start a new trace for message processing (legacy API).
    
    Note: New code should use trace_scope() context manager directly.
    """
    if not _AGENTSCOPE_AVAILABLE:
        return None
    
    try:
        trace = TraceEvent(name=name, tags=tags)
        trace.input_query = input_query[:1000]
        _set_trace(trace)
        
        # Add input step
        add_step(
            StepType.INPUT,
            input_query[:500],
        )
        
        logger.debug(f"AgentScope: Started trace {trace.id} for {name}")
        return trace
    except Exception as e:
        logger.warning(f"AgentScope: Failed to start trace: {e}")
        return None


def finish_trace(trace: Optional[TraceEvent], output: Optional[str], error: Optional[Exception] = None):
    """Finish and send trace to AgentScope (legacy API)."""
    if not trace or not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        if error:
            add_step(
                StepType.ERROR,
                str(error)[:500],
                status=Status.ERROR,
            )
            trace.finish(Status.ERROR)
            logger.debug(f"AgentScope: Trace {trace.id} finished with error")
        else:
            output_str = output[:1000] if output else ""
            trace.output_result = output_str
            add_step(
                StepType.OUTPUT,
                output_str[:500],
            )
            trace.finish(Status.SUCCESS)
            logger.debug(f"AgentScope: Trace {trace.id} finished successfully")
        
        _send_trace(trace)
    except Exception as e:
        logger.warning(f"AgentScope: Failed to finish trace: {e}")


def add_context_building_step(session_key: str, history_count: int, skills_used: List[str]):
    """Record context building step."""
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        content = f"Building context for session {session_key[:20]}...\n"
        content += f"- History messages: {history_count}\n"
        content += f"- Skills loaded: {', '.join(skills_used) if skills_used else 'None'}"
        
        add_thinking(content)
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
    if not _AGENTSCOPE_AVAILABLE:
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
        
        add_llm_call(
            prompt=f"Messages: {messages_count}",
            completion=content,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latency_ms=latency_ms,
        )
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
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        add_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            error=error,
            latency_ms=latency_ms,
        )
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add tool step: {e}")


def add_skill_trigger_step(skill_name: str, trigger_reason: str):
    """Record skill triggering."""
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        add_thinking(f"Skill triggered: {skill_name}\nReason: {trigger_reason}")
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add skill step: {e}")


def add_memory_step(action: str, details: str):
    """Record memory operation."""
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        add_memory(action, details)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add memory step: {e}")


def add_prompt_building_step(
    system_prompt: str,
    history_count: int,
    context_length: int,
    max_context: int
):
    """Record prompt building step.
    
    Args:
        system_prompt: System prompt content (truncated)
        history_count: Number of history messages included
        context_length: Total context length in characters/tokens
        max_context: Maximum allowed context size
    """
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        usage_percent = (context_length / max_context * 100) if max_context > 0 else 0
        content = f"Building final prompt for LLM\n"
        content += f"- System prompt: {len(system_prompt)} chars\n"
        content += f"- History messages: {history_count}\n"
        content += f"- Context size: {context_length}/{max_context} ({usage_percent:.1f}%)\n"
        
        if usage_percent > 80:
            content += "⚠️ Warning: Context window usage high!"
        
        add_thinking(content)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add prompt building step: {e}")


def add_context_window_step(
    operation: str,
    original_count: int,
    new_count: int,
    reason: str
):
    """Record context window management operation.
    
    Args:
        operation: 'truncate', 'summarize', 'archive', etc.
        original_count: Original message count
        new_count: New message count after operation
        reason: Why the operation was performed
    """
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        reduction = original_count - new_count
        content = f"Context window management: {operation}\n"
        content += f"- Messages: {original_count} → {new_count} ({reduction} removed)\n"
        content += f"- Reason: {reason}"
        
        add_thinking(content)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add context window step: {e}")


def add_retry_step(
    attempt: int,
    max_attempts: int,
    error_type: str,
    delay: float,
    will_retry: bool
):
    """Record retry attempt.
    
    Args:
        attempt: Current attempt number
        max_attempts: Maximum allowed attempts
        error_type: Type of error encountered
        delay: Delay before retry in seconds
        will_retry: Whether another retry will be attempted
    """
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        content = f"LLM call retry: attempt {attempt}/{max_attempts}\n"
        content += f"- Error: {error_type}\n"
        content += f"- Delay: {delay}s\n"
        content += f"- Will retry: {will_retry}"
        
        add_thinking(content)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add retry step: {e}")


def add_rate_limit_step(
    limit_type: str,
    current_usage: int,
    limit: int,
    wait_time: float = 0
):
    """Record rate limit event.
    
    Args:
        limit_type: 'requests', 'tokens', etc.
        current_usage: Current usage count
        limit: Maximum allowed
        wait_time: Time waited before proceeding (if throttled)
    """
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        usage_percent = (current_usage / limit * 100) if limit > 0 else 0
        content = f"Rate limit check: {limit_type}\n"
        content += f"- Usage: {current_usage}/{limit} ({usage_percent:.1f}%)\n"
        
        if wait_time > 0:
            content += f"- Throttled: waited {wait_time:.1f}s"
        
        add_thinking(content)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add rate limit step: {e}")


def add_session_lifecycle_step(
    event: str,
    session_key: str,
    details: str = ""
):
    """Record session lifecycle event.
    
    Args:
        event: 'created', 'loaded', 'saved', 'archived', 'destroyed'
        session_key: Session identifier
        details: Additional details about the event
    """
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        content = f"Session {event}: {session_key}\n"
        if details:
            content += f"Details: {details}"
        
        add_thinking(content)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add session lifecycle step: {e}")


def add_skill_loading_step(
    skills: List[str],
    loaded_count: int,
    failed_count: int,
    total_time_ms: float
):
    """Record skill loading operation.
    
    Args:
        skills: List of skill names requested
        loaded_count: Number successfully loaded
        failed_count: Number failed to load
        total_time_ms: Time taken to load
    """
    if not _AGENTSCOPE_AVAILABLE:
        return
    
    try:
        content = f"Loading skills: {', '.join(skills)}\n"
        content += f"- Success: {loaded_count}, Failed: {failed_count}\n"
        content += f"- Load time: {total_time_ms:.1f}ms"
        
        add_thinking(content)
    except Exception as e:
        logger.debug(f"AgentScope: Failed to add skill loading step: {e}")


class TraceContext:
    """Context manager for tracing (now wraps trace_scope for Scheme 3)."""
    
    def __init__(self, name: str, tags: List[str], input_query: str):
        self.name = name
        self.tags = tags
        self.input_query = input_query
        self.trace: Optional[TraceEvent] = None
        self._context_manager = None
    
    def __enter__(self):
        if _SCHEME3_AVAILABLE:
            self._context_manager = trace_scope(
                name=self.name,
                input_query=self.input_query,
                tags=self.tags
            )
            self.trace = self._context_manager.__enter__()
        else:
            # Fallback to legacy implementation
            self.trace = start_trace(self.name, self.tags, self.input_query)
        return self.trace
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context_manager:
            return self._context_manager.__exit__(exc_type, exc_val, exc_tb)
        else:
            finish_trace(self.trace, None, exc_val)
            return False
    
    async def __aenter__(self):
        return self.__enter__()
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)


# Export Scheme 3 APIs for direct use
__all__ = [
    'init_monitor',
    'trace_scope',
    'get_trace',
    'start_trace',
    'finish_trace',
    'add_context_building_step',
    'add_llm_call_step',
    'add_tool_execution_step',
    'add_skill_trigger_step',
    'add_memory_step',
    'add_prompt_building_step',
    'add_context_window_step',
    'add_retry_step',
    'add_rate_limit_step',
    'add_session_lifecycle_step',
    'add_skill_loading_step',
    'TraceContext',
    'instrument_llm',
    'instrumented_tool',
]
