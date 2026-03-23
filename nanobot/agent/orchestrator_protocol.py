"""Orchestrator protocol and shared TurnState dataclass.

``TurnState`` is the mutable state bag shared across iterations of the
Plan-Act-Observe-Reflect loop.  It lives here (rather than in
``turn_orchestrator.py``) so that ``message_processor.py`` can reference
it without importing the concrete ``TurnOrchestrator`` class, eliminating
a deferred import cycle.

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
    from nanobot.agent.coordinator import ClassificationResult
    from nanobot.agent.delegation_advisor import DelegationAction
    from nanobot.agent.turn_orchestrator import TurnResult


@dataclass(slots=True)
class TurnState:
    """Mutable state shared across iterations of the Plan-Act-Observe-Reflect loop."""

    messages: list[dict[str, Any]]
    user_text: str
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


class Orchestrator(Protocol):
    """Structural protocol for the turn orchestrator.

    Any object with a compatible ``run`` method satisfies this protocol,
    including ``TurnOrchestrator`` and test mocks.
    """

    _last_classification_result: ClassificationResult | None

    async def run(
        self,
        state: TurnState,
        on_progress: ProgressCallback | None,
    ) -> TurnResult:
        """Execute one full turn of the Plan-Act-Observe-Reflect loop."""  # Protocol stub
