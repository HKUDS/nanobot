"""TTS provider interface."""

from abc import ABC, abstractmethod
from pathlib import Path


class TTSError(Exception):
    """TTS synthesis failed."""
    pass


class TTSProvider(ABC):
    """Abstract TTS provider."""

    @abstractmethod
    async def synthesize(self, text: str, output_path: Path) -> Path:
        """Convert text to audio file. Returns output_path on success, raises TTSError on failure."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...
