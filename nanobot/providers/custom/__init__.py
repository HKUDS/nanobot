"""Custom provider extensions for nanobot."""

from nanobot.providers.custom.opencode import OpenCodeAsyncOpenAI, is_opencode_model
from nanobot.providers.custom.zaicoding import is_zaicoding_model

__all__ = [
    "OpenCodeAsyncOpenAI",
    "is_opencode_model",
    "is_zaicoding_model",
]
