"""Direct Anthropic API client using Claude Code OAuth token.

When the user authenticates via Claude Code CLI (browser OAuth), the token
must be sent with specific headers that identify the request as coming from
Claude Code. This module handles that direct path, bypassing litellm.
"""

import json
from typing import Any, AsyncIterator

import httpx
from loguru import logger

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# These headers tell the Anthropic API to accept the OAuth token
CLAUDE_CODE_HEADERS = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,interleaved-thinking-2025-05-14",
}

CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."


def is_oauth_token(token: str) -> bool:
    """Check if a token is a Claude Code OAuth token (vs regular API key)."""
    return token.startswith("sk-ant-oat")


def _inject_system_prompt(body: dict[str, Any]) -> dict[str, Any]:
    """Ensure the required Claude Code system prompt is present."""
    system = body.get("system")

    if system is None:
        body["system"] = CLAUDE_CODE_SYSTEM_PREFIX
    elif isinstance(system, str):
        if CLAUDE_CODE_SYSTEM_PREFIX not in system:
            # OAuth tokens require the prefix as a separate content block
            body["system"] = [
                {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX},
                {"type": "text", "text": system},
            ]
    elif isinstance(system, list):
        # Array of content blocks — prepend as first block
        has_prefix = any(
            b.get("type") == "text" and CLAUDE_CODE_SYSTEM_PREFIX in b.get("text", "")
            for b in system
        )
        if not has_prefix:
            body["system"] = [
                {"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX}
            ] + system

    return body


async def anthropic_direct_request(
    token: str, body: dict[str, Any]
) -> httpx.Response:
    """Send a non-streaming request directly to the Anthropic API."""
    body = _inject_system_prompt(body)
    body.pop("stream", None)

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                **CLAUDE_CODE_HEADERS,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    return response


async def anthropic_direct_stream(
    token: str, body: dict[str, Any]
) -> AsyncIterator[str]:
    """Send a streaming request directly to the Anthropic API, yielding raw SSE lines.

    The Anthropic API already returns proper SSE events in Anthropic format,
    so we just pass them through as-is — no format conversion needed.
    """
    body = _inject_system_prompt(body)
    body["stream"] = True

    async with httpx.AsyncClient(timeout=300) as client:
        async with client.stream(
            "POST",
            ANTHROPIC_API_URL,
            headers={
                **CLAUDE_CODE_HEADERS,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                raise Exception(
                    f"Anthropic API error {response.status_code}: {error_body.decode()}"
                )
            async for line in response.aiter_lines():
                if line:
                    yield line + "\n"
                else:
                    yield "\n"
