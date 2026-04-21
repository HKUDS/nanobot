"""Use-case classifier — Gemini Flash with LRU cache."""

from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict

logger = logging.getLogger(__name__)

VALID_TAGS = frozenset({
    "meal_planning", "calendar", "home_maintenance", "learning_tola",
    "medical", "inventory", "general_qa", "admin", "other",
})

_PROMPT = (
    "You are classifying a message sent to a household AI assistant. "
    "Return exactly one token from this list, no punctuation, no explanation:\n\n"
    "meal_planning calendar home_maintenance learning_tola medical inventory general_qa admin other\n\n"
    'Message: "{message_text}"'
)


class _LRUCache:
    """Simple ordered-dict LRU cache."""

    def __init__(self, maxsize: int = 500):
        self._data: OrderedDict[str, str] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> str | None:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: str, value: str) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        else:
            if len(self._data) >= self._maxsize:
                self._data.popitem(last=False)
        self._data[key] = value


_cache = _LRUCache()


def _message_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def classify_message_async(text: str) -> str:
    """Classify *text* into a use-case tag. Async version for nanobot's event loop.

    Uses Gemini Flash via OpenAI-compat API. Results cached by SHA-256 of text.
    """
    key = _message_hash(text)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    try:
        tag = await _call_gemini_async(text)
    except Exception:
        logger.debug("Classification failed, defaulting to 'other'", exc_info=True)
        tag = "other"
    _cache.put(key, tag)
    return tag


async def _call_gemini_async(text: str) -> str:
    """Call Gemini Flash and return a validated tag."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "other"
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "gemini-2.5-flash",
                    "messages": [{"role": "user", "content": _PROMPT.format(message_text=text[:500])}],
                    "max_tokens": 10,
                    "temperature": 0,
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"].strip().lower()
            tag = raw.replace('"', "").replace("'", "").strip()
            return tag if tag in VALID_TAGS else "other"
    except Exception:
        logger.debug("Gemini classification request failed", exc_info=True)
        return "other"
