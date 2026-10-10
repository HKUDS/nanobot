"""Tool that asks the user for credentials through a WebUI form mid-turn.

The agent emits a ``credential_request`` UI payload and suspends; the WebUI
renders a form whose values travel back over a dedicated ``credential_submit``
envelope that bypasses the chat transcript and the model context. Resolved
values are written to the Playwright MCP secrets file and the server is
restarted so the new keys are available to ``browser_fill_form``/``browser_type``
on the next call.
"""
# pyright: reportIncompatibleMethodOverride=false
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agent.tools.schema import (
    ArraySchema,
    BooleanSchema,
    IntegerSchema,
    ObjectSchema,
    StringSchema,
    tool_parameters_schema,
)
from nanobot.bus.events import OUTBOUND_META_AGENT_UI, OutboundMessage
from nanobot.webui.credential_prompts import (
    STATUS_CANCELLED,
    STATUS_SUBMITTED,
    CredentialField,
    credential_prompts,
)

_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_DEFAULT_TIMEOUT_SECONDS = 300
_MAX_TIMEOUT_SECONDS = 900
_MAX_VALUE_CHARS = 4096

_FIELD_SCHEMA = ObjectSchema(
    {
        "key": StringSchema(
            "Secret key name to store the value under, e.g. LINKEDIN_EMAIL. "
            "Uppercase letters, digits and underscores only."
        ),
        "label": StringSchema("Input label shown to the user."),
        "sensitive": BooleanSchema(
            description="Mask the input as a password field (default true).",
            default=True,
        ),
        "required": BooleanSchema(
            description="Whether the user must fill this field before submitting (default true).",
            default=True,
        ),
    },
    required=["key"],
)


