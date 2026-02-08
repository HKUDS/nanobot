"""
FIT-Sec Runtime Type Definitions
================================
Core types for the FIT security layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional
import time


class OmegaLevel(Enum):
    """Blast radius classification for tool actions.

    Ω0: Safe/reversible - pure read, local compute, no network writes
    Ω1: Medium risk - network requests, workspace writes, send messages
    Ω2: High risk/irreversible - shell exec, credentials, deploy, privilege changes
    """
    OMEGA_0 = 0  # Safe
    OMEGA_1 = 1  # Medium
    OMEGA_2 = 2  # High/Irreversible
    UNKNOWN = 99  # Unclassified (treated as Ω2)


class Decision(Enum):
    """Policy decision outcomes."""
    ALLOW = auto()
    DENY = auto()
    REVIEW = auto()  # Requires human review


class GateStatus(Enum):
    """Monitorability gate status."""
    PASS = auto()
    FAIL_FPR = auto()         # FPR not controllable
    FAIL_COVERAGE = auto()    # Coverage too low at target FPR
    FAIL_CALIBRATION = auto() # Probability outputs degenerate
    FAIL_LEAD_TIME = auto()   # Alert timing unstable
    UNKNOWN = auto()          # No metrics available


class EmptinessState(Enum):
    """Emptiness Window state."""
    NORMAL = auto()      # Full execution power
    EMPTINESS = auto()   # Cognition only, no commit power


@dataclass
class ToolManifest:
    """Declared capabilities and constraints for a tool."""
    tool_id: str
    omega_level: OmegaLevel
    description: str
    capabilities: List[str] = field(default_factory=list)
    network_domains: List[str] = field(default_factory=list)  # Allowed egress
    fs_paths: List[str] = field(default_factory=list)  # Allowed FS access
    requires_approval: bool = False
    hash_sha256: Optional[str] = None  # For supply chain verification

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "omega_level": self.omega_level.name,
            "description": self.description,
            "capabilities": self.capabilities,
            "network_domains": self.network_domains,
            "fs_paths": self.fs_paths,
            "requires_approval": self.requires_approval,
            "hash_sha256": self.hash_sha256,
        }


@dataclass
class ToolCall:
    """A proposed tool invocation."""
    tool_id: str
    action: str
    args: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class GateMetrics:
    """Operational usability metrics for the monitorability gate."""
    fpr: Optional[float] = None           # False positive rate
    fpr_target: float = 0.05              # Target FPR ceiling
    coverage_at_fpr: Optional[float] = None
    coverage_target: float = 0.80         # Minimum coverage at target FPR
    calibration_score: Optional[float] = None
    calibration_threshold: float = 0.7    # Minimum calibration quality
    lead_time_mean: Optional[float] = None
    lead_time_std: Optional[float] = None
    lead_time_cv_max: float = 0.5         # Max coefficient of variation


@dataclass
class PolicyDecision:
    """Result of a policy evaluation."""
    decision: Decision
    omega_level: OmegaLevel
    gate_status: GateStatus
    rationale: str
    metrics_snapshot: Optional[GateMetrics] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.name,
            "omega_level": self.omega_level.name,
            "gate_status": self.gate_status.name,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
        }


@dataclass
class AuditEntry:
    """Audit log entry for a tool call decision."""
    entry_id: str
    tool_call: ToolCall
    manifest: Optional[ToolManifest]
    policy_decision: PolicyDecision
    executed: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class FitSecError(Exception):
    """Base exception for FIT-Sec runtime errors."""
    pass


class ToolNotRegisteredError(FitSecError):
    """Tool not found in registry."""
    pass


class PolicyDeniedError(FitSecError):
    """Action denied by policy."""
    pass


class GateFailedError(FitSecError):
    """Monitorability gate check failed."""
    pass


class EmptinessActiveError(FitSecError):
    """Action blocked due to Emptiness Window."""
    pass
