"""Provider-independent generation defaults."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GenerationSettings:
    """Default generation settings."""

    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None
