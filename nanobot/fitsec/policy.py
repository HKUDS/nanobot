"""
FIT-Sec Policy Engine
=====================
Static policy rules for tool execution authorization.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .types import (
    Decision,
    OmegaLevel,
    PolicyDecision,
    GateStatus,
    ToolCall,
    ToolManifest,
)


class PolicyEngine:
    """
    Evaluates tool calls against security policy.

    Default policy:
    - O0: ALLOW
    - O1: ALLOW if audit enabled
    - O2: DENY unless explicitly granted in approval window
    """

    def __init__(
        self,
        policy_path: Optional[Path] = None,
        default_omega2_deny: bool = True,
    ):
        self.default_omega2_deny = default_omega2_deny
        self._grants: Dict[str, Set[str]] = {}  # tool_id -> allowed actions
        self._omega2_approvals: Dict[str, float] = {}  # tool_id -> expiry timestamp
        self._blocked_tools: Set[str] = set()
        self._allowed_network_domains: Set[str] = set()

        if policy_path and policy_path.exists():
            self._load_policy(policy_path)

    def _load_policy(self, path: Path) -> None:
        """Load policy from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Load grants
        for tool_id, actions in data.get("grants", {}).items():
            self._grants[tool_id] = set(actions)

        # Load blocked tools
        self._blocked_tools = set(data.get("blocked_tools", []))

        # Load network allowlist
        self._allowed_network_domains = set(data.get("allowed_network_domains", []))

    def evaluate(
        self,
        tool_call: ToolCall,
        manifest: Optional[ToolManifest],
        gate_status: GateStatus = GateStatus.UNKNOWN,
    ) -> PolicyDecision:
        """
        Evaluate a tool call against policy.

        Returns PolicyDecision with ALLOW/DENY/REVIEW.
        """
        import time

        # No manifest = unknown tool = deny
        if manifest is None:
            return PolicyDecision(
                decision=Decision.DENY,
                omega_level=OmegaLevel.UNKNOWN,
                gate_status=gate_status,
                rationale="Tool not registered (no manifest)",
            )

        omega = manifest.omega_level

        # Blocked tool check
        if tool_call.tool_id in self._blocked_tools:
            return PolicyDecision(
                decision=Decision.DENY,
                omega_level=omega,
                gate_status=gate_status,
                rationale=f"Tool '{tool_call.tool_id}' is blocked by policy",
            )

        # O0: safe, always allow
        if omega == OmegaLevel.OMEGA_0:
            return PolicyDecision(
                decision=Decision.ALLOW,
                omega_level=omega,
                gate_status=gate_status,
                rationale="O0 (safe) - allowed by default",
            )

        # O1: allow if gate passes
        if omega == OmegaLevel.OMEGA_1:
            if gate_status in (GateStatus.PASS, GateStatus.UNKNOWN):
                return PolicyDecision(
                    decision=Decision.ALLOW,
                    omega_level=omega,
                    gate_status=gate_status,
                    rationale="O1 (medium risk) - allowed with audit",
                )
            else:
                return PolicyDecision(
                    decision=Decision.DENY,
                    omega_level=omega,
                    gate_status=gate_status,
                    rationale=f"O1 blocked: gate failed ({gate_status.name})",
                )

        # O2: deny by default, require explicit approval
        if omega == OmegaLevel.OMEGA_2:
            # Check for time-bounded approval
            if tool_call.tool_id in self._omega2_approvals:
                expiry = self._omega2_approvals[tool_call.tool_id]
                if time.time() < expiry:
                    return PolicyDecision(
                        decision=Decision.ALLOW,
                        omega_level=omega,
                        gate_status=gate_status,
                        rationale="O2 - explicitly approved (time-bounded)",
                    )
                else:
                    del self._omega2_approvals[tool_call.tool_id]

            # Check grant list
            if tool_call.tool_id in self._grants:
                allowed_actions = self._grants[tool_call.tool_id]
                if "*" in allowed_actions or tool_call.action in allowed_actions:
                    return PolicyDecision(
                        decision=Decision.ALLOW,
                        omega_level=omega,
                        gate_status=gate_status,
                        rationale="O2 - granted by policy",
                    )

            # Default deny
            if self.default_omega2_deny:
                return PolicyDecision(
                    decision=Decision.DENY,
                    omega_level=omega,
                    gate_status=gate_status,
                    rationale="O2 (high risk) - denied by default, requires approval",
                )
            else:
                return PolicyDecision(
                    decision=Decision.REVIEW,
                    omega_level=omega,
                    gate_status=gate_status,
                    rationale="O2 (high risk) - requires human review",
                )

        # Unknown omega level = treat as O2
        return PolicyDecision(
            decision=Decision.DENY,
            omega_level=omega,
            gate_status=gate_status,
            rationale="Unknown O level - denied for safety",
        )

    def grant_omega2_approval(
        self,
        tool_id: str,
        duration_seconds: float = 300.0,  # 5 minute default
    ) -> None:
        """Grant time-bounded approval for an O2 tool."""
        import time
        self._omega2_approvals[tool_id] = time.time() + duration_seconds

    def revoke_omega2_approval(self, tool_id: str) -> None:
        """Revoke O2 approval for a tool."""
        self._omega2_approvals.pop(tool_id, None)

    def block_tool(self, tool_id: str) -> None:
        """Add tool to blocklist."""
        self._blocked_tools.add(tool_id)

    def unblock_tool(self, tool_id: str) -> None:
        """Remove tool from blocklist."""
        self._blocked_tools.discard(tool_id)

    def add_network_domain(self, domain: str) -> None:
        """Add domain to network egress allowlist."""
        self._allowed_network_domains.add(domain)

    def check_network_domain(self, domain: str) -> bool:
        """Check if domain is in network allowlist."""
        if not self._allowed_network_domains:
            return True  # No restrictions if empty
        return domain in self._allowed_network_domains

    def export_policy(self) -> Dict[str, Any]:
        """Export current policy state."""
        return {
            "grants": {k: list(v) for k, v in self._grants.items()},
            "blocked_tools": list(self._blocked_tools),
            "allowed_network_domains": list(self._allowed_network_domains),
            "omega2_approvals": {
                k: v for k, v in self._omega2_approvals.items()
            },
        }
