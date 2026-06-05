"""Resend email tool for nanobot.

Sends transactional emails via Resend API using the verified
thefoolishbutcher.com domain. Sets Reply-To to the AgentMail
support inbox so customer replies land where Frank can read them.

Tool exposed:
  resend_send — send a transactional email (shipping updates, order info, etc.)
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters

_API_URL = "https://api.resend.com/emails"
_DEFAULT_FROM = "The Foolish Butcher <ordini@updates.thefoolishbutcher.com>"
_DEFAULT_REPLY_TO = "support.foolish@agentmail.to"


def _api_key() -> str:
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        raise ValueError("RESEND_API_KEY not set")
    return key


@tool_parameters({
    "type": "object",
    "properties": {
        "to": {
            "type": "string",
            "description": "Recipient email address.",
        },
        "subject": {
            "type": "string",
            "description": "Email subject line.",
        },
        "html": {
            "type": "string",
            "description": "HTML body. Use this for rich formatting (preferred).",
        },
        "text": {
            "type": "string",
            "description": "Plain-text body. Used as fallback when html is not provided.",
        },
        "reply_to": {
            "type": "string",
            "description": (
                "Reply-To address. Defaults to support.foolish@agentmail.to so customer "
                "replies land in the AgentMail inbox Frank monitors. Override only if needed."
            ),
        },
        "from_address": {
            "type": "string",
            "description": (
                "Sender address. Defaults to "
                "'The Foolish Butcher <ordini@updates.thefoolishbutcher.com>'. "
                "Must use a Resend-verified domain. Do not change unless instructed."
            ),
        },
    },
    "required": ["to", "subject"],
})
class ResendSendTool(Tool):
    """Send a transactional email via Resend with the verified Foolish Butcher domain.

    Use this for all outbound customer emails: shipping updates, order confirmations,
    tracking notifications, etc. Customer replies will go to the AgentMail support
    inbox where Frank can read and respond to them.

    Always show the user the email content before sending.
    """

    name = "resend_send"
    description = (
        "Send a transactional email to a customer via Resend "
        "(from: ordini@updates.thefoolishbutcher.com, reply-to: AgentMail support inbox). "
        "Use for shipping updates and order-related notifications. "
        "Always show the email content to the user before sending."
    )
    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return bool(os.environ.get("RESEND_API_KEY"))

    @classmethod
    def create(cls, ctx: Any) -> "ResendSendTool":
        return cls()

    async def execute(
        self,
        to: str,
        subject: str,
        html: str = "",
        text: str = "",
        reply_to: str = "",
        from_address: str = "",
    ) -> str:
        if not html and not text:
            return "Provide at least 'html' or 'text' for the email body."

        try:
            api_key = _api_key()
        except ValueError as e:
            return str(e)

        sender = from_address.strip() or _DEFAULT_FROM
        reply = reply_to.strip() or _DEFAULT_REPLY_TO

        payload: dict[str, Any] = {
            "from": sender,
            "to": [to],
            "subject": subject,
            "reply_to": reply,
        }
        if html:
            payload["html"] = html
        if text:
            payload["text"] = text

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                _API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.status_code >= 400:
                return f"Resend error {resp.status_code}: {resp.text}"
            data = resp.json() if resp.content else {}

        msg_id = data.get("id") or "sent"
        logger.info("Resend email sent → {} | {} | id={}", to, subject, msg_id)

        return (
            f"## Email inviata ✓\n"
            f"- **Da**: {sender}\n"
            f"- **A**: {to}\n"
            f"- **Oggetto**: {subject}\n"
            f"- **Reply-To**: {reply}\n"
            f"- **ID**: `{msg_id}`"
        )
