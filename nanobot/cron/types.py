"""Cron types."""

from dataclasses import dataclass, field
from typing import Literal

# Exponential backoff delays in ms: 30s, 1m, 5m, 15m, 60m
DEFAULT_BACKOFF_MS: list[int] = [30_000, 60_000, 300_000, 900_000, 3_600_000]

# Max retry attempts for one-shot jobs
ONE_SHOT_MAX_RETRIES = 3

TRANSIENT_ERROR_KEYWORDS = frozenset({
    "timeout", "timed out", "econnreset", "econnrefused",
    "fetch failed", "socket", "network",
    "rate limit", "rate_limit", "too many requests",
    "resource exhausted", "429", "500", "502", "503", "504",
    "cloudflare", "server error", "5xx",
})

PERMANENT_ERROR_KEYWORDS = frozenset({
    "invalid api key", "unauthorized", "forbidden",
    "authentication", "auth failed", "invalid_api_key",
    "config", "validation", "permission denied",
})


def classify_error(error_msg: str) -> Literal["transient", "permanent"]:
    """Classify an error as transient (retryable) or permanent."""
    lower = error_msg.lower()
    if any(kw in lower for kw in PERMANENT_ERROR_KEYWORDS):
        return "permanent"
    if any(kw in lower for kw in TRANSIENT_ERROR_KEYWORDS):
        return "transient"
    return "permanent"


@dataclass
class CronSchedule:
    """Schedule definition for a cron job."""
    kind: Literal["at", "every", "cron"]
    # For "at": timestamp in ms
    at_ms: int | None = None
    # For "every": interval in ms
    every_ms: int | None = None
    # For "cron": cron expression (e.g. "0 9 * * *")
    expr: str | None = None
    # Timezone for cron expressions
    tz: str | None = None
    # Deterministic stagger offset for recurring top-of-hour expressions (ms).
    # 0 = exact, None = auto (up to 5 min for top-of-hour).
    stagger_ms: int | None = None


@dataclass
class DeliveryConfig:
    """How job output is delivered."""
    mode: Literal["announce", "webhook", "none"] = "none"
    channel: str | None = None
    to: str | None = None
    best_effort: bool = False


@dataclass
class CronPayload:
    """What to do when the job runs."""
    kind: Literal["system_event", "agent_turn"] = "agent_turn"
    message: str = ""
    # Legacy fields kept for backward compatibility during deserialization
    deliver: bool = False
    channel: str | None = None
    to: str | None = None


@dataclass
class CronJobState:
    """Runtime state of a job."""
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error", "skipped"] | None = None
    last_error: str | None = None
    consecutive_errors: int = 0
    next_retry_at_ms: int | None = None


@dataclass
class CronRunRecord:
    """Single run history entry (serialized to JSONL)."""
    job_id: str
    timestamp_ms: int
    duration_ms: int
    status: Literal["ok", "error", "skipped"]
    error: str | None = None


@dataclass
class CronJob:
    """A scheduled job."""
    id: str
    name: str
    enabled: bool = True
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))
    payload: CronPayload = field(default_factory=CronPayload)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    state: CronJobState = field(default_factory=CronJobState)
    session_target: Literal["isolated", "main"] = "isolated"
    wake_mode: Literal["now", "next-heartbeat"] = "now"
    created_at_ms: int = 0
    updated_at_ms: int = 0
    delete_after_run: bool = False
    description: str = ""


@dataclass
class CronStore:
    """Persistent store for cron jobs."""
    version: int = 2
    jobs: list[CronJob] = field(default_factory=list)
