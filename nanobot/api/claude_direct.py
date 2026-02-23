"""Direct Anthropic API client using OAuth token.

Used by the proxy server in OAuth mode to forward requests directly
to the Anthropic Messages API with Claude Code headers.
"""

from typing import Any

import httpx
from loguru import logger

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

CLAUDE_CODE_HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14",
}

CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."


def inject_system_prompt(body: dict[str, Any]) -> dict[str, Any]:
    """Ensure the required Claude Code system prompt is present."""
    system = body.get("system")

    if system is None:
        body["system"] = CLAUDE_CODE_SYSTEM_PREFIX
    elif isinstance(system, str):
        if CLAUDE_CODE_SYSTEM_PREFIX not in system:
            body["system"] = [
                {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX},
                {"type": "text", "text": system},
            ]
    elif isinstance(system, list):
        has_prefix = any(
            b.get("type") == "text" and CLAUDE_CODE_SYSTEM_PREFIX in b.get("text", "")
            for b in system
        )
        if not has_prefix:
            body["system"] = [
                {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX},
            ] + system

    return body


async def send_to_anthropic(
    body: dict[str, Any],
    token: str,
    stream: bool = False,
) -> httpx.Response:
    """Send a request to the Anthropic Messages API.

    For streaming requests, returns the response with stream open (caller must close).
    For non-streaming, returns the complete response.
    """
    body = inject_system_prompt(body)

    headers = {
        **CLAUDE_CODE_HEADERS,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if stream:
        body["stream"] = True
        client = httpx.AsyncClient(timeout=300)
        req = client.build_request("POST", ANTHROPIC_API_URL, json=body, headers=headers)
        resp = await client.send(req, stream=True)
        resp._client = client  # attach for cleanup
        return resp

    async with httpx.AsyncClient(timeout=300) as client:
        return await client.post(ANTHROPIC_API_URL, json=body, headers=headers)
