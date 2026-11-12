"""Normalized usage values shared by providers and usage records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Canonical token usage reported by, or estimated for, one or more LLM calls.

    ``input_tokens`` is the logical input total and therefore includes cache reads
    and writes.  ``None`` cache counts mean the wire protocol did not report that
    metric, while zero means it explicitly reported no cache activity.

    ``total_tokens`` preserves a provider-reported total when it exceeds the
    visible input plus output (for example, hidden reasoning or tool usage).  It
    must be at least ``input_tokens + output_tokens``.  The reported and estimated
    totals partition it exactly, including after multi-call aggregation.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reported_tokens: int = 0
    estimated_tokens: int = 0
    generation_ms: int = 0
    measured_output_tokens: int = 0
    ttft_ms: int = 0
    timed_requests: int = 0
    context_tokens: int | None = None
    request_count: int = 0

    def __post_init__(self) -> None:
        token_fields = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "reported_tokens": self.reported_tokens,
            "estimated_tokens": self.estimated_tokens,
            "generation_ms": self.generation_ms,
            "measured_output_tokens": self.measured_output_tokens,
            "ttft_ms": self.ttft_ms,
            "timed_requests": self.timed_requests,
            "request_count": self.request_count,
        }
        for name, value in token_fields.items():
            runtime_value = cast(object, value)
            if (
                not isinstance(runtime_value, int)
                or isinstance(runtime_value, bool)
                or runtime_value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        for name, value in (
            ("cache_read_tokens", self.cache_read_tokens),
            ("cache_write_tokens", self.cache_write_tokens),
            ("context_tokens", self.context_tokens),
        ):
            runtime_value = cast(object, value)
            if runtime_value is not None and (
                not isinstance(runtime_value, int)
                or isinstance(runtime_value, bool)
                or runtime_value < 0
            ):
                raise ValueError(f"{name} must be None or a non-negative integer")

        visible_total = self.input_tokens + self.output_tokens
        if self.total_tokens < visible_total:
            raise ValueError("total_tokens must be at least input_tokens + output_tokens")
        if self.reported_tokens + self.estimated_tokens != self.total_tokens:
            raise ValueError("reported_tokens + estimated_tokens must equal total_tokens")
        cache_total = (self.cache_read_tokens or 0) + (self.cache_write_tokens or 0)
        if cache_total > self.input_tokens:
            raise ValueError("cache token counts cannot exceed logical input_tokens")

    @classmethod
    def reported(
        cls,
        *,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int | None = None,
        cache_read_tokens: int | None = None,
        cache_write_tokens: int | None = None,
    ) -> LLMUsage:
        """Build usage normalized from a provider response."""
        visible_total = input_tokens + output_tokens
        normalized_total = (
            visible_total if total_tokens is None else max(visible_total, total_tokens)
        )
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=normalized_total,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            reported_tokens=normalized_total,
            context_tokens=input_tokens,
            request_count=1,
        )

    @classmethod
    def estimated(cls, *, input_tokens: int, output_tokens: int) -> LLMUsage:
        """Build usage estimated locally because the provider omitted it."""
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_tokens=input_tokens + output_tokens,
            context_tokens=input_tokens,
            request_count=1,
        )

    @classmethod
    def empty_request(cls) -> LLMUsage:
        """Represent a completed model request with no measurable token usage."""
        return cls(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            request_count=1,
        )

    @property
    def source(self) -> Literal["reported", "estimated", "mixed"]:
        if self.estimated_tokens == 0:
            return "reported"
        if self.reported_tokens == 0:
            return "estimated"
        return "mixed"

    def with_timing(
        self,
        *,
        generation_ms: int | None,
        ttft_ms: int | None,
    ) -> LLMUsage:
        """Attach locally measured streaming telemetry to this usage value."""
        return LLMUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
            reported_tokens=self.reported_tokens,
            estimated_tokens=self.estimated_tokens,
            generation_ms=max(0, generation_ms or 0),
            measured_output_tokens=self.output_tokens if generation_ms is not None else 0,
            ttft_ms=max(0, ttft_ms or 0),
            timed_requests=1 if ttft_ms is not None else 0,
            context_tokens=self.context_tokens,
            request_count=self.request_count,
        )

    def __add__(self, other: LLMUsage) -> LLMUsage:
        """Aggregate calls without turning partially reported cache data into a count."""

        def _sum_cache(left: int | None, right: int | None) -> int | None:
            return left + right if left is not None and right is not None else None

        return LLMUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_read_tokens=_sum_cache(self.cache_read_tokens, other.cache_read_tokens),
            cache_write_tokens=_sum_cache(self.cache_write_tokens, other.cache_write_tokens),
            reported_tokens=self.reported_tokens + other.reported_tokens,
            estimated_tokens=self.estimated_tokens + other.estimated_tokens,
            generation_ms=self.generation_ms + other.generation_ms,
            measured_output_tokens=(
                self.measured_output_tokens + other.measured_output_tokens
            ),
            ttft_ms=self.ttft_ms + other.ttft_ms,
            timed_requests=self.timed_requests + other.timed_requests,
            context_tokens=(
                other.context_tokens
                if other.context_tokens is not None
                else self.context_tokens
            ),
            request_count=self.request_count + other.request_count,
        )

    def to_dict(self) -> dict[str, int | str | None]:
        """Serialize the canonical contract at JSON/persistence boundaries."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "reported_tokens": self.reported_tokens,
            "estimated_tokens": self.estimated_tokens,
            "source": self.source,
            "generation_ms": self.generation_ms,
            "measured_output_tokens": self.measured_output_tokens,
            "ttft_ms": self.ttft_ms,
            "timed_requests": self.timed_requests,
            "context_tokens": self.context_tokens,
            "request_count": self.request_count,
        }

    def to_turn_dict(self) -> dict[str, int]:
        """Project canonical usage into the compact WebUI/TUI per-turn shape."""
        result: dict[str, int] = {
            "prompt_tokens": self.input_tokens,
            "completion_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "request_count": self.request_count,
            "estimated_tokens": self.estimated_tokens,
        }
        if self.context_tokens is not None:
            result["context_tokens"] = self.context_tokens
        if self.cache_read_tokens is not None:
            result["cached_tokens"] = self.cache_read_tokens
        if self.cache_write_tokens is not None:
            result["cache_write_tokens"] = self.cache_write_tokens
        if self.generation_ms > 0 and self.measured_output_tokens > 0:
            result["generation_ms"] = self.generation_ms
            result["measured_completion_tokens"] = self.measured_output_tokens
        if self.timed_requests > 0:
            result["ttft_ms"] = self.ttft_ms
            result["timed_requests"] = self.timed_requests
        return result

    @classmethod
    def from_dict(cls, value: object) -> LLMUsage | None:
        """Validate the exact first-party serialized contract."""
        if not isinstance(value, dict):
            return None
        data = cast(dict[object, object], value)
        integer_fields = (
            "input_tokens",
            "output_tokens",
            "reported_tokens",
            "estimated_tokens",
            "generation_ms",
            "measured_output_tokens",
            "ttft_ms",
            "timed_requests",
            "request_count",
        )
        serialized_fields = {
            *integer_fields,
            "total_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "context_tokens",
            "source",
        }
        if set(data) != serialized_fields:
            return None
        if any(
            not isinstance(item := data.get(name), int) or isinstance(item, bool)
            for name in integer_fields
        ):
            return None
        cache_read = data.get("cache_read_tokens")
        cache_write = data.get("cache_write_tokens")
        context_tokens = data.get("context_tokens")
        total = data.get("total_tokens")
        source = data.get("source")
        if any(
            item is not None and (not isinstance(item, int) or isinstance(item, bool))
            for item in (cache_read, cache_write, context_tokens)
        ) or not isinstance(total, int) or isinstance(total, bool):
            return None
        try:
            usage = cls(
                input_tokens=cast(int, data["input_tokens"]),
                output_tokens=cast(int, data["output_tokens"]),
                total_tokens=total,
                cache_read_tokens=cast(int | None, cache_read),
                cache_write_tokens=cast(int | None, cache_write),
                reported_tokens=cast(int, data["reported_tokens"]),
                estimated_tokens=cast(int, data["estimated_tokens"]),
                generation_ms=cast(int, data["generation_ms"]),
                measured_output_tokens=cast(int, data["measured_output_tokens"]),
                ttft_ms=cast(int, data["ttft_ms"]),
                timed_requests=cast(int, data["timed_requests"]),
                context_tokens=cast(int | None, context_tokens),
                request_count=cast(int, data["request_count"]),
            )
        except (KeyError, ValueError):
            return None
        if source != usage.source:
            return None
        return usage
