"""Tool for on-demand email checking via IMAP."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, Callable

from nanobot.agent.tools.base import Tool, ToolResult


class CheckEmailTool(Tool):
    """Fetch and summarise emails on demand.

    Uses a callback to reach the email channel so that ``agent/tools/``
    never imports from ``channels/`` directly.
    """

    readonly = True

    _MAX_BODY_PREVIEW = 500

    def __init__(
        self,
        fetch_callback: Callable[[date, date, int], list[dict[str, Any]]] | None = None,
        fetch_unread_callback: Callable[[int], list[dict[str, Any]]] | None = None,
    ):
        self._fetch = fetch_callback
        self._fetch_unread = fetch_unread_callback

    @property
    def name(self) -> str:
        return "check_email"

    @property
    def description(self) -> str:
        return (
            "Check and retrieve emails from the configured mailbox. "
            "Use period='unread' for new/unread messages, or specify a date "
            "range like 'today', 'yesterday', 'last_3_days', or explicit "
            "'start_date'/'end_date' (YYYY-MM-DD)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": (
                        "Shortcut period: 'unread', 'today', 'yesterday', "
                        "'last_3_days', 'last_7_days'. Default: 'unread'."
                    ),
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD). Overrides period.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD). Defaults to today+1.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of emails to return. Default: 20.",
                },
            },
            "required": [],
        }

    # ------------------------------------------------------------------

    async def execute(  # type: ignore[override]
        self,
        period: str = "unread",
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 20,
        **kwargs: Any,
    ) -> ToolResult:
        if not self._fetch and not self._fetch_unread:
            return ToolResult.fail(
                "Email channel is not configured or not available.",
                error_type="email_unavailable",
            )

        limit = max(1, min(limit, 100))

        # Explicit date range takes priority
        if start_date:
            return await self._fetch_by_dates(start_date, end_date, limit)

        # Named period shortcuts
        period = (period or "unread").strip().lower()
        if period == "unread":
            return await self._fetch_unread_emails(limit)

        today = date.today()
        if period == "today":
            return await self._fetch_by_date_range(today, today + timedelta(days=1), limit)
        if period == "yesterday":
            return await self._fetch_by_date_range(today - timedelta(days=1), today, limit)
        for prefix in ("last_", "last"):
            if period.startswith(prefix) and period.endswith("_days"):
                try:
                    n = int(period[len(prefix) :].removesuffix("_days"))
                except ValueError:
                    break
                return await self._fetch_by_date_range(
                    today - timedelta(days=n), today + timedelta(days=1), limit
                )
            if period.startswith(prefix) and period.rstrip("s").endswith("_day"):
                try:
                    n = int(period[len(prefix) :].split("_")[0])
                except ValueError:
                    break
                return await self._fetch_by_date_range(
                    today - timedelta(days=n), today + timedelta(days=1), limit
                )

        return ToolResult.fail(
            f"Unknown period '{period}'. Use 'unread', 'today', 'yesterday', "
            "'last_3_days', or provide explicit start_date/end_date.",
            error_type="invalid_parameter",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_unread_emails(self, limit: int) -> ToolResult:
        if not self._fetch_unread:
            # Fall back to today's date range
            today = date.today()
            return await self._fetch_by_date_range(today, today + timedelta(days=1), limit)

        messages = await asyncio.to_thread(self._fetch_unread, limit)
        return self._format_result(messages, "unread")

    async def _fetch_by_dates(self, start_str: str, end_str: str | None, limit: int) -> ToolResult:
        try:
            start = date.fromisoformat(start_str)
        except ValueError:
            return ToolResult.fail(
                f"Invalid start_date format: '{start_str}'. Use YYYY-MM-DD.",
                error_type="invalid_parameter",
            )
        if end_str:
            try:
                end = date.fromisoformat(end_str)
            except ValueError:
                return ToolResult.fail(
                    f"Invalid end_date format: '{end_str}'. Use YYYY-MM-DD.",
                    error_type="invalid_parameter",
                )
        else:
            end = date.today() + timedelta(days=1)

        return await self._fetch_by_date_range(start, end, limit)

    async def _fetch_by_date_range(self, start: date, end: date, limit: int) -> ToolResult:
        if not self._fetch:
            return ToolResult.fail(
                "Email date-range fetch is not available.",
                error_type="email_unavailable",
            )
        messages = await asyncio.to_thread(self._fetch, start, end, limit)
        label = f"{start.isoformat()} to {end.isoformat()}"
        return self._format_result(messages, label)

    def _format_result(self, messages: list[dict[str, Any]], label: str) -> ToolResult:
        if not messages:
            return ToolResult.ok(f"No emails found ({label}).")

        lines: list[str] = [f"Found {len(messages)} email(s) ({label}):\n"]
        for i, msg in enumerate(messages, 1):
            sender = msg.get("sender", "unknown")
            subject = msg.get("subject", "(no subject)")
            meta = msg.get("metadata", {})
            date_str = meta.get("date", "") if isinstance(meta, dict) else ""
            body = msg.get("content", "")
            if isinstance(body, str) and len(body) > self._MAX_BODY_PREVIEW:
                body = body[: self._MAX_BODY_PREVIEW] + "…"
            lines.append(f"--- Email {i} ---")
            lines.append(f"From: {sender}")
            lines.append(f"Subject: {subject}")
            if date_str:
                lines.append(f"Date: {date_str}")
            lines.append(f"Body: {body}")
            lines.append("")

        output = "\n".join(lines)
        truncated = len(messages) >= 20
        return ToolResult.ok(output, truncated=truncated)
