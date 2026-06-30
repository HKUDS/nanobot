"""Workspace-scoped local trigger store and delivery queue."""

from __future__ import annotations

import json
import os
import secrets
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from filelock import FileLock
from loguru import logger

from nanobot.triggers.types import ExternalTrigger, TriggerDelivery, TriggerRunRecord

_TRIGGER_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_MAX_RUN_HISTORY = 20
_MAX_DELIVERY_ATTEMPTS = 10
_PROCESSING_RECOVERY_ERROR = "delivery was recovered from interrupted processing"


class TriggerStoreError(RuntimeError):
    """Base class for trigger store errors."""


class TriggerNotFoundError(TriggerStoreError):
    """Raised when a trigger ID does not exist."""


class TriggerDisabledError(TriggerStoreError):
    """Raised when a trigger is disabled."""


class ExternalTriggerStore:
    """Persistent local triggers for one workspace."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self.root = self.workspace_path / "triggers"
        self.store_path = self.root / "triggers.json"
        self.inbox_dir = self.root / "inbox"
        self.processing_dir = self.root / "processing"
        self.failed_dir = self.root / "failed"
        self._lock = FileLock(str(self.root / ".lock"))

    def create(
        self,
        *,
        name: str,
        channel: str,
        chat_id: str,
        session_key: str,
        sender_id: str = "trigger",
        origin_metadata: dict[str, Any] | None = None,
    ) -> ExternalTrigger:
        """Create a new session-bound external trigger."""
        clean_name = _clean_name(name)
        channel = channel.strip()
        chat_id = chat_id.strip()
        session_key = session_key.strip()
        if not channel or not chat_id or not session_key:
            raise ValueError("channel, chat_id, and session_key are required")

        now = _now_ms()
        self._ensure_dirs()
        with self._lock:
            triggers = self._load_triggers_unlocked()
            existing_ids = {trigger.id for trigger in triggers}
            trigger_id = _new_trigger_id(existing_ids)
            trigger = ExternalTrigger(
                id=trigger_id,
                name=clean_name,
                enabled=True,
                channel=channel,
                chat_id=chat_id,
                session_key=session_key,
                sender_id=sender_id.strip() or "trigger",
                origin_metadata=dict(origin_metadata or {}),
                created_at_ms=now,
                updated_at_ms=now,
            )
            triggers.append(trigger)
            self._save_triggers_unlocked(triggers)
            return trigger

    def list_triggers(self, *, include_disabled: bool = False) -> list[ExternalTrigger]:
        """List triggers in this workspace."""
        self._ensure_dirs()
        with self._lock:
            triggers = self._load_triggers_unlocked()
        if not include_disabled:
            triggers = [trigger for trigger in triggers if trigger.enabled]
        return sorted(triggers, key=lambda trigger: (trigger.updated_at_ms, trigger.id), reverse=True)

    def list_for_session(
        self,
        session_key: str,
        *,
        include_disabled: bool = True,
    ) -> list[ExternalTrigger]:
        """List triggers bound to one session key."""
        return [
            trigger
            for trigger in self.list_triggers(include_disabled=include_disabled)
            if trigger.session_key == session_key
        ]

    def get(self, trigger_id: str) -> ExternalTrigger | None:
        """Return one trigger by ID."""
        self._ensure_dirs()
        with self._lock:
            return self._find_unlocked(self._load_triggers_unlocked(), trigger_id)

    def enable(self, trigger_id: str, *, enabled: bool) -> ExternalTrigger | None:
        """Enable or disable a trigger."""
        self._ensure_dirs()
        with self._lock:
            triggers = self._load_triggers_unlocked()
            trigger = self._find_unlocked(triggers, trigger_id)
            if trigger is None:
                return None
            trigger.enabled = enabled
            trigger.updated_at_ms = _now_ms()
            self._save_triggers_unlocked(triggers)
            return trigger

    def update(self, trigger_id: str, *, name: str | None = None) -> ExternalTrigger | None:
        """Update mutable trigger fields."""
        self._ensure_dirs()
        with self._lock:
            triggers = self._load_triggers_unlocked()
            trigger = self._find_unlocked(triggers, trigger_id)
            if trigger is None:
                return None
            if name is not None:
                trigger.name = _clean_name(name)
            trigger.updated_at_ms = _now_ms()
            self._save_triggers_unlocked(triggers)
            return trigger

    def delete(self, trigger_id: str) -> bool:
        """Delete a trigger by ID."""
        self._ensure_dirs()
        with self._lock:
            triggers = self._load_triggers_unlocked()
            remaining = [trigger for trigger in triggers if trigger.id != trigger_id]
            if len(remaining) == len(triggers):
                return False
            self._save_triggers_unlocked(remaining)
            return True

    def enqueue(self, trigger_id: str, content: str) -> TriggerDelivery:
        """Queue a delivery for the gateway process to consume."""
        trigger_id = trigger_id.strip()
        if not content.strip():
            raise ValueError("trigger message is required")
        self._ensure_dirs()
        with self._lock:
            trigger = self._find_unlocked(self._load_triggers_unlocked(), trigger_id)
            if trigger is None:
                raise TriggerNotFoundError(f"trigger not found: {trigger_id}")
            if not trigger.enabled:
                raise TriggerDisabledError(f"trigger is disabled: {trigger_id}")
            delivery = TriggerDelivery(
                id=f"tdl_{uuid.uuid4().hex[:12]}",
                trigger_id=trigger_id,
                content=content,
                created_at_ms=_now_ms(),
            )
            path = self.inbox_dir / f"{delivery.created_at_ms}-{delivery.id}.json"
            self._atomic_write(path, json.dumps(_delivery_payload(delivery), ensure_ascii=False))
            delivery.path = path
            return delivery

    def claim_deliveries(self, *, limit: int = 20) -> list[TriggerDelivery]:
        """Move pending deliveries into processing and return them."""
        self._ensure_dirs()
        claimed: list[TriggerDelivery] = []
        with self._lock:
            for path in sorted(self.inbox_dir.glob("*.json"))[: max(0, limit)]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    delivery = TriggerDelivery.from_dict(
                        data.get("delivery", data),
                        path=self.processing_dir / path.name,
                    )
                except Exception:
                    logger.exception("Trigger: failed to parse delivery {}", path)
                    self._move_bad_delivery_unlocked(path)
                    continue
                os.replace(path, delivery.path)
                claimed.append(delivery)
        return claimed

    def recover_processing_deliveries(self) -> int:
        """Requeue deliveries left in processing by an interrupted gateway."""
        self._ensure_dirs()
        recovered = 0
        with self._lock:
            for path in sorted(self.processing_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    delivery = TriggerDelivery.from_dict(
                        data.get("delivery", data),
                        path=path,
                    )
                except Exception:
                    logger.exception("Trigger: failed to parse processing delivery {}", path)
                    self._move_bad_delivery_unlocked(path)
                    continue
                if self._retry_delivery_unlocked(delivery, _PROCESSING_RECOVERY_ERROR):
                    recovered += 1
        return recovered

    def complete_delivery(self, delivery: TriggerDelivery) -> None:
        """Delete a claimed delivery after it is handled."""
        if delivery.path is None:
            return
        self._ensure_dirs()
        with self._lock:
            delivery.path.unlink(missing_ok=True)

    def retry_delivery(self, delivery: TriggerDelivery, error: str) -> bool:
        """Retry a claimed delivery unless it exceeded the attempt limit."""
        if delivery.path is None:
            return False
        self._ensure_dirs()
        with self._lock:
            return self._retry_delivery_unlocked(delivery, error)

    def record_delivery(
        self,
        trigger_id: str,
        *,
        status: str,
        error: str | None = None,
        run_at_ms: int | None = None,
    ) -> None:
        """Record the latest delivery status on a trigger."""
        self._ensure_dirs()
        run_at_ms = run_at_ms or _now_ms()
        with self._lock:
            triggers = self._load_triggers_unlocked()
            trigger = self._find_unlocked(triggers, trigger_id)
            if trigger is None:
                return
            trigger.last_run_at_ms = run_at_ms
            trigger.last_status = "ok" if status == "ok" else "error"
            trigger.last_error = None if status == "ok" else (error or "delivery failed")
            trigger.updated_at_ms = _now_ms()
            trigger.run_history.append(
                TriggerRunRecord(
                    run_at_ms=run_at_ms,
                    status=trigger.last_status,
                    error=trigger.last_error,
                )
            )
            trigger.run_history = trigger.run_history[-_MAX_RUN_HISTORY:]
            self._save_triggers_unlocked(triggers)

    def _ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def _load_triggers_unlocked(self) -> list[ExternalTrigger]:
        if not self.store_path.exists():
            return []
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return [
                ExternalTrigger.from_dict(raw)
                for raw in data.get("triggers", [])
                if isinstance(raw, dict)
            ]
        except Exception as exc:
            backup = self.store_path.with_suffix(
                self.store_path.suffix + f".corrupt-{int(time.time())}"
            )
            with suppress(OSError):
                os.replace(self.store_path, backup)
            raise TriggerStoreError(
                f"trigger store at {self.store_path} could not be loaded and was preserved "
                "as a .corrupt-<ts> backup"
            ) from exc

    def _save_triggers_unlocked(self, triggers: list[ExternalTrigger]) -> None:
        payload = {
            "version": 1,
            "triggers": [trigger.to_dict() for trigger in triggers],
        }
        self._atomic_write(self.store_path, json.dumps(payload, indent=2, ensure_ascii=False))

    @staticmethod
    def _find_unlocked(
        triggers: list[ExternalTrigger],
        trigger_id: str,
    ) -> ExternalTrigger | None:
        return next((trigger for trigger in triggers if trigger.id == trigger_id), None)

    def _move_bad_delivery_unlocked(self, path: Path) -> None:
        target = self.failed_dir / f"{path.name}.bad"
        with suppress(OSError):
            os.replace(path, target)

    def _retry_delivery_unlocked(self, delivery: TriggerDelivery, error: str) -> bool:
        if delivery.path is None:
            return False
        if delivery.attempts + 1 >= _MAX_DELIVERY_ATTEMPTS:
            delivery.attempts += 1
            delivery.last_error = error
            failed = self.failed_dir / delivery.path.name
            self._atomic_write(failed, json.dumps(_delivery_payload(delivery), ensure_ascii=False))
            delivery.path.unlink(missing_ok=True)
            return False
        delivery.attempts += 1
        delivery.last_error = error
        target = self.inbox_dir / delivery.path.name
        self._atomic_write(target, json.dumps(_delivery_payload(delivery), ensure_ascii=False))
        delivery.path.unlink(missing_ok=True)
        return True

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            with suppress(PermissionError):
                fd = os.open(str(path.parent), os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise


def _new_trigger_id(existing_ids: set[str]) -> str:
    for _ in range(100):
        suffix = "".join(secrets.choice(_TRIGGER_ID_ALPHABET) for _ in range(8))
        candidate = f"trg_{suffix}"
        if candidate not in existing_ids:
            return candidate
    raise TriggerStoreError("could not allocate a unique trigger id")


def _clean_name(name: str) -> str:
    stripped = " ".join(name.strip().split())
    return (stripped or "External trigger")[:120]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _delivery_payload(delivery: TriggerDelivery) -> dict[str, Any]:
    return {
        "version": 1,
        "delivery": delivery.to_dict(),
    }
