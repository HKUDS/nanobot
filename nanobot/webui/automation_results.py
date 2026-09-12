"""Read the response of a selected automation run without exposing its audit metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from nanobot.cron.types import CronJob, CronRunRecord
from nanobot.triggers.local_types import LocalTrigger, TriggerRunRecord
from nanobot.utils.run_records import safe_run_record_name


def _read_record(path: Path, runs_dir: Path) -> dict[str, object] | None:
    if path.is_symlink() or path.resolve().parent != runs_dir.resolve():
        return None
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return None
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
        return None
    # JSON objects have string keys; values remain untrusted until checked below.
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def cron_run_response(runs_dir: Path, job: CronJob, run: CronRunRecord) -> str | None:
    """Resolve explicit run IDs, or uniquely match older records within their execution interval."""
    if run.run_id:
        path = runs_dir / f"{safe_run_record_name(run.run_id)}.json"
        record = _read_record(path, runs_dir)
        if not record or record.get("run_id") != run.run_id:
            return None
        records = [record]
    else:
        records: list[dict[str, object]] = []
        prefix = f"{job.id}:"
        for path in runs_dir.glob("*.json"):
            if not path.name.startswith(safe_run_record_name(prefix)):
                continue
            record = _read_record(path, runs_dir)
            run_id = record.get("run_id") if record else None
            if not isinstance(run_id, str) or not run_id.startswith(prefix):
                continue
            timestamp = run_id[len(prefix):].split(":", 1)[0]
            if not timestamp.isdecimal():
                continue
            started = int(timestamp)
            if not run.run_at_ms <= started <= run.run_at_ms + run.duration_ms:
                continue
            # An overlapping run must not borrow a neighbouring execution's response.
            matches = [item for item in job.state.run_history
                       if item.run_at_ms <= started <= item.run_at_ms + item.duration_ms]
            if len(matches) != 1 or matches[0] != run:
                return None
            if record is not None:
                records.append(record)
    matching = [record for record in records
                if record.get("job_id") == job.id
                and record.get("session_key") == job.payload.session_key
                and record.get("status") == run.status]
    if len(matching) != 1:
        return None
    response = matching[0].get("response")
    return response if isinstance(response, str) else None


def trigger_run_response(
    runs_dir: Path, trigger: LocalTrigger, run: TriggerRunRecord,
) -> str | None:
    """Match a trigger delivery by its saved creation time and session, never the latest reply."""
    matching: list[dict[str, object]] = []
    for path in runs_dir.glob("*.json"):
        record = _read_record(path, runs_dir)
        if (record and record.get("trigger_id") == trigger.id
                and record.get("session_key") == trigger.session_key
                and record.get("created_at_ms") == run.run_at_ms
                and record.get("status") == run.status):
            matching.append(record)
    if len(matching) != 1:
        return None
    response = matching[0].get("response")
    return response if isinstance(response, str) else None
