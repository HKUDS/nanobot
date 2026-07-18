"""Workspace-scoped local trigger store and delivery queue."""

from __future__ import annotations

import errno
import json
import os
import secrets
import time
import uuid
from collections.abc import Collection
from contextlib import suppress
from pathlib import Path
from typing import Any

from filelock import FileLock
from loguru import logger

from nanobot.triggers.local_types import LocalTrigger, TriggerDelivery, TriggerRunRecord
from nanobot.utils.helpers import truncate_text
from nanobot.utils.run_records import write_run_record as write_automation_run_record

_TRIGGER_ID_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_MAX_RUN_HISTORY = 20
_MAX_DELIVERY_ATTEMPTS = 10
_RUN_RECORD_TEXT_MAX_CHARS = 4000
_PENDING_PREVIEW_MAX_CHARS = 4000
_PENDING_PREVIEW_PREFIX_MAX_CHARS = 32 * 1024
_PENDING_PREVIEW_CACHE_VARIANTS = 16
_PROCESSING_RECOVERY_ERROR = "delivery was recovered from interrupted processing"


class TriggerStoreError(RuntimeError):
    """Base class for trigger store errors."""


class TriggerNotFoundError(TriggerStoreError):
    """Raised when a trigger ID does not exist."""


class TriggerDisabledError(TriggerStoreError):
    """Raised when a trigger is disabled."""


