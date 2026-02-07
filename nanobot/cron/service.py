"""Cron store: jobs.json persistence and next-run computation."""

import json
import re
import time
import uuid
from pathlib import Path

from loguru import logger


def _camel_to_snake(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def _snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:]) if parts else ""


def _keys_snake(d):
    if isinstance(d, dict):
        return {_camel_to_snake(k): _keys_snake(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_keys_snake(v) for v in d]
    return d


def _keys_camel(d):
    if isinstance(d, dict):
        return {_snake_to_camel(k): _keys_camel(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_keys_camel(v) for v in d]
    return d


def now_ms() -> int:
    return int(time.time() * 1000)


def compute_next_run(schedule: dict, base_ms: int) -> int | None:
    kind = schedule.get("kind")
    if kind == "at":
        at = schedule.get("at_ms")
        return at if at and at > base_ms else None
    if kind == "every":
        every = schedule.get("every_ms")
        if not every or every <= 0:
            return None
        return base_ms + every
    if kind == "cron" and schedule.get("expr"):
        try:
            from croniter import croniter
            cron = croniter(schedule["expr"], time.time())
            return int(cron.get_next() * 1000)
        except Exception:
            return None
    return None


class CronStoreService:
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self._store: dict | None = None

    def load(self) -> dict:
        if self._store is not None:
            return self._store
        if self.store_path.exists():
            try:
                raw = json.loads(self.store_path.read_text())
                self._store = _keys_snake(raw)
            except Exception as e:
                logger.warning(f"Failed to load cron store: {e}")
                self._store = {"version": 1, "jobs": []}
        else:
            self._store = {"version": 1, "jobs": []}
        return self._store

    def save(self) -> None:
        store = self.load()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(_keys_camel(store), indent=2))

    def mark_job_finished(
        self,
        job: dict,
        ok: bool,
        error: str | None = None,
        started_at_ms: int | None = None,
    ) -> None:
        state = job.setdefault("state", {})
        state["last_status"] = "ok" if ok else "error"
        state["last_error"] = None if ok else (error or "unknown error")
        state["last_run_at_ms"] = started_at_ms or now_ms()
        job["updated_at_ms"] = now_ms()

        if job.get("schedule", {}).get("kind") == "at":
            if job.get("delete_after_run"):
                store = self.load()
                store["jobs"] = [j for j in store["jobs"] if j["id"] != job["id"]]
            else:
                job["enabled"] = False
                state["next_run_at_ms"] = None
        else:
            state["next_run_at_ms"] = compute_next_run(job.get("schedule", {}), now_ms())

    def list_jobs(self, include_disabled: bool = False) -> list[dict]:
        store = self.load()
        jobs = store["jobs"] if include_disabled else [j for j in store["jobs"] if j.get("enabled", True)]
        return sorted(jobs, key=lambda j: j.get("state", {}).get("next_run_at_ms") or float("inf"))

    def get_job(self, job_id: str) -> dict | None:
        store = self.load()
        return next((j for j in store["jobs"] if j.get("id") == job_id), None)

    def add_job(
        self,
        name: str,
        schedule: dict,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> dict:
        store = self.load()
        base = now_ms()
        job = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "enabled": True,
            "schedule": schedule,
            "payload": {
                "kind": "agent_turn",
                "message": message,
                "deliver": deliver,
                "channel": channel,
                "to": to,
            },
            "state": {"next_run_at_ms": compute_next_run(schedule, base)},
            "created_at_ms": base,
            "updated_at_ms": base,
            "delete_after_run": delete_after_run,
        }
        store["jobs"].append(job)
        self.save()
        return job

    def remove_job(self, job_id: str) -> bool:
        store = self.load()
        before = len(store["jobs"])
        store["jobs"] = [j for j in store["jobs"] if j.get("id") != job_id]
        removed = len(store["jobs"]) < before
        if removed:
            self.save()
        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None
        job["enabled"] = enabled
        job["updated_at_ms"] = now_ms()
        state = job.setdefault("state", {})
        if enabled:
            state["next_run_at_ms"] = compute_next_run(job.get("schedule", {}), now_ms())
        else:
            state["next_run_at_ms"] = None
        self.save()
        return job
