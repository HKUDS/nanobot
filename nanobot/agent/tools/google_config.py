"""ID parsing for the Google Drive configuration."""

import re

_GOOGLE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def normalize_google_ids(values: list[str], *, kind: str) -> list[str]:
    """Split, de-duplicate and validate pasted Drive folder IDs."""
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in values:
        for part in re.split(r"[\s,]+", raw.strip()):
            if not part or part in seen:
                continue
            if not _GOOGLE_ID_RE.fullmatch(part):
                raise ValueError(f"invalid {kind} id: {part}")
            seen.add(part)
            normalized.append(part)
    return normalized
