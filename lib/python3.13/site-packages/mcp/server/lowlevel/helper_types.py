from dataclasses import dataclass
from typing import Any


@dataclass
class ReadResourceContents:
    """Contents returned from a read_resource call."""

    content: str | bytes
    mime_type: str | None = None
    meta: dict[str, Any] | None = None
