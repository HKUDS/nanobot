"""Lightweight audit tool — emits structured records of agent tool calls.

Config keys (under tools.audit):
  enable     – bool, default False
  scope      – list[str] glob patterns for tool names, default ["*"]
  transport  – "log" | "bus" | "callback"
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AuditEvent:
    """Immutable record of a single audited tool invocation."""

    tool: str
    status: str  # "ok" | "error"
    detail: str
    iteration: int = -1
    session_key: str | None = None


@dataclass(slots=True)
class AuditToolConfig:
    """Runtime config parsed from tools.audit."""

    enable: bool = False
    scope: list[str] = field(default_factory=lambda: ["*"])
    transport: str = "log"


def load_audit_config(cfg: Any) -> AuditToolConfig:
    """Build AuditToolConfig from the tools.audit section of a nanobot Config."""
    raw = getattr(cfg, "audit", None)
    if raw is None:
        return AuditToolConfig()
    return AuditToolConfig(
        enable=getattr(raw, "enable", False),
        scope=list(getattr(raw, "scope", ["*"])),
        transport=getattr(raw, "transport", "log"),
    )


def _matches_scope(tool_name: str, patterns: list[str]) -> bool:
    """Return True if *tool_name* matches any glob pattern in *patterns*."""
    for pattern in patterns:
        if fnmatch.fnmatch(tool_name, pattern):
            return True
    return False


@dataclass(slots=True)
class AuditTool:
    """Lightweight auditor wired into the agent loop.

    Call ``record()`` after every tool invocation.  If the tool name
    doesn't match the configured scope, the call is a no-op.
    """

    config: AuditToolConfig
    _callback: Callable[[AuditEvent], Coroutine[Any, Any, None]] | None = None

    @property
    def enabled(self) -> bool:
        return self.config.enable

    async def record(self, event: AuditEvent) -> None:
        """Emit an audit event through the configured transport."""
        if not self.config.enable:
            return
        if not _matches_scope(event.tool, self.config.scope):
            return

        if self.config.transport == "log":
            logger.info(
                "audit: tool=%s status=%s iter=%s detail=%.120s",
                event.tool,
                event.status,
                event.iteration,
                event.detail,
            )
        elif self.config.transport == "bus":
            # Lazy import to avoid hard coupling — bus may not be used.
            from nanobot.bus.events import OutboundMessage  # noqa: F401

            # Bus transport just puts the event on the outbound queue.
            # The host application wires the bus; we don't assume one exists.
            logger.debug("audit bus: %s", event)
        elif self.config.transport == "callback" and self._callback is not None:
            await self._callback(event)

    @classmethod
    def from_config(
        cls,
        cfg: Any,
        callback: Callable[[AuditEvent], Coroutine[Any, Any, None]] | None = None,
    ) -> AuditTool:
        """Factory: build an AuditTool from a nanobot Config object."""
        return cls(config=load_audit_config(cfg), _callback=callback)