"""Secure Tool Registry (optional middleware).

This module provides an opt-in wrapper around nanoBot's `ToolRegistry` that
routes tool execution through the FIT-Sec runtime:

- Omega taxonomy (O0/O1/O2)
- Monitorability gate checks
- Emptiness Window blocking
- Policy decisions + audit logging

Important: This file is *not* wired into the default agent loop in PR2.
It is intended to be used by an opt-in secure loop in a later PR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.fitsec import (
    Decision,
    EmptinessActiveError,
    FitSecRuntime,
    GateFailedError,
    GateStatus,
    OmegaLevel,
    PolicyDeniedError,
    ToolCall,
    ToolManifest,
    ToolNotRegisteredError,
)


DEFAULT_OMEGA_MAPPINGS: dict[str, OmegaLevel] = {
    # O0 - safe, read-only operations
    "read_file": OmegaLevel.OMEGA_0,
    "list_dir": OmegaLevel.OMEGA_0,
    "web_search": OmegaLevel.OMEGA_0,
    "web_fetch": OmegaLevel.OMEGA_0,
    "message": OmegaLevel.OMEGA_0,
    # O1 - reversible writes
    "write_file": OmegaLevel.OMEGA_1,
    "edit_file": OmegaLevel.OMEGA_1,
    # O2 - irreversible / high-impact operations
    "exec": OmegaLevel.OMEGA_2,
    "spawn": OmegaLevel.OMEGA_2,
    "cron": OmegaLevel.OMEGA_2,
}


class SecureToolRegistry:
    """Opt-in tool registry wrapper with FIT-Sec checks and audit."""

    def __init__(
        self,
        *,
        strict_mode: bool = True,
        omega_mappings: dict[str, OmegaLevel] | None = None,
        audit_path: Path | None = None,
    ) -> None:
        self._registry = ToolRegistry()
        self._runtime = FitSecRuntime(
            strict_mode=strict_mode,
            audit_path=audit_path,
        )
        self._omega_mappings = {**DEFAULT_OMEGA_MAPPINGS, **(omega_mappings or {})}

    def register(self, tool: Tool, omega_level: OmegaLevel | None = None) -> None:
        """Register a tool in both the nanoBot registry and FIT-Sec manifest registry."""
        self._registry.register(tool)

        level = omega_level or self._omega_mappings.get(tool.name, OmegaLevel.OMEGA_1)
        manifest = ToolManifest(
            tool_id=tool.name,
            omega_level=level,
            description=tool.description,
            requires_approval=(level == OmegaLevel.OMEGA_2),
        )

        # Manifest registration only (FIT-Sec runtime execution is evaluated in `execute`).
        self._runtime.register_tool(manifest, executor=None)

    def unregister(self, name: str) -> None:
        self._registry.unregister(name)
        # FIT-Sec runtime keeps manifests for auditability; no unregister.

    def get(self, name: str) -> Tool | None:
        return self._registry.get(name)

    def has(self, name: str) -> bool:
        return self._registry.has(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        return self._registry.get_definitions()

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """Execute with FIT-Sec checks; raises on deny/block/fail."""
        call = ToolCall(tool_id=name, action="execute", args=params)
        manifest = self._runtime.registry.get_manifest(name)

        if manifest is None:
            # Keep semantics explicit; callers can catch and surface.
            raise ToolNotRegisteredError(f"Tool '{name}' not registered (no manifest)")

        omega = manifest.omega_level

        # Emptiness Window (O0 is allowed; others depend on emptiness config)
        if not self._runtime.emptiness.check_allowed(omega):
            self._runtime.emptiness.record_blocked_call(call)
            self._runtime.audit.log(
                tool_call=call,
                manifest=manifest,
                policy_decision=self._runtime.policy.evaluate(call, manifest, GateStatus.UNKNOWN),
                executed=False,
                error="EmptinessActiveError",
            )
            raise EmptinessActiveError("Blocked by Emptiness Window")

        gate_status = GateStatus.PASS
        if omega in (OmegaLevel.OMEGA_1, OmegaLevel.OMEGA_2):
            gate_status = self._runtime.gate.check()
            if gate_status not in (GateStatus.PASS, GateStatus.UNKNOWN) and self._runtime.strict_mode:
                decision = self._runtime.policy.evaluate(call, manifest, gate_status)
                self._runtime.audit.log(
                    tool_call=call,
                    manifest=manifest,
                    policy_decision=decision,
                    executed=False,
                    error="GateFailedError",
                )
                raise GateFailedError(self._runtime.gate.get_failure_reason() or gate_status.name)

        decision = self._runtime.policy.evaluate(call, manifest, gate_status)
        if decision.decision != Decision.ALLOW:
            self._runtime.audit.log(
                tool_call=call,
                manifest=manifest,
                policy_decision=decision,
                executed=False,
                error="PolicyDeniedError" if decision.decision == Decision.DENY else "RequiresReview",
            )
            raise PolicyDeniedError(decision.rationale)

        result = await self._registry.execute(name, params)
        self._runtime.audit.log(
            tool_call=call,
            manifest=manifest,
            policy_decision=decision,
            executed=True,
            result=result,
        )
        return result

    @property
    def runtime(self) -> FitSecRuntime:
        """Access FIT-Sec runtime (policy/gate/emptiness/audit)."""
        return self._runtime

