"""
FIT-Sec Runtime for Local Agents
================================

A security layer for AI agent runtimes implementing FIT safety principles.

Core primitives:
1. Ω taxonomy - classify tools by blast radius (Ω0/Ω1/Ω2)
2. Monitorability Gate - block execution when safety mechanisms aren't operational
3. Emptiness Window - remove commit power while preserving cognition

Usage:
    from fitsec import FitSecRuntime, ToolManifest, OmegaLevel, ToolCall

    # Create runtime
    runtime = FitSecRuntime()

    # Register a safe tool (Ω0)
    runtime.register_tool(
        ToolManifest(
            tool_id="file_read",
            omega_level=OmegaLevel.OMEGA_0,
            description="Read file contents",
        ),
        executor=my_file_reader,
    )

    # Execute through security layer
    result = runtime.execute(ToolCall(
        tool_id="file_read",
        action="read",
        args={"path": "/workspace/readme.md"},
    ))

    # Enter Emptiness mode (blocks Ω1/Ω2)
    runtime.enter_emptiness("Suspicious activity detected")

    # Check status
    print(runtime.get_status())
"""

__version__ = "0.3.0"

from .types import (
    OmegaLevel,
    Decision,
    GateStatus,
    EmptinessState,
    ToolManifest,
    ToolCall,
    GateMetrics,
    PolicyDecision,
    AuditEntry,
    FitSecError,
    ToolNotRegisteredError,
    PolicyDeniedError,
    GateFailedError,
    EmptinessActiveError,
)

from .runtime import FitSecRuntime, ToolRegistry
from .policy import PolicyEngine
from .gate import MonitorabilityGate, EmergencyGate
from .audit import AuditLogger
from .emptiness import EmptinessWindow, ReviewPacket

__all__ = [
    # Version
    "__version__",
    # Core types
    "OmegaLevel",
    "Decision",
    "GateStatus",
    "EmptinessState",
    "ToolManifest",
    "ToolCall",
    "GateMetrics",
    "PolicyDecision",
    "AuditEntry",
    "ReviewPacket",
    # Exceptions
    "FitSecError",
    "ToolNotRegisteredError",
    "PolicyDeniedError",
    "GateFailedError",
    "EmptinessActiveError",
    # Runtime
    "FitSecRuntime",
    "ToolRegistry",
    # Components
    "PolicyEngine",
    "MonitorabilityGate",
    "EmergencyGate",
    "AuditLogger",
    "EmptinessWindow",
]
