"""Cycle detection for tool calls to prevent infinite loops."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import CycleDetectionConfig


def _canonicalize_args(args: dict | list | None) -> str:
    """Convert args to a canonical JSON string for comparison."""
    if args is None:
        return "{}"
    if isinstance(args, list):
        args = args[0] if args and isinstance(args[0], dict) else {}
    if not isinstance(args, dict):
        return str(args)
    # Sort keys and serialize consistently
    return json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _args_hash(tool_name: str, args: dict | list | None) -> str:
    """Generate a hash for a tool call for deduplication."""
    canonical = f"{tool_name}:{_canonicalize_args(args)}"
    return hashlib.md5(canonical.encode(), usedforsecurity=False).hexdigest()


def _sequence_hash(hashes: list[str]) -> str:
    """Generate a hash for a sequence of tool call hashes."""
    return hashlib.md5("|".join(hashes).encode(), usedforsecurity=False).hexdigest()


@dataclass
class CycleDetectionResult:
    """Result of cycle detection check."""

    is_cycle: bool = False
    reason: str | None = None
    repeated_tool: str | None = None
    repeat_count: int = 0


@dataclass
class CycleDetector:
    """
    Detects repeating tool call patterns to prevent infinite loops.

    Detection strategies:
    1. Same call repetition: same (tool_name, args) called multiple times
    2. Pattern repetition: same sequence of calls repeated

    The detector maintains a sliding window of recent tool calls and checks
    for repetitions within that window.
    """

    # Configuration
    enabled: bool = True
    window_size: int = 20
    max_same_calls: int = 3
    pattern_min_length: int = 2
    pattern_min_repeats: int = 2

    # Internal state
    _recent_hashes: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    _hash_counts: dict[str, int] = field(default_factory=dict)
    _pattern_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize deques with correct maxlen after dataclass init."""
        if not isinstance(self._recent_hashes, deque):
            self._recent_hashes = deque(maxlen=self.window_size)
        if self._recent_hashes.maxlen != self.window_size:
            self._recent_hashes = deque(self._recent_hashes, maxlen=self.window_size)

    @classmethod
    def from_config(cls, config: CycleDetectionConfig | None) -> CycleDetector:
        """Create a CycleDetector from configuration."""
        if config is None:
            return cls()
        return cls(
            enabled=config.enabled,
            window_size=config.window_size,
            max_same_calls=config.max_same_calls,
            pattern_min_length=config.pattern_min_length,
            pattern_min_repeats=config.pattern_min_repeats,
        )

    def check(self, tool_name: str, args: dict | list | None) -> CycleDetectionResult:
        """
        Check if this tool call indicates a cycle.

        Call this BEFORE executing the tool. Returns a result indicating
        whether a cycle was detected and why.

        Args:
            tool_name: Name of the tool being called
            args: Arguments to the tool (dict or list with single dict)

        Returns:
            CycleDetectionResult with is_cycle=True if a loop is detected
        """
        if not self.enabled:
            return CycleDetectionResult()

        call_hash = _args_hash(tool_name, args)

        # Check 1: Same call repeated too many times
        count = self._hash_counts.get(call_hash, 0) + 1
        if count > self.max_same_calls:
            logger.warning(
                "Cycle detected: tool '{}' with same args called {} times",
                tool_name,
                count,
            )
            return CycleDetectionResult(
                is_cycle=True,
                reason=f"Same tool call repeated {count} times",
                repeated_tool=tool_name,
                repeat_count=count,
            )

        # Check 2: Pattern repetition (only if we have enough history)
        if len(self._recent_hashes) >= self.pattern_min_length * 2:
            # Check for repeating patterns of various lengths
            for pattern_len in range(self.pattern_min_length, min(6, len(self._recent_hashes) // 2 + 1)):
                recent = list(self._recent_hashes)[-pattern_len * 2 :]
                first_half = recent[:pattern_len]
                second_half = recent[pattern_len : pattern_len * 2]

                if first_half == second_half:
                    # Pattern repeats! Check if adding current call would continue it
                    pattern_hash = _sequence_hash(first_half)
                    pattern_count = self._pattern_counts.get(pattern_hash, 1) + 1

                    if pattern_count >= self.pattern_min_repeats:
                        tools_in_pattern = self._extract_tool_names(first_half)
                        logger.warning(
                            "Cycle detected: pattern of {} tools repeated {} times: {}",
                            pattern_len,
                            pattern_count,
                            tools_in_pattern,
                        )
                        return CycleDetectionResult(
                            is_cycle=True,
                            reason=f"Pattern of {pattern_len} tools repeated {pattern_count} times",
                            repeated_tool=tool_name,
                            repeat_count=pattern_count,
                        )

        # No cycle detected yet, record this call
        self._record_call(call_hash)
        return CycleDetectionResult()

    def _record_call(self, call_hash: str) -> None:
        """Record a tool call for cycle detection."""
        # Update hash counts
        self._hash_counts[call_hash] = self._hash_counts.get(call_hash, 0) + 1

        # Track patterns when window slides
        if len(self._recent_hashes) >= self.pattern_min_length:
            recent = list(self._recent_hashes)[-self.pattern_min_length :]
            pattern_hash = _sequence_hash(recent)
            self._pattern_counts[pattern_hash] = self._pattern_counts.get(pattern_hash, 0) + 1

        self._recent_hashes.append(call_hash)

    def _extract_tool_names(self, hashes: list[str]) -> list[str]:
        """Extract tool names from hashes (for logging)."""
        # We don't store tool names with hashes, so return hash prefixes
        return [h[:6] for h in hashes]

    def reset(self) -> None:
        """Reset the detector state for a new session/turn."""
        self._recent_hashes.clear()
        self._hash_counts.clear()
        self._pattern_counts.clear()

    def get_stats(self) -> dict:
        """Get statistics about detected patterns (for debugging/metrics)."""
        return {
            "unique_calls": len(self._hash_counts),
            "total_calls": sum(self._hash_counts.values()),
            "patterns_seen": len(self._pattern_counts),
        }
