"""Optional agent-loop guards that detect common LLM failure modes.

Guards are opt-in `AgentHook` implementations. They never block a turn by
default — they observe, log, and optionally annotate the final response so
the user is not silently misled.
"""

from nanobot.agent.guards.hallucinated_tool_call import (
    HallucinatedToolCallGuard,
    HallucinatedToolCallGuardConfig,
)

__all__ = [
    "HallucinatedToolCallGuard",
    "HallucinatedToolCallGuardConfig",
]
