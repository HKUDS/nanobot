"""Small helpers for passing the active LLM provider/model together."""

from __future__ import annotations

from dataclasses import dataclass

from nanobot.providers.base import LLMProvider


@dataclass(frozen=True)
class LLMRuntime:
    provider: LLMProvider
    model: str
