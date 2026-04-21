"""Tool registry for dynamic tool management."""

import time
from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.utils.sensitive import redact_if_sensitive


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._definitions_cache: list[dict[str, Any]] | None = None
        self._audit_logger = None
        self._session_id: str = ""
        self._channel: str = ""
        self._sender_id: str = ""

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        self._definitions_cache = None

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)
        self._definitions_cache = None

    def set_audit_logger(self, audit_logger) -> None:
        """Attach an AuditLogger to record all tool executions."""
        self._audit_logger = audit_logger

    def set_context(self, session_id: str, channel: str, sender_id: str = "") -> None:
        """Set session context for audit logging and access control."""
        self._session_id = session_id
        self._channel = channel
        self._sender_id = sender_id
        # Propagate sender to filesystem tools for protected-path checks
        from nanobot.agent.tools import filesystem as _fs
        _fs._current_sender_id = sender_id

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        """Extract a normalized tool name from either OpenAI or flat schemas."""
        fn = schema.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions with stable ordering for cache-friendly prompts.

        Built-in tools are sorted first as a stable prefix, then MCP tools are
        sorted and appended.  The result is cached until the next
        register/unregister call.
        """
        if self._definitions_cache is not None:
            return self._definitions_cache

        definitions = [tool.to_schema() for tool in self._tools.values()]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        self._definitions_cache = builtins + mcp_tools
        return self._definitions_cache

    async def execute(
        self,
        name: str,
        params: dict[str, Any],
        *,
        session_id: str | None = None,
        channel: str | None = None,
    ) -> str:
        """Execute a tool by name with given parameters.

        *session_id* and *channel* are per-call overrides for audit logging,
        avoiding shared mutable state across concurrent workers.
        """
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        # Guard against invalid parameter types (e.g., list instead of dict)
        if not isinstance(params, dict) and name in ('write_file', 'read_file'):
            return (
                f"Error: Tool '{name}' parameters must be a JSON object, got {type(params).__name__}. "
                "Use named parameters: tool_name(param1=\"value1\", param2=\"value2\")" + _HINT
            )

        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        sid = session_id or self._session_id
        ch = channel or self._channel

        t0 = time.monotonic()
        try:
            # Schema-driven cast (e.g. stringly-typed ints from LLM JSON) before
            # validation — regression restored from pre-1d18d24 prepare_call().
            params = tool.cast_params(params)
            errors = tool.validate_params(params)
            if errors:
                self._audit("error", name, params, t0, sid, ch, error="; ".join(errors))
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT
            result = await tool.execute(**params)
            duration_ms = (time.monotonic() - t0) * 1000
            status = "error" if isinstance(result, str) and result.startswith("Error") else "ok"
            self._audit(status, name, params, t0, sid, ch)
            self._prom_observe(name, status, duration_ms)
            # Defence-in-depth: scrub embedded secrets from any string result,
            # both success AND error paths (MIT-147).
            #
            # Tool authors can legitimately return error strings that embed the
            # offending payload for the model to reason about — e.g. "Error:
            # invalid AWS credentials: AKIA..." or "Error parsing PEM: -----BEGIN
            # RSA PRIVATE KEY-----...". Before MIT-147, the error branch was a
            # short-circuit that bypassed the redactor entirely, so anything a
            # (possibly adversarial) tool stuffed into an `Error:` prefix would
            # leak straight to the model.
            #
            # Error-prefix preservation: `AgentRunner._run_tool()` (and other
            # downstream consumers) detect tool failures via
            # `result.startswith("Error")`. The raw redaction notice does NOT
            # start with "Error", so on the error branch we re-wrap the
            # redacted result in an "Error: ..." shell to preserve the
            # failure-detection contract. The `_HINT` suffix is appended after
            # redaction so the model still gets the "try something else" nudge.
            #
            # Non-string results (e.g. ReadFileTool's image content blocks ->
            # list[dict]) bypass the scrubber and pass through untouched.
            if isinstance(result, str):
                redacted = redact_if_sensitive(result)
                if status == "error":
                    # Preserve the "Error:" prefix that downstream failure
                    # detection relies on, even when the body was scrubbed.
                    if not redacted.startswith("Error"):
                        redacted = f"Error ({name}): {redacted}"
                    result = redacted + _HINT
                else:
                    result = redacted
            return result
        except Exception as e:
            duration_ms = (time.monotonic() - t0) * 1000
            self._audit("error", name, params, t0, sid, ch, error=str(e))
            self._prom_observe(name, "error", duration_ms)
            # Exception strings can also carry secrets — e.g. a ValueError
            # raised while parsing a file embeds the line that failed. Run
            # the redactor on the exception path too (MIT-147).
            #
            # Preserve the "Error executing ..." prefix so downstream failure
            # detection keeps working when the exception message contained
            # a secret and got fully replaced by the redaction notice.
            raw = f"Error executing {name}: {str(e)}"
            redacted = redact_if_sensitive(raw)
            if not redacted.startswith("Error"):
                redacted = f"Error executing {name}: {redacted}"
            return redacted + _HINT

    def _audit(
        self,
        status: str,
        name: str,
        params: dict,
        t0: float,
        session_id: str = "",
        channel: str = "",
        error: str | None = None,
    ) -> None:
        """Log a tool execution to the audit logger if attached."""
        if self._audit_logger is None:
            return
        try:
            self._audit_logger.log(
                tool_name=name,
                arguments=params,
                result_status=status,
                session_id=session_id,
                channel=channel,
                error=error,
                duration_ms=(time.monotonic() - t0) * 1000,
            )
        except Exception:
            pass  # Audit must never crash tool execution

    @staticmethod
    def _prom_observe(tool_name: str, status: str, duration_ms: float) -> None:
        """Feed Prometheus metrics if available."""
        try:
            from nanobot.dashboard.server import _PROM_AVAILABLE
            if _PROM_AVAILABLE:
                from nanobot.dashboard.server import PROM_TOOL_CALLS, PROM_TOOL_DURATION
                PROM_TOOL_CALLS.labels(tool_name=tool_name, status=status).inc()
                PROM_TOOL_DURATION.labels(tool_name=tool_name).observe(duration_ms)
        except Exception:
            pass

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
