"""Delivers approval results back into nanobot sessions via MessageBus.

When an approval resolves, this formats a user-friendly message and
publishes it as an InboundMessage so the agent sees it on its next turn.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .types import ApprovalResult, PendingApproval

logger = logging.getLogger(__name__)


def format_approval_message(result: ApprovalResult, approval: PendingApproval) -> str:
    """Format a human-readable message about the approval outcome."""
    method = approval.original_payload.get("method", "?")
    url = approval.original_payload.get("url", "?")
    short_url = url.split("?")[0] if url else "?"

    if result.status == "approved":
        if result.error:
            return (
                f"[AgentHiFive] Your request was approved but replay failed: {result.error}\n"
                f"Original request: {method} {short_url}"
            )
        exec_result = result.execution_result or {}
        if exec_result.get("path"):
            return (
                f"[AgentHiFive] Your download was approved and saved successfully.\n"
                f"Request: {method} {short_url}\n"
                f"Saved to: {exec_result.get('path')}\n"
                f"Size: {exec_result.get('sizeBytes', 'unknown')} bytes"
            )
        status_code = exec_result.get("status", "unknown")
        if isinstance(status_code, int) and 200 <= status_code < 300:
            body_preview = json.dumps(exec_result.get("body", {}))[:500]
            return (
                f"[AgentHiFive] Your request was approved and executed successfully.\n"
                f"Request: {method} {short_url}\n"
                f"Response status: {status_code}\n"
                f"Response: {body_preview}"
            )
        else:
            return (
                f"[AgentHiFive] Your request was approved and sent to the provider, "
                f"but the provider returned status {status_code}.\n"
                f"Request: {method} {short_url}\n"
                f"Response: {json.dumps(exec_result.get('body', {}))[:500]}"
            )
    elif result.status == "denied":
        return (
            f"[AgentHiFive] Your request was denied by the workspace owner.\n"
            f"Request: {method} {short_url}"
        )
    elif result.status == "expired":
        return (
            f"[AgentHiFive] Your approval request expired before it was reviewed.\n"
            f"Request: {method} {short_url}"
        )
    else:
        return f"[AgentHiFive] Approval {result.approval_request_id} resolved with status: {result.status}"


class ResultInjector:
    """Injects approval results into nanobot sessions via MessageBus."""

    def __init__(self, bus: Any):
        """bus: nanobot.bus.queue.MessageBus instance."""
        self._bus = bus

    async def deliver(self, result: ApprovalResult, approval: PendingApproval) -> None:
        """Format and inject the approval result into the originating session."""
        message_text = format_approval_message(result, approval)
        logger.info(
            "Delivering approval result: %s status=%s channel=%s chat=%s",
            result.approval_request_id,
            result.status,
            approval.channel,
            approval.chat_id,
        )

        from nanobot.bus.events import InboundMessage

        msg = InboundMessage(
            channel=approval.channel or "system",
            sender_id=approval.sender_id or "agenthifive",
            chat_id=approval.chat_id or "default",
            content=message_text,
        )
        await self._bus.publish_inbound(msg)
