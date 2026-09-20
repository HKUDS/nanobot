"""Private, in-memory attribution of a single measured model input."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, cast


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    """Exact provider-owned input shape, scoped to one live provider instance.

    Fingerprints retain neither transcript text nor credentials. Providers opt
    in only when they can describe the actual representation before dispatch.
    """

    identity: str = field(repr=False)
    messages: tuple[str, ...] = field(repr=False)

    @classmethod
    def from_chat_request(cls, scope: str, body: dict[str, Any]) -> InputSnapshot:
        # Delivery options do not affect model input. All other fields, including
        # model, tools, reasoning and tool choice, must match before reuse.
        options = {
            key: value for key, value in body.items()
            if key not in {"messages", "stream", "stream_options", "timeout", "extra_headers"}
        }
        return cls(
            identity=_digest([scope, "chat", options]),
            messages=tuple(_digest(row) for row in cast(list[Any], body["messages"])),
        )


@dataclass(frozen=True, slots=True)
class InputUsage:
    """A reported input count, never a sum of calls or a token estimate."""

    snapshot: InputSnapshot = field(repr=False)
    input_tokens: int

    def floor_for(self, candidate: InputSnapshot | None) -> int | None:
        """Reuse only an exact, unchanged prefix under the same request contract."""
        if (
            candidate is None
            or candidate.identity != self.snapshot.identity
            or not self.snapshot.messages
            or candidate.messages[:len(self.snapshot.messages)] != self.snapshot.messages
        ):
            return None
        return self.input_tokens