class LocalTriggerStore:
    """Persistent local triggers for one workspace."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self.root = self.workspace_path / "triggers"
        self.store_path = self.root / "triggers.json"
        self.inbox_dir = self.root / "inbox"
        self.processing_dir = self.root / "processing"
        self.failed_dir = self.root / "failed"
        self.runs_dir = self.root / "runs"
        self._lock = FileLock(str(self.root / ".lock"))
        self._pending_preview_cache_state: tuple[int, int] | None = None
        self._pending_preview_cache: dict[frozenset[str] | None, dict[str, str]] = {}

    def create(
        self,
        *,
        name: str,
        channel: str,
        chat_id: str,
        session_key: str,
        sender_id: str = "trigger",
        origin_metadata: dict[str, Any] | None = None,
    ) -> LocalTrigger:
        """Create a new session-bound local trigger."""
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
            trigger = LocalTrigger(
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

    def list_triggers(self, *, include_disabled: bool = False) -> list[LocalTrigger]:
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
    ) -> list[LocalTrigger]:
        """List triggers bound to one session key."""
        return [
            trigger
            for trigger in self.list_triggers(include_disabled=include_disabled)
            if trigger.session_key == session_key
        ]

    def get(self, trigger_id: str) -> LocalTrigger | None:
        """Return one trigger by ID."""
        self._ensure_dirs()
        with self._lock:
            return self._find_unlocked(self._load_triggers_unlocked(), trigger_id)

    def enable(self, trigger_id: str, *, enabled: bool) -> LocalTrigger | None:
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

    def update(self, trigger_id: str, *, name: str | None = None) -> LocalTrigger | None:
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
        trigger_id = trigger_id.strip()
        self._ensure_dirs()
        with self._lock:
            triggers = self._load_triggers_unlocked()
            remaining = [trigger for trigger in triggers if trigger.id != trigger_id]
            if len(remaining) == len(triggers):
                return False
            self._save_triggers_unlocked(remaining)
            self._delete_delivery_files_for_trigger_unlocked(trigger_id)
            self._invalidate_pending_preview_cache_unlocked()
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
            path = self.inbox_dir / (
                f"{delivery.created_at_ms}-{delivery.id}-{delivery.trigger_id}.json"
            )
            self._atomic_write(path, json.dumps(_delivery_payload(delivery), ensure_ascii=False))
            delivery.path = path
            try:
                self.write_delivery_run_record(delivery, trigger=trigger, status="queued")
            except BaseException:
                path.unlink(missing_ok=True)
                delivery.path = None
                raise
            self._invalidate_pending_preview_cache_unlocked()
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
            if claimed:
                self._invalidate_pending_preview_cache_unlocked()
        return claimed

    def pending_delivery_previews(
        self,
        trigger_ids: Collection[str] | None = None,
    ) -> dict[str, str]:
        """Return bounded previews of the next delivery for selected local triggers."""
        self._ensure_dirs()
        targets = (
            frozenset(trigger_id.strip() for trigger_id in trigger_ids if trigger_id.strip())
            if trigger_ids is not None
            else None
        )
        if targets is not None and not targets:
            return {}

        with self._lock:
            state = self._pending_queue_state_unlocked()
            if state != self._pending_preview_cache_state:
                self._pending_preview_cache_state = state
                self._pending_preview_cache.clear()
            cached = self._pending_preview_cache.get(targets)
            if cached is not None:
                return dict(cached)

            previews: dict[str, str] = {}
            done = False
            # Claimed deliveries run before anything still in the inbox. New
            # filenames expose the trigger ID so duplicate backlog entries can
            # be skipped without reading their full payloads. Legacy queue files
            # remain readable through the JSON fallback below.
            for directory in (self.processing_dir, self.inbox_dir):
                for path in sorted(directory.glob("*.json")):
                    trigger_hint = self._delivery_file_trigger_id_from_name(path)
                    if trigger_hint is not None:
                        if targets is not None and trigger_hint not in targets:
                            continue
                        if trigger_hint in previews:
                            continue
                    preview = self._read_pending_delivery_preview_unlocked(
                        path,
                        expected_trigger_id=trigger_hint,
                    )
                    if preview is None:
                        # Queue recovery/claiming owns corrupt-file handling. This
                        # read-only view should not mutate the delivery queue.
                        continue
                    trigger_id, content = preview
                    if targets is not None and trigger_id not in targets:
                        continue
                    previews.setdefault(trigger_id, content)
                    if targets is not None and targets.issubset(previews):
                        done = True
                        break
                if done:
                    break

            if len(self._pending_preview_cache) >= _PENDING_PREVIEW_CACHE_VARIANTS:
                oldest = next(iter(self._pending_preview_cache))
                self._pending_preview_cache.pop(oldest)
            self._pending_preview_cache[targets] = dict(previews)
            return previews

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
            self._invalidate_pending_preview_cache_unlocked()

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

    def write_run_record(self, run_id: str, record: dict[str, Any]) -> Path:
        """Write an internal audit record for one local trigger delivery."""
        self._ensure_dirs()
        return write_automation_run_record(self.runs_dir, run_id, record)

    def write_delivery_run_record(
        self,
        delivery: TriggerDelivery,
        *,
        status: str,
        trigger: LocalTrigger | None = None,
        error: str | None = None,
        response: str | None = None,
    ) -> Path:
        """Write the durable audit record for one local trigger delivery."""
        if trigger is None:
            trigger = self.get(delivery.trigger_id)
        record = _delivery_run_record(delivery, trigger)
        record["status"] = status
        if error:
            record["error"] = _run_record_text(error)
        if response is not None:
            record["response"] = _run_record_text(response)
        return self.write_run_record(delivery.id, record)

    def _ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _load_triggers_unlocked(self) -> list[LocalTrigger]:
        if not self.store_path.exists():
            return []
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
            return [
                LocalTrigger.from_dict(raw)
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

    def _save_triggers_unlocked(self, triggers: list[LocalTrigger]) -> None:
        payload = {
            "version": 1,
            "triggers": [trigger.to_dict() for trigger in triggers],
        }
        self._atomic_write(self.store_path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _pending_queue_state_unlocked(self) -> tuple[int, int]:
        return (
            self.processing_dir.stat().st_mtime_ns,
            self.inbox_dir.stat().st_mtime_ns,
        )

    def _invalidate_pending_preview_cache_unlocked(self) -> None:
        self._pending_preview_cache_state = None
        self._pending_preview_cache.clear()

    def _read_pending_delivery_preview_unlocked(
        self,
        path: Path,
        *,
        expected_trigger_id: str | None,
    ) -> tuple[str, str] | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                prefix = handle.read(_PENDING_PREVIEW_PREFIX_MAX_CHARS)
                preview = _preview_from_payload_prefix(prefix)
                if preview is not None and (
                    expected_trigger_id is None or preview[0] == expected_trigger_id
                ):
                    return preview
                data = json.loads(prefix + handle.read())
            delivery = TriggerDelivery.from_dict(data.get("delivery", data), path=path)
        except Exception:
            return None
        return delivery.trigger_id, _pending_preview_text(delivery.content)

    @staticmethod
    def _find_unlocked(
        triggers: list[LocalTrigger],
        trigger_id: str,
    ) -> LocalTrigger | None:
        return next((trigger for trigger in triggers if trigger.id == trigger_id), None)

    def _move_bad_delivery_unlocked(self, path: Path) -> None:
        target = self.failed_dir / f"{path.name}.bad"
        try:
            os.replace(path, target)
        except OSError:
            return
        self._invalidate_pending_preview_cache_unlocked()

    def _retry_delivery_unlocked(self, delivery: TriggerDelivery, error: str) -> bool:
        if delivery.path is None:
            return False
        if delivery.attempts + 1 >= _MAX_DELIVERY_ATTEMPTS:
            delivery.attempts += 1
            delivery.last_error = error
            failed = self.failed_dir / delivery.path.name
            self._atomic_write(failed, json.dumps(_delivery_payload(delivery), ensure_ascii=False))
            delivery.path.unlink(missing_ok=True)
            self._invalidate_pending_preview_cache_unlocked()
            return False
        delivery.attempts += 1
        delivery.last_error = error
        target = self.inbox_dir / delivery.path.name
        self._atomic_write(target, json.dumps(_delivery_payload(delivery), ensure_ascii=False))
        delivery.path.unlink(missing_ok=True)
        self._invalidate_pending_preview_cache_unlocked()
        return True

    def _delete_delivery_files_for_trigger_unlocked(self, trigger_id: str) -> None:
        for directory in (self.inbox_dir, self.processing_dir, self.failed_dir):
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                if self._delivery_file_trigger_id(path) != trigger_id:
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning(
                        "Trigger: failed to delete delivery file {} for deleted trigger {}: {}",
                        path,
                        trigger_id,
                        exc,
                    )

    @staticmethod
    def _delivery_file_trigger_id(path: Path) -> str | None:
        trigger_id = LocalTriggerStore._delivery_file_trigger_id_from_name(path)
        if trigger_id is not None:
            return trigger_id
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        raw = data.get("delivery", data) if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            return None
        trigger_id = raw.get("triggerId", raw.get("trigger_id", ""))
        return str(trigger_id) if trigger_id else None

    @staticmethod
    def _delivery_file_trigger_id_from_name(path: Path) -> str | None:
        parts = path.name.split("-", 2)
        if len(parts) != 3:
            return None
        delivery_name, trigger_name = parts[1:]
        trigger_id = trigger_name.split(".", 1)[0]
        if not delivery_name.startswith("tdl_") or not trigger_id.startswith("trg_"):
            return None
        return trigger_id

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
                    try:
                        os.fsync(fd)
                    except OSError as exc:
                        if exc.errno != errno.EINVAL:
                            raise
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
    return (stripped or "Local trigger")[:120]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _delivery_payload(delivery: TriggerDelivery) -> dict[str, Any]:
    # Keep the bounded preview before the full delivery. The WebUI queue view
    # intentionally decodes only a fixed-size prefix for current-format files.
    return {
        "version": 1,
        "preview": {
            "triggerId": delivery.trigger_id,
            "content": _pending_preview_text(delivery.content),
        },
        "delivery": delivery.to_dict(),
    }


def _preview_from_payload_prefix(content: str) -> tuple[str, str] | None:
    marker = '"preview":'
    marker_index = content.find(marker)
    if marker_index < 0:
        return None
    fragment = content[marker_index + len(marker) :].lstrip()
    try:
        raw, _ = json.JSONDecoder().raw_decode(fragment)
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    trigger_id = raw.get("triggerId")
    preview = raw.get("content")
    if not isinstance(trigger_id, str) or not isinstance(preview, str):
        return None
    return trigger_id, preview


def _pending_preview_text(value: str) -> str:
    return truncate_text(value, _PENDING_PREVIEW_MAX_CHARS)


def _delivery_run_record(
    delivery: TriggerDelivery,
    trigger: LocalTrigger | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "kind": "local_trigger",
        "trigger_id": delivery.trigger_id,
        "delivery_id": delivery.id,
        "content": _run_record_text(delivery.content),
        "created_at_ms": delivery.created_at_ms,
        "attempts": delivery.attempts,
    }
    if delivery.last_error:
        record["last_error"] = _run_record_text(delivery.last_error)
    if trigger is not None:
        record.update(
            {
                "trigger_name": trigger.name,
                "session_key": trigger.session_key,
                "channel": trigger.channel,
                "chat_id": trigger.chat_id,
                "sender_id": trigger.sender_id,
                "origin_metadata": trigger.origin_metadata,
            }
        )
    return record


def _run_record_text(value: str) -> str:
    return truncate_text(value, _RUN_RECORD_TEXT_MAX_CHARS)
