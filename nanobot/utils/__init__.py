"""Utility functions for nanobot."""

from nanobot.utils.helpers import ensure_dir, get_data_path, get_workspace_path
from nanobot.utils.media_cleanup import (
    MediaCleanupRegistry,
    get_cleanup_registry,
    shutdown_cleanup_registry,
)
from nanobot.utils.rate_limit import (
    RateLimiter,
    transcription_rate_limiter,
    tts_rate_limiter,
    video_rate_limiter,
    # Legacy class aliases (deprecated)
    TranscriptionRateLimiter,
    TTSRateLimiter,
    VideoRateLimiter,
    VisionRateLimiter,
)

__all__ = [
    "ensure_dir",
    "get_workspace_path",
    "get_data_path",
    "MediaCleanupRegistry",
    "get_cleanup_registry",
    "shutdown_cleanup_registry",
    "RateLimiter",
    # Factory functions (preferred)
    "tts_rate_limiter",
    "transcription_rate_limiter",
    "video_rate_limiter",
    # Legacy classes (deprecated, use factory functions instead)
    "TTSRateLimiter",
    "TranscriptionRateLimiter",
    "VideoRateLimiter",
    "VisionRateLimiter",
]
