"""The official installer's explicit package selection, not inferred dependencies.

The installer records selection before creating a dedicated environment, so retry
survives first-install failure. The receipt alone does not prove installation or
readiness. Existing uv, pipx, source and unrecorded venvs are never adopted implicitly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RECEIPT_NAME = "nanobot-install.json"


def managed_extras(environment: str, expected_sha256: str) -> list[str]:
    path = Path(environment) / RECEIPT_NAME
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError("Invalid installer receipt")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Installer receipt changed")
    record = json.loads(payload)
    if record != {"schema_version": 1, "owner": "nanobot-installer",
                  "environment": str(Path(environment).resolve()), "extras": []}:
        raise ValueError("This installation selection needs its owner's update workflow")
    return []
