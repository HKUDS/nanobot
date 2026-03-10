"""Endpoint rotation pool — wraps multiple LLMProvider instances with failover.

Usage:
    pool = EndpointPool([provider_a, provider_b])
    resp = await pool.chat_with_retry(messages=...)

When an endpoint fails with a transient error, the pool marks it on cooldown
and tries the next one.  If all endpoints are on cooldown the least-recently-
failed one is used as a last resort.

This class implements the LLMProvider interface so callers (agent loop, etc.)
need zero changes.

Configuration
=============

Add an ``endpoints`` list to any provider in ``~/.nanobot/config.json``.
Without ``endpoints`` the provider works exactly as before (single endpoint).

Basic — multiple API keys for the same provider::

    {
      "providers": {
        "openrouter": {
          "apiKey": "sk-or-default",
          "endpoints": [
            { "apiKey": "sk-or-key-1", "priority": 0 },
            { "apiKey": "sk-or-key-2", "priority": 1 }
          ]
        }
      }
    }

Degradation — primary model falls back to a cheaper one::

    {
      "providers": {
        "openrouter": {
          "apiKey": "sk-or-xxx",
          "endpoints": [
            { "apiKey": "sk-or-key-1", "model": "anthropic/claude-sonnet-4-5", "priority": 0 },
            { "apiKey": "sk-or-key-2", "model": "anthropic/claude-haiku-3.5",  "priority": 1, "cooldownSeconds": 120 }
          ]
        }
      }
    }

Multiple base URLs (e.g. local GPU servers)::

    {
      "providers": {
        "custom": {
          "apiKey": "no-key",
          "apiBase": "http://localhost:8000/v1",
          "endpoints": [
            { "apiBase": "http://gpu-server-1:8000/v1", "priority": 0 },
            { "apiBase": "http://gpu-server-2:8000/v1", "priority": 1 }
          ]
        }
      }
    }

Endpoint fields (all optional, inherit from the outer provider if omitted):

=================  ======  ===========  ==========================================
Field              Type    Default      Description
=================  ======  ===========  ==========================================
apiKey             str     outer value  API key for this endpoint
apiBase            str     outer value  Base URL for this endpoint
model              str     global model Model override for this endpoint
extraHeaders       dict    outer value  Custom HTTP headers
priority           int     0            Lower = tried first
cooldownSeconds    float   60.0         Seconds to skip endpoint after failure
=================  ======  ===========  ==========================================
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


class EndpointPool(LLMProvider):
    """Round-robin pool of LLMProvider endpoints with cooldown-based failover."""

    def __init__(
        self,
        endpoints: list[LLMProvider],
        cooldown_seconds: float = 60.0,
    ):
        if not endpoints:
            raise ValueError("EndpointPool requires at least one endpoint")
        super().__init__()
        self._endpoints = endpoints
        self._cooldown_seconds = cooldown_seconds
        # endpoint index → timestamp when cooldown expires
        self._cooldowns: dict[int, float] = {}
        # round-robin cursor
        self._cursor = 0

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        """Try endpoints in order, skipping those on cooldown."""
        order = self._pick_order()
        last_resp: LLMResponse | None = None

        for idx in order:
            provider = self._endpoints[idx]
            try:
                resp = await provider.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                )
            except Exception as exc:
                resp = LLMResponse(
                    content=f"Error calling LLM: {exc}",
                    finish_reason="error",
                )

            if resp.finish_reason != "error" or not self._is_transient_error(resp.content):
                # Success or non-transient error — clear cooldown and return.
                self._cooldowns.pop(idx, None)
                self._cursor = (idx + 1) % len(self._endpoints)
                return resp

            # Transient failure — cooldown this endpoint and try next.
            self._cooldowns[idx] = time.monotonic() + self._cooldown_seconds
            logger.warning(
                "Endpoint {} failed (transient), cooling down for {}s. Trying next.",
                idx,
                self._cooldown_seconds,
            )
            last_resp = resp

        # All endpoints failed — return the last error.
        return last_resp  # type: ignore[return-value]

    def get_default_model(self) -> str:
        return self._endpoints[0].get_default_model()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _pick_order(self) -> list[int]:
        """Return endpoint indices: available ones first (round-robin), then cooldown ones (least-recently-failed first)."""
        now = time.monotonic()
        n = len(self._endpoints)

        available: list[int] = []
        on_cooldown: list[tuple[float, int]] = []  # (expiry, index)

        for offset in range(n):
            idx = (self._cursor + offset) % n
            expiry = self._cooldowns.get(idx)
            if expiry is None or now >= expiry:
                available.append(idx)
                # Expired cooldown — clean up.
                self._cooldowns.pop(idx, None)
            else:
                on_cooldown.append((expiry, idx))

        # Sort cooldown endpoints by expiry ascending (try the one closest to recovery first).
        on_cooldown.sort()
        return available + [idx for _, idx in on_cooldown]
