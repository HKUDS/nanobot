"""
FIT-Sec Emptiness Window
========================
Operational safety mode that removes commit power while preserving cognition.

This implements the "Controlled Nirvana" concept from FIT Phase II:
- Pause irreversible actions
- Keep reasoning, planning, summarization alive
- Generate review packets for human oversight
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .types import EmptinessState, OmegaLevel, ToolCall


@dataclass
class ReviewPacket:
    """Human review artifact generated during Emptiness mode."""
    packet_id: str
    timestamp: float
    blocked_calls: List[ToolCall]
    proposed_plan: Optional[str] = None
    dry_run_diffs: List[Dict[str, Any]] = field(default_factory=list)
    context_summary: Optional[str] = None
    recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "timestamp": self.timestamp,
            "blocked_calls": [
                {"tool_id": c.tool_id, "action": c.action, "args": c.args}
                for c in self.blocked_calls
            ],
            "proposed_plan": self.proposed_plan,
            "dry_run_diffs": self.dry_run_diffs,
            "context_summary": self.context_summary,
            "recommendation": self.recommendation,
        }


class EmptinessWindow:
    """
    Emptiness Window controller.

    When active:
    - Ω1/Ω2 actions are blocked
    - Only safe reads (Ω0) are allowed
    - Blocked calls are collected into review packets
    - The window is "sticky" - stays active until explicitly cleared
    """

    def __init__(self):
        self._state = EmptinessState.NORMAL
        self._activated_at: Optional[float] = None
        self._activation_reason: str = ""
        self._blocked_calls: List[ToolCall] = []
        self._review_packets: List[ReviewPacket] = []

    @property
    def state(self) -> EmptinessState:
        """Current emptiness state."""
        return self._state

    @property
    def is_active(self) -> bool:
        """Check if Emptiness Window is active."""
        return self._state == EmptinessState.EMPTINESS

    def activate(self, reason: str = "Manual activation") -> None:
        """
        Activate Emptiness Window.

        This removes all commit power (Ω1/Ω2) while keeping
        cognition and audit alive.
        """
        if self._state == EmptinessState.NORMAL:
            self._state = EmptinessState.EMPTINESS
            self._activated_at = time.time()
            self._activation_reason = reason
            self._blocked_calls = []

    def deactivate(self, require_review: bool = True) -> Optional[ReviewPacket]:
        """
        Deactivate Emptiness Window and return to normal operation.

        If require_review=True and there are blocked calls,
        generates a review packet.
        """
        packet = None
        if self._state == EmptinessState.EMPTINESS:
            if require_review and self._blocked_calls:
                packet = self._generate_review_packet()

            self._state = EmptinessState.NORMAL
            self._activated_at = None
            self._activation_reason = ""
            self._blocked_calls = []

        return packet

    def check_allowed(self, omega_level: OmegaLevel) -> bool:
        """
        Check if an action at given Ω level is allowed.

        During Emptiness:
        - Ω0 (safe reads): allowed
        - Ω1/Ω2: blocked
        """
        if self._state == EmptinessState.NORMAL:
            return True

        # In Emptiness mode, only Ω0 is allowed
        return omega_level == OmegaLevel.OMEGA_0

    def record_blocked_call(self, tool_call: ToolCall) -> None:
        """Record a blocked tool call for later review."""
        if self._state == EmptinessState.EMPTINESS:
            self._blocked_calls.append(tool_call)

    def _generate_review_packet(self) -> ReviewPacket:
        """Generate a review packet from blocked calls."""
        import uuid
        packet = ReviewPacket(
            packet_id=str(uuid.uuid4()),
            timestamp=time.time(),
            blocked_calls=self._blocked_calls.copy(),
            recommendation=f"{len(self._blocked_calls)} action(s) blocked during Emptiness Window",
        )
        self._review_packets.append(packet)
        return packet

    def get_status(self) -> Dict[str, Any]:
        """Get current Emptiness Window status."""
        return {
            "state": self._state.name,
            "is_active": self.is_active,
            "activated_at": self._activated_at,
            "activation_reason": self._activation_reason,
            "blocked_calls_count": len(self._blocked_calls),
            "duration_seconds": (
                time.time() - self._activated_at
                if self._activated_at else None
            ),
        }

    def get_blocked_calls(self) -> List[ToolCall]:
        """Get list of blocked calls during current Emptiness window."""
        return self._blocked_calls.copy()

    def get_review_packets(self) -> List[ReviewPacket]:
        """Get all generated review packets."""
        return self._review_packets.copy()

    def add_dry_run_diff(self, diff: Dict[str, Any]) -> None:
        """Add a dry-run diff to current session (for review packet)."""
        # This would be populated during "what-if" planning
        pass

    def set_proposed_plan(self, plan: str) -> None:
        """Set the proposed plan text (for review packet)."""
        # This captures what the agent would do if allowed
        pass