@tool_parameters(
    tool_parameters_schema(
        service=StringSchema(
            "Service the credentials belong to, e.g. 'LinkedIn'. Shown as the form title.",
            min_length=1,
            max_length=80,
        ),
        fields=ArraySchema(
            _FIELD_SCHEMA,
            description=(
                "Credential fields to collect. Each field stores its value under "
                "the given key in the Playwright MCP secrets file; reference keys "
                "by name in browser_fill_form/browser_type afterwards."
            ),
            min_items=1,
            max_items=8,
        ),
        reason=StringSchema(
            "Short explanation shown to the user describing why these credentials are needed.",
            max_length=200,
        ),
        timeout_seconds=IntegerSchema(
            description=f"Seconds to wait for the user (default {_DEFAULT_TIMEOUT_SECONDS}).",
            minimum=10,
            maximum=_MAX_TIMEOUT_SECONDS,
        ),
        required=["service", "fields"],
    )
)
class RequestSecretTool(Tool):
    """Request user credentials via an interactive WebUI form."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        secrets_file: Path | None = None,
    ) -> None:
        self._send_callback = send_callback
        self._secrets_file = secrets_file

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.bus is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(
            send_callback=ctx.bus.publish_outbound if ctx.bus else None,
            secrets_file=_configured_secrets_file(ctx),
        )

    @property
    def name(self) -> str:
        return "request_secret"

    @property
    def description(self) -> str:
        return (
            "Ask the user for credentials through a secure form rendered in the "
            "WebUI chat. Use this instead of asking for credentials in plain "
            "chat text: submitted values bypass the conversation, are written to "
            "the local secrets file, and become available to the Playwright "
            "browser tools as secret key names. The tool blocks until the user "
            "submits, cancels, or the timeout expires."
        )

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(
        self,
        service: str,
        fields: Any = None,
        reason: str | None = None,
        timeout_seconds: int | None = None,
        **kwargs: Any,
    ) -> str:
        request_ctx = current_request_context()
        if request_ctx is None or request_ctx.channel != "websocket" or not request_ctx.chat_id:
            return ToolResult.error(
                "Error: request_secret is only available for WebUI conversations"
            )
        if self._send_callback is None:
            return ToolResult.error("Error: outbound messaging is not configured")
        if self._secrets_file is None:
            return ToolResult.error(
                "Error: no Playwright secrets file is configured"
            )

        parsed_fields = self._parse_fields(fields)
        if isinstance(parsed_fields, str):
            return ToolResult.error(parsed_fields)

        timeout = timeout_seconds or _DEFAULT_TIMEOUT_SECONDS
        timeout = max(10, min(timeout, _MAX_TIMEOUT_SECONDS))
        prompt = credential_prompts.open(
            request_ctx.chat_id,
            parsed_fields,
            timeout,
        )
        try:
            await self._send_callback(
                OutboundMessage(
                    channel=request_ctx.channel,
                    chat_id=request_ctx.chat_id,
                    content=f"Requesting {service} credentials via secure form.",
                    metadata={
                        **request_ctx.metadata,
                        OUTBOUND_META_AGENT_UI: {
                            "kind": "credential_request",
                            "data": {
                                "request_id": prompt.request_id,
                                "chat_id": request_ctx.chat_id,
                                "service": service,
                                "reason": reason or "",
                                "fields": [f.wire() for f in prompt.fields],
                                "expires_at": prompt.expires_at,
                            },
                        },
                    },
                )
            )
            result = await asyncio.wait_for(prompt.future, timeout)
        except asyncio.TimeoutError:
            return ToolResult.error(
                f"Error: credential request timed out after {timeout}s"
            )
        finally:
            credential_prompts.drop(prompt.request_id)

        status = result.get("status")
        if status != STATUS_SUBMITTED:
            if status == STATUS_CANCELLED:
                return "The user declined to provide the requested credentials."
            return ToolResult.error("Error: credential request was closed before submission")

        values = result.get("values")
        if not isinstance(values, dict):
            return ToolResult.error("Error: credential submission was malformed")
        typed_values = cast(dict[str, Any], values)
        try:
            await asyncio.to_thread(self._write_secrets, typed_values)
        except OSError as exc:
            return ToolResult.error(f"Error: could not store credentials: {exc}")

        stored_keys = sorted(str(k) for k in typed_values)
        reloaded = await self._restart_playwright_server()
        suffix = (
            " The Playwright browser server was reloaded and can now use these keys."
            if reloaded
            else ""
        )
        return (
            f"Stored {len(stored_keys)} credential(s) for {service}: "
            f"{', '.join(stored_keys)}.{suffix} "
            "Use the key names (not literal values) in browser_fill_form or "
            "browser_type to fill login forms."
        )

    def _parse_fields(
        self,
        fields: Any,
    ) -> list[CredentialField] | str:
        if not isinstance(fields, list) or not fields:
            return "Error: fields must be a non-empty list"
        parsed: list[CredentialField] = []
        seen: set[str] = set()
        for raw_entry in cast(list[Any], fields):
            if not isinstance(raw_entry, dict):
                return "Error: each field must be an object"
            entry = cast(dict[str, Any], raw_entry)
            key = str(entry.get("key", "")).strip().upper()
            if not _KEY_PATTERN.match(key):
                return (
                    f"Error: invalid secret key {key!r}; use uppercase letters, "
                    "digits and underscores"
                )
            if key in seen:
                return f"Error: duplicate secret key {key!r}"
            seen.add(key)
            label = str(entry.get("label") or key).strip()[:80]
            parsed.append(
                CredentialField(
                    key=key,
                    label=label or key,
                    sensitive=bool(entry.get("sensitive", True)),
                    required=bool(entry.get("required", True)),
                )
            )
        return parsed

    def _write_secrets(self, values: dict[str, Any]) -> None:
        """Merge submitted values into the dotenv secrets file (mode 0600)."""
        path = self._secrets_file
        assert path is not None
        cleaned: dict[str, str] = {}
        for key, raw in values.items():
            value = str(raw)
            if len(value) > _MAX_VALUE_CHARS:
                value = value[:_MAX_VALUE_CHARS]
            cleaned[key] = value

        lines: list[str] = []
        written: set[str] = set()
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    name = stripped.split("=", 1)[0].strip()
                    if name in cleaned:
                        lines.append(_dotenv_line(name, cleaned[name]))
                        written.add(name)
                        continue
                lines.append(line)
        for key, value in cleaned.items():
            if key not in written:
                lines.append(_dotenv_line(key, value))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)

    async def _restart_playwright_server(self) -> bool:
        """Reconnect the Playwright MCP server so it re-reads the secrets file."""
        try:
            from nanobot.agent.tools.mcp import get_active_mcp_provider

            provider = get_active_mcp_provider()
            if provider is None or "playwright" not in provider.configured_server_names:
                return False
            return await provider.restart_server("playwright")
        except Exception as exc:
            logger.warning("Playwright MCP restart after secret write failed: {}", exc)
            return False


def _configured_secrets_file(ctx: ToolContext) -> Path | None:
    """Resolve the dotenv file the Playwright MCP server loads secrets from."""
    server = ctx.config.mcp_servers.get("playwright")
    if server is not None:
        configured = server.env.get("PLAYWRIGHT_MCP_SECRETS_FILE", "")
        if configured:
            return Path(configured).expanduser()
    default = Path.home() / ".nanobot" / "mcp" / "playwright" / "secrets.env"
    return default


def _dotenv_line(key: str, value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r")
    return f'{key}="{escaped}"'
