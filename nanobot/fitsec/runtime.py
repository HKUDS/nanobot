"""
FIT-Sec Runtime
===============
Main orchestrator for the FIT security layer.

Data flow:
1. Tool call proposed
2. Classify O level from manifest
3. Check Emptiness Window
4. Check Monitorability Gate
5. Evaluate Policy
6. Execute in sandbox OR block
7. Log to audit

Design constraints:
- Deterministic policy decisions
- No hidden tool execution
- Default deny for O2
- Safe failure: if uncertain → block and generate review packet
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .types import (
    Decision,
    EmptinessActiveError,
    FitSecError,
    GateFailedError,
    GateMetrics,
    GateStatus,
    OmegaLevel,
    PolicyDecision,
    PolicyDeniedError,
    ToolCall,
    ToolManifest,
    ToolNotRegisteredError,
)
from .policy import PolicyEngine
from .gate import MonitorabilityGate, EmergencyGate
from .audit import AuditLogger
from .emptiness import EmptinessWindow


class ToolRegistry:
    """Registry of declared tools with their manifests."""

    def __init__(self):
        self._tools: Dict[str, ToolManifest] = {}
        self._executors: Dict[str, Callable] = {}

    def register(
        self,
        manifest: ToolManifest,
        executor: Optional[Callable] = None,
    ) -> None:
        """Register a tool with its manifest and optional executor."""
        self._tools[manifest.tool_id] = manifest
        if executor:
            self._executors[manifest.tool_id] = executor

    def get_manifest(self, tool_id: str) -> Optional[ToolManifest]:
        """Get manifest for a tool."""
        return self._tools.get(tool_id)

    def get_executor(self, tool_id: str) -> Optional[Callable]:
        """Get executor function for a tool."""
        return self._executors.get(tool_id)

    def list_tools(self) -> Dict[str, ToolManifest]:
        """List all registered tools."""
        return self._tools.copy()


class FitSecRuntime:
    """
    Main FIT-Sec runtime orchestrator.

    Provides:
    - Tool registration with O classification
    - Policy-based execution control
    - Monitorability gate enforcement
    - Emptiness Window support
    - Complete audit logging
    """

    def __init__(
        self,
        policy_path: Optional[Path] = None,
        audit_path: Optional[Path] = None,
        strict_mode: bool = True,
    ):
        self.strict_mode = strict_mode

        # Components
        self.registry = ToolRegistry()
        self.policy = PolicyEngine(policy_path=policy_path)
        self.gate = MonitorabilityGate()
        self.emergency_gate = EmergencyGate()
        self.emptiness = EmptinessWindow()
        self.audit = AuditLogger(
            log_path=audit_path,
            in_memory=(audit_path is None),
        )

    def register_tool(
        self,
        manifest: ToolManifest,
        executor: Optional[Callable] = None,
    ) -> None:
        """Register a tool with manifest and optional executor."""
        self.registry.register(manifest, executor)

    def execute(
        self,
        tool_call: ToolCall,
        dry_run: bool = False,
    ) -> Any:
        """
        Execute a tool call through the security layer.

        Args:
            tool_call: The proposed tool invocation
            dry_run: If True, evaluate but don't execute

        Returns:
            Tool execution result

        Raises:
            ToolNotRegisteredError: Tool not in registry
            PolicyDeniedError: Policy denied the action
            GateFailedError: Monitorability gate failed
            EmptinessActiveError: Blocked by Emptiness Window
        """
        manifest = self.registry.get_manifest(tool_call.tool_id)

        # Step 1: Check manifest exists
        if manifest is None:
            decision = PolicyDecision(
                decision=Decision.DENY,
                omega_level=OmegaLevel.UNKNOWN,
                gate_status=GateStatus.UNKNOWN,
                rationale="Tool not registered",
            )
            self.audit.log(
                tool_call=tool_call,
                manifest=None,
                policy_decision=decision,
                executed=False,
                error="ToolNotRegisteredError",
            )
            raise ToolNotRegisteredError(f"Tool '{tool_call.tool_id}' not registered")

        omega = manifest.omega_level

        # Step 2: Check Emptiness Window
        if not self.emptiness.check_allowed(omega):
            self.emptiness.record_blocked_call(tool_call)
            decision = PolicyDecision(
                decision=Decision.DENY,
                omega_level=omega,
                gate_status=GateStatus.UNKNOWN,
                rationale="Blocked by Emptiness Window",
            )
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                error="EmptinessActiveError",
            )
            raise EmptinessActiveError(
                f"Action blocked: Emptiness Window active (O{omega.value})"
            )

        # Step 3: Check Emergency Gate
        if self.emergency_gate.is_active() and omega != OmegaLevel.OMEGA_0:
            decision = PolicyDecision(
                decision=Decision.DENY,
                omega_level=omega,
                gate_status=GateStatus.UNKNOWN,
                rationale=f"Emergency gate active: {self.emergency_gate.get_reason()}",
            )
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                error="EmergencyGateActive",
            )
            raise GateFailedError("Emergency gate is active")

        # Step 4: Check Monitorability Gate (for O1/O2)
        gate_status = GateStatus.PASS
        if omega in (OmegaLevel.OMEGA_1, OmegaLevel.OMEGA_2):
            gate_status = self.gate.check()
            if gate_status not in (GateStatus.PASS, GateStatus.UNKNOWN):
                if self.strict_mode:
                    decision = PolicyDecision(
                        decision=Decision.DENY,
                        omega_level=omega,
                        gate_status=gate_status,
                        rationale=f"Monitorability gate failed: {gate_status.name}",
                        metrics_snapshot=self.gate.get_metrics(),
                    )
                    self.audit.log(
                        tool_call=tool_call,
                        manifest=manifest,
                        policy_decision=decision,
                        executed=False,
                        error="GateFailedError",
                    )
                    raise GateFailedError(
                        self.gate.get_failure_reason() or gate_status.name
                    )

        # Step 5: Evaluate Policy
        decision = self.policy.evaluate(tool_call, manifest, gate_status)

        # Step 6: Handle decision
        if decision.decision == Decision.DENY:
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                error="PolicyDeniedError",
            )
            raise PolicyDeniedError(decision.rationale)

        if decision.decision == Decision.REVIEW:
            # Generate review packet
            self.emptiness.record_blocked_call(tool_call)
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                error="RequiresReview",
            )
            raise PolicyDeniedError(f"Requires human review: {decision.rationale}")

        # Step 7: Execute (if not dry run)
        if dry_run:
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                result="[DRY RUN]",
            )
            return {"dry_run": True, "would_execute": True}

        executor = self.registry.get_executor(tool_call.tool_id)
        if executor is None:
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                error="NoExecutor",
            )
            raise FitSecError(f"No executor registered for '{tool_call.tool_id}'")

        # Execute and log
        try:
            result = executor(tool_call.action, tool_call.args)
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=True,
                result=result,
            )
            return result
        except Exception as e:
            self.audit.log(
                tool_call=tool_call,
                manifest=manifest,
                policy_decision=decision,
                executed=True,
                error=str(e),
            )
            raise

    def enter_emptiness(self, reason: str = "Manual") -> None:
        """Enter Emptiness Window mode."""
        self.emptiness.activate(reason)

    def exit_emptiness(self) -> None:
        """Exit Emptiness Window mode."""
        self.emptiness.deactivate()

    def emergency_stop(self, reason: str = "Emergency stop") -> None:
        """Activate emergency gate (blocks all O1/O2)."""
        self.emergency_gate.activate(reason)

    def emergency_clear(self) -> None:
        """Clear emergency gate."""
        self.emergency_gate.deactivate()

    def get_status(self) -> Dict[str, Any]:
        """Get runtime status."""
        return {
            "emptiness": self.emptiness.get_status(),
            "emergency_active": self.emergency_gate.is_active(),
            "emergency_reason": self.emergency_gate.get_reason(),
            "registered_tools": len(self.registry.list_tools()),
            "audit_summary": self.audit.get_summary(),
        }
