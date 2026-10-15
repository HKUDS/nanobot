"""Identity of a complete scheduled turn, not a separate forwarding address."""

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from nanobot.cron.types import CronJob


class CronBindingError(ValueError):
    def __init__(self, reason: Literal["busy", "unavailable", "conflict", "empty"], message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CronBinding:
    session_key: str
    channel: str
    chat_id: str
    metadata: dict[str, Any]


def binding_revision(job: CronJob) -> str:
    """Compare all editable state, including changes within the same millisecond."""
    value = asdict(job)
    value.pop("state")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
