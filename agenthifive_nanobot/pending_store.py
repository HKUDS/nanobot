"""JSON file persistence for pending approval requests.

Stores pending approvals with their original payloads so the adapter
can replay the exact request when approval is granted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nanobot.config.paths import get_data_dir

from .types import PendingApproval

logger = logging.getLogger(__name__)


def _default_store_path() -> Path:
    return get_data_dir() / "agenthifive" / "pending-approvals.json"


class PendingStore:
    """Thread-safe JSON file store for pending approvals."""

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else _default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[PendingApproval]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
            return [PendingApproval.from_dict(d) for d in data]
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load pending approvals: %s", e)
            return []

    def save(self, approvals: list[PendingApproval]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([a.to_dict() for a in approvals], indent=2))
        tmp.rename(self.path)  # atomic on POSIX

    def add(self, approval: PendingApproval) -> None:
        approvals = self.load()
        # Deduplicate by approval_request_id
        approvals = [a for a in approvals if a.approval_request_id != approval.approval_request_id]
        approvals.append(approval)
        self.save(approvals)

    def remove(self, approval_request_id: str) -> None:
        approvals = self.load()
        approvals = [a for a in approvals if a.approval_request_id != approval_request_id]
        self.save(approvals)
