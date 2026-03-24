"""Orchestrator protocol and shared turn data types.

``TurnState`` is the mutable state bag shared across iterations of the
Plan-Act-Observe-Reflect loop.  ``TurnResult`` is the immutable output.
Both live here (rather than in ``turn_orchestrator.py``) so that
``message_processor.py`` can reference them without importing the concrete
``TurnOrchestrator`` class, avoiding an import cycle.

``Orchestrator`` is a structural ``Protocol`` satisfied by
``TurnOrchestrator`` (and any test mock that exposes the same ``run``
signature).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from nanobot.agent.failure import ToolCallTracker

if TYPE_CHECKING:
    from nanobot.agent.callbacks import ProgressCallback
    from nanobot.coordination.coordinator import ClassificationResult
    from nanobot.coordination.delegation_advisor import DelegationAction


@dataclass(slots=True)
class TurnState:
    """Mutable state shared across iterations of the Plan-Act-Observe-Reflect loop."""

    messages: list[dict[str, Any]]
    user_text: str
    classification_result: ClassificationResult | None = None
    disabled_tools: set[str] = field(default_factory=set)
    tracker: ToolCallTracker = field(default_factory=ToolCallTracker)
    nudged_for_final: bool = False
    turn_tool_calls: int = 0
    last_tool_call_msg_idx: int = -1
    last_delegation_advice: DelegationAction | None = None
    has_plan: bool = False
    plan_enforced: bool = False
    consecutive_errors: int = 0
    iteration: int = 0
    tools_def_cache: list[dict[str, Any]] = field(default_factory=list)
    tools_def_snapshot: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Immutable result of a single turn of the PAOR loop."""

    content: str
    tools_used: list[str]  # tool names called this turn; empty list = no tools used
    messages: list[dict[str, Any]]
    tokens_prompt: int = 0
    tokens_completion: int = 0
    llm_calls: int = 0


class Orchestrator(Protocol):
    """Structural protocol for the turn orchestrator.

    Any object with a compatible ``run`` method satisfies this protocol,
    including ``TurnOrchestrator`` and test mocks.  Zero attributes —
    pure behavioral contract.
    """

    async def run(
        self,
        state: TurnState,
        on_progress: ProgressCallback | None,
    ) -> TurnResult:
        """Execute one full turn of the Plan-Act-Observe-Reflect loop."""
