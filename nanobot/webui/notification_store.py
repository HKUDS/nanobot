"""Durable owner notification feed, separate from any transport's delivery receipt."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Literal, cast

from filelock import FileLock

DeliveryState = Literal["pending", "delivered", "uncertain", "not_sent"]
MAX_NOTIFICATIONS = 500


class NotificationStore:
    """Atomic cross-process updates preserve acknowledgement and delivery state.

    The existing receipt file remains readable, with missing additive fields
    interpreted as a delivered, unread notification. Corruption must never be
    silently overwritten. Delivery uncertainty does not authorize another send.
    """

    def __init__(self, path: Path, *, owner: str, target: str) -> None:
        self.path = path
        self.owner = owner
        self.target = target
        self._lock = FileLock(str(path) + ".lock")

    def rows(self) -> list[dict[str, Any]]:
        try:
            value: object = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(value, dict):
            raise ValueError("invalid notification store")
        data = cast(dict[str, Any], value)
        if data.get("owner") != self.owner or data.get("target") != self.target:
            return []
        rows = data.get("messages")
        if not isinstance(rows, list):
            raise ValueError("invalid notification messages")
        result: list[dict[str, Any]] = []
        for value in cast(list[object], rows)[-MAX_NOTIFICATIONS:]:
            if not isinstance(value, dict):
                raise ValueError("invalid notification row")
            row = cast(dict[str, Any], value)
            if not isinstance(row.get("id"), str) or not isinstance(row.get("content"), str):
                raise ValueError("invalid notification identity or content")
            result.append({"delivery_state": "delivered", "read": False, **row})
        return result

    def record(
        self, text: str, identity: str | int, state: DeliveryState,
    ) -> None:
        if not text.strip():
            return
        key = f"notification:{identity}"
        with self._lock:
            rows = self.rows()
            previous = next((row for row in rows if row["id"] == key), None)
            if previous is not None:
                # A late generated-message event must not downgrade an already
                # confirmed send, or clear a read acknowledgement from another UI.
                if previous["delivery_state"] == "delivered" or state == "pending":
                    return
                previous["delivery_state"] = state
            else:
                rows.append({
                    "id": key, "role": "assistant", "content": text,
                    "createdAt": int(time.time() * 1000),
                    "delivery_state": state, "read": False,
                })
            self._save(rows[-MAX_NOTIFICATIONS:])

    def mark_read(self, identities: list[str]) -> int:
        """Acknowledge exactly the rows a client observed, never unseen new arrivals."""
        if len(identities) > MAX_NOTIFICATIONS or any(
            len(key) > 512 for key in identities
        ):
            raise ValueError("invalid notification identities")
        selected = set(identities)
        with self._lock:
            rows = self.rows()
            changed = 0
            for row in rows:
                if row["id"] in selected and not row["read"]:
                    row["read"] = True
                    changed += 1
            if changed:
                self._save(rows)
            return changed

    def _save(self, rows: list[dict[str, Any]]) -> None:
        payload = {"owner": self.owner, "target": self.target, "messages": rows}
        fd, name = tempfile.mkstemp(prefix=".notification-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            if os.name == "posix":
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)
