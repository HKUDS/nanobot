"""Optional logging wrapper for LLM chat requests (messages + tools)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse

_DEFAULT_LLM_LOG_REL = "logs/llm_requests.log"


def _resolve_llm_log_path(workspace: Path, path: str | None) -> Path:
    """Resolve log file path: None/empty -> workspace/logs/llm_requests.log; else relative to workspace unless absolute."""
    ws = workspace.expanduser().resolve()
    raw = (path or "").strip()
    if not raw:
        raw = _DEFAULT_LLM_LOG_REL
    p = Path(raw)
    if p.is_absolute():
        return p
    return (ws / p).resolve()


def wrap_llm_provider_if_enabled(
    inner: LLMProvider,
    *,
    workspace: Path,
    log_llm_requests: bool,
    log_llm_max_chars: int | None = None,
    log_llm_requests_path: str | None = None,
) -> LLMProvider:
    """Return inner unchanged, or wrapped to append each chat() payload to a log file when enabled."""
    if not log_llm_requests:
        return inner
    log_path = _resolve_llm_log_path(workspace, log_llm_requests_path)
    return LoggingLLMProvider(inner, log_path=log_path, max_chars=log_llm_max_chars)


class LoggingLLMProvider(LLMProvider):
    """Delegates to an inner provider and appends each outgoing chat request to a log file."""

    def __init__(self, inner: LLMProvider, log_path: Path, max_chars: int | None = None):
        super().__init__(api_key=inner.api_key, api_base=inner.api_base)
        self._inner = inner
        self._log_path = log_path
        self._max_chars = max_chars
        self._lock = threading.Lock()

    def get_default_model(self) -> str:
        return self._inner.get_default_model()

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
    ) -> LLMResponse:
        self._log_request(messages, tools, model, max_tokens, temperature, reasoning_effort)
        return await self._inner.chat(
            messages=messages,
            tools=tools,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
        )

    def _log_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
            "messages": messages,
            "tools": tools,
        }
        try:
            text = json.dumps(payload, ensure_ascii=False, default=str)
        except Exception as e:  # noqa: BLE001 — best-effort logging
            logger.warning("LLM request log serialization failed: {}", e)
            text = json.dumps(
                {
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "reasoning_effort": reasoning_effort,
                    "messages_note": "omitted (serialization error)",
                    "tools_note": "omitted (serialization error)",
                },
                ensure_ascii=False,
            )

        original_len = len(text)
        if self._max_chars is not None and original_len > self._max_chars:
            text = (
                text[: self._max_chars]
                + f"\n... [truncated, original_length={original_len} chars]"
            )

        ts = datetime.now(timezone.utc).isoformat()
        block = f"==== {ts} ====\n{text}\n\n"
        try:
            with self._lock:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(block)
                    f.flush()
        except OSError as e:
            logger.warning("LLM request log write failed ({}): {}", self._log_path, e)
