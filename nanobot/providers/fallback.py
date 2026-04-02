"""FallbackProvider — transparent chain with circuit breaker.

Wraps a primary LLMProvider + N fallback (provider, model) pairs.
On transient errors, falls through the chain. Circuit breaker skips
providers that failed recently (within cooldown_s).
"""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse


class FallbackProvider(LLMProvider):
    """Chain: primary → fallback[0] → fallback[1] → ... → error."""

    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: list[tuple[LLMProvider, str]],
        cooldown_s: float = 60,
    ):
        super().__init__()
        self.primary = primary
        self.fallbacks = fallbacks
        self._cooldown_s = cooldown_s
        self._primary_failed_at: float = 0

    async def chat(self, **kwargs: Any) -> LLMResponse:
        resp = await self._try_primary(self.primary._safe_chat, **kwargs)
        if resp is not None:
            return resp
        return await self._try_fallbacks(self._call_chat, **kwargs)

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        logger.debug("FallbackProvider.chat_stream called, cooldown={}", self._in_cooldown())
        resp = await self._try_primary(self.primary._safe_chat_stream, **kwargs)
        if resp is not None:
            return resp
        return await self._try_fallbacks(self._call_stream, **kwargs)

    def get_default_model(self) -> str:
        return self.primary.get_default_model()

    # --- 内部 ---

    async def _try_primary(self, call, **kwargs: Any) -> LLMResponse | None:
        """尝试 primary，返回 None 表示需要 fallback。"""
        if self._in_cooldown():
            return None
        resp = await call(**kwargs)
        if resp.finish_reason != "error" or not self._is_transient_error(resp.content):
            self._primary_failed_at = 0
            return resp
        self._primary_failed_at = time.monotonic()
        logger.warning("Primary provider failed: {}", (resp.content or "")[:120])
        return None

    async def _try_fallbacks(self, call, **kwargs: Any) -> LLMResponse:
        resp = LLMResponse(content="All providers failed", finish_reason="error")
        kwargs.pop("model", None)  # 避免与 fallback 的显式 model 参数冲突
        for fb_provider, fb_model in self.fallbacks:
            logger.info("Trying fallback: {}", fb_model)
            resp = await call(fb_provider, fb_model, **kwargs)
            if resp.finish_reason != "error" or not self._is_transient_error(resp.content):
                return resp
            logger.warning("Fallback {} also failed: {}", fb_model, (resp.content or "")[:120])
        return resp

    @staticmethod
    async def _call_chat(provider: LLMProvider, model: str, **kwargs: Any) -> LLMResponse:
        return await provider._safe_chat(model=model, **kwargs)

    @staticmethod
    async def _call_stream(provider: LLMProvider, model: str, **kwargs: Any) -> LLMResponse:
        return await provider._safe_chat_stream(model=model, **kwargs)

    def _in_cooldown(self) -> bool:
        if self._primary_failed_at == 0:
            return False
        return (time.monotonic() - self._primary_failed_at) < self._cooldown_s
