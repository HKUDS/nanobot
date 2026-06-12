"""Audit tool — records agent tool invocations for observability and attribution.

Config schema (tools.audit):
    enabled (bool):        Enable/disable audit recording. Default: False
    scope (list[str]):     Tool names to audit. ["*"] means all. Default: ["*"]
    transport (str):       Where to send audit events. One of:
                              "logger"  — loguru info-level logging (default)
                              "webhook" — HTTP POST to transport_url
                              "file"    — append JSON lines to transport_path
                              "custom"  — call transport_callback (programmatic only)
    transport_url (str):   URL for "webhook" transport.
    transport_path (str): File path for "file" transport.

Audit events are emitted after each tool call (success or error) when the tool
name matches the configured scope.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from nanobot.agent.tools.base import Tool


# ---------------------------------------------------------------------------
# Audit event model
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class AuditEvent:
    """Single audit record for a tool invocation."""

    tool: str
    action: str  # "call" | "error" | "blocked"
    params: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    detail: str = ""
    timestamp: float = field(default_factory=time.time)
    session: str = ""
    agent_id: str = ""
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "action": self.action,
            "params": self.params,
            "result_summary": self.result_summary,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "session": self.session,
            "agent_id": self.agent_id,
            "duration_ms": self.duration_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Transport layer
# ---------------------------------------------------------------------------

class AuditTransport:
    """Base class for audit event transports."""

    def send(self, event: AuditEvent) -> None:
        raise NotImplementedError


class LoggerTransport(AuditTransport):
    """Emit audit events via loguru at INFO level."""

    def send(self, event: AuditEvent) -> None:
        logger.info(
            "audit.{} | {} | {} | session:{} | agent:{} | duration:{}ms",
            event.action,
            event.tool,
            event.detail[:200] if event.detail else event.result_summary[:200],
            event.session,
            event.agent_id,
            f"{event.duration_ms:.1f}" if event.duration_ms is not None else "N/A",
        )


class WebhookTransport(AuditTransport):
    """POST audit events as JSON to a configurable URL."""

    def __init__(self, url: str) -> None:
        self._url = url

    def send(self, event: AuditEvent) -> None:
        import urllib.request

        payload = event.to_json().encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                logger.debug("audit webhook response: {}", resp.status)
        except Exception:
            logger.warning("audit webhook delivery failed for {}", self._url)


class FileTransport(AuditTransport):
    """Append audit events as JSON lines to a file."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def send(self, event: AuditEvent) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(event.to_json() + "\n")
        except Exception:
            logger.warning("audit file write failed for {}", self._path)


class CallbackTransport(AuditTransport):
    """Invoke a user-supplied async or sync callback for each event."""

    def __init__(self, callback: Callable[[AuditEvent], None]) -> None:
        self._callback = callback

    def send(self, event: AuditEvent) -> None:
        self._callback(event)


# ---------------------------------------------------------------------------
# Transport factory
# ---------------------------------------------------------------------------

_TRANSPORTS: dict[str, type[AuditTransport]] = {
    "logger": LoggerTransport,
    "webhook": WebhookTransport,
    "file": FileTransport,
}


def build_transport(cfg: "AuditToolConfig") -> AuditTransport:
    """Build the appropriate transport from config."""
    kind = cfg.transport
    if kind == "logger":
        return LoggerTransport()
    if kind == "webhook":
        if not cfg.transport_url:
            raise ValueError("tools.audit.transport_url is required when transport is 'webhook'")
        return WebhookTransport(cfg.transport_url)
    if kind == "file":
        if not cfg.transport_path:
            raise ValueError("tools.audit.transport_path is required when transport is 'file'")
        return FileTransport(cfg.transport_path)
    if kind == "custom":
        # Custom transport must be set programmatically via set_custom_transport()
        if _custom_transport is not None:
            return _custom_transport
        raise ValueError("tools.audit transport is 'custom' but no callback has been registered")
    raise ValueError(f"Unknown tools.audit transport: {kind!r}")


# Module-level custom transport (set programmatically for testing)
_custom_transport: AuditTransport | None = None


def set_custom_transport(transport: AuditTransport | None) -> None:
    """Register a custom transport programmatically (e.g., for tests)."""
    global _custom_transport
    _custom_transport = transport


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class AuditToolConfig(BaseSettings):
    """Configuration for the audit tool."""

    enabled: bool = False
    scope: list[str] = Field(default_factory=lambda: ["*"])
    transport: str = "logger"  # logger | webhook | file | custom
    transport_url: str = ""  # URL for webhook transport
    transport_path: str = ""  # File path for file transport

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> "AuditToolConfig":
        if self.transport == "webhook" and not self.transport_url:
            # Don't raise at construction — allow empty config that's later filled.
            # Validation happens at build_transport time.
            pass
        if self.transport == "file" and not self.transport_path:
            pass
        return self


# ---------------------------------------------------------------------------
# Audit tool
# ---------------------------------------------------------------------------

class AuditTool(Tool):
    """Audit tool — records agent tool invocations for observability.

    This tool is not invoked by the agent LLM. It is called programmatically
    by the agent runner after each tool call to emit audit events to the
    configured transport.
    """

    config_key = "audit"
    _scopes = {"core"}

    @property
    def name(self) -> str:  # noqa: D102
        return "audit"

    @property
    def description(self) -> str:  # noqa: D102
        return "Records agent tool invocations for observability and attribution."

    @property
    def parameters(self) -> dict[str, Any]:  # noqa: D102
        return {}

    def __init__(self, cfg: AuditToolConfig | None = None, **kwargs: Any) -> None:
        super().__init__()
        self._cfg = cfg or AuditToolConfig()
        self._transport: AuditTransport | None = None
        self._session: str = ""
        self._agent_id: str = ""

    # -- public API ---------------------------------------------------------

    def configure(
        self,
        cfg: AuditToolConfig,
        *,
        session: str = "",
        agent_id: str = "",
    ) -> None:
        """(Re)configure the audit tool at runtime."""
        self._cfg = cfg
        self._session = session
        self._agent_id = agent_id
        if cfg.enabled:
            self._transport = build_transport(cfg)
        else:
            self._transport = None

    def record(
        self,
        tool: str,
        action: str,
        *,
        params: dict[str, Any] | None = None,
        result_summary: str = "",
        detail: str = "",
        duration_ms: float | None = None,
    ) -> None:
        """Record an audit event if the tool is in scope and audit is enabled."""
        if not self._cfg.enabled:
            return
        if not self._in_scope(tool):
            return
        if self._transport is None:
            return
        event = AuditEvent(
            tool=tool,
            action=action,
            params=params or {},
            result_summary=result_summary[:200] if result_summary else "",
            detail=detail[:500] if detail else "",
            session=self._session,
            agent_id=self._agent_id,
            duration_ms=duration_ms,
        )
        try:
            self._transport.send(event)
        except Exception:
            logger.warning("audit transport failed for tool {}", tool)

    def _in_scope(self, tool_name: str) -> bool:
        scope = self._cfg.scope
        if not scope:
            return True  # empty scope means all
        if "*" in scope:
            return True
        return tool_name in scope

    # -- Tool interface (not LLM-callable) ----------------------------------

    @classmethod
    def definition(cls) -> dict[str, Any]:
        """Audit tool has no LLM-callable definition."""
        return {}

    async def execute(self, **kwargs: Any) -> str:
        """Not LLM-callable; use record() programmatically."""
        return "audit tool: use record() API, not LLM invocation"