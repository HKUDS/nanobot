"""SQLite persistence and chart queries for LLM usage records."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nanobot.llm_usage.models import LLMCallRecord

SCHEMA_VERSION = 1
MAX_DAYS_RETAINED = 400
MAX_CALLS_RETAINED = 100_000

_ERROR_KINDS = frozenset({
    "authentication",
    "cancelled",
    "configuration",
    "connection",
    "content_filter",
    "context_length",
    "empty",
    "http",
    "invalid_request",
    "overloaded",
    "permission",
    "rate_limit",
    "refusal",
    "server_error",
    "timeout",
})
_FINISH_REASONS = frozenset({
    "cancelled",
    "content_filter",
    "error",
    "function_call",
    "length",
    "refusal",
    "stop",
    "tool_calls",
})

_USAGE_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cache_read_observed_input_tokens",
    "cache_write_observed_input_tokens",
    "total_tokens",
    "reported_tokens",
    "estimated_tokens",
    "generation_ms",
    "measured_output_tokens",
    "ttft_ms",
    "timed_requests",
)
_REQUEST_COLUMNS = (
    "requests",
    "successful_requests",
    "failed_requests",
    "reported_requests",
    "estimated_requests",
)
_AGGREGATE_SQL = """
    COALESCE(SUM(input_tokens), 0) AS input_tokens,
    COALESCE(SUM(output_tokens), 0) AS output_tokens,
    COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
    COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
    COALESCE(SUM(
        CASE WHEN cache_read_tokens IS NOT NULL THEN input_tokens ELSE 0 END
    ), 0) AS cache_read_observed_input_tokens,
    COALESCE(SUM(
        CASE WHEN cache_write_tokens IS NOT NULL THEN input_tokens ELSE 0 END
    ), 0) AS cache_write_observed_input_tokens,
    COALESCE(SUM(total_tokens), 0) AS total_tokens,
    COALESCE(SUM(reported_tokens), 0) AS reported_tokens,
    COALESCE(SUM(estimated_tokens), 0) AS estimated_tokens,
    COALESCE(SUM(generation_ms), 0) AS generation_ms,
    COALESCE(SUM(measured_output_tokens), 0) AS measured_output_tokens,
    COALESCE(SUM(ttft_ms), 0) AS ttft_ms,
    COALESCE(SUM(timed_requests), 0) AS timed_requests,
    COUNT(*) AS requests,
    COALESCE(SUM(CASE WHEN finish_reason IN ('error', 'cancelled') THEN 0 ELSE 1 END), 0)
        AS successful_requests,
    COALESCE(SUM(CASE WHEN finish_reason IN ('error', 'cancelled') THEN 1 ELSE 0 END), 0)
        AS failed_requests,
    COALESCE(SUM(
        CASE WHEN total_tokens IS NOT NULL AND NOT (
            estimated_tokens > 0 AND reported_tokens = 0
        ) THEN 1 ELSE 0 END
    ), 0) AS reported_requests,
    COALESCE(SUM(
        CASE WHEN estimated_tokens > 0 AND reported_tokens = 0 THEN 1 ELSE 0 END
    ), 0) AS estimated_requests,
    COALESCE(SUM(duration_ms), 0) AS duration_ms
"""


def _zone(timezone_name: str | None) -> timezone | ZoneInfo:
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _clean_error_kind(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    return cleaned if cleaned in _ERROR_KINDS else "other"


def _clean_finish_reason(value: str) -> str:
    cleaned = value.strip().lower()
    return cleaned if cleaned in _FINISH_REASONS else "other"


def _clean_status_code(value: int | None) -> int | None:
    if value is None:
        return None
    try:
        status = int(value)
    except (TypeError, ValueError):
        return None
    return status if 100 <= status <= 599 else None


def _as_int_row(row: sqlite3.Row) -> dict[str, int]:
    return {
        key: max(0, int(row[key] or 0))
        for key in (*_USAGE_COLUMNS, *_REQUEST_COLUMNS, "duration_ms")
    }


def _empty_totals() -> dict[str, int]:
    return {key: 0 for key in (*_USAGE_COLUMNS, *_REQUEST_COLUMNS, "duration_ms")}


def _sum_rows(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    totals = _empty_totals()
    for row in rows:
        for key in totals:
            totals[key] += max(0, int(row.get(key) or 0))
    return totals


class LLMUsageStore:
    """A small synchronous WAL database shared by gateway threads/processes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._connection_pid: int | None = None
        self._last_prune_utc_day: int | None = None
        self._writes_since_size_prune = 0
        self._write_version = 0
        self._cached_payload_key: tuple[int, str, str, int, int] | None = None
        self._cached_payload: dict[str, Any] | None = None

    def _connect(self) -> sqlite3.Connection:
        pid = os.getpid()
        if self._connection is not None and self._connection_pid == pid:
            return self._connection
        if self._connection is not None:
            self._connection.close()
            self._cached_payload_key = None
            self._cached_payload = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=0.25,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 250")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.create_function("llm_usage_local_day", 2, self._local_day, deterministic=True)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY,
                started_at_ms INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                source TEXT NOT NULL,
                stream INTEGER NOT NULL,
                finish_reason TEXT NOT NULL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                cache_read_tokens INTEGER,
                cache_write_tokens INTEGER,
                reported_tokens INTEGER,
                estimated_tokens INTEGER,
                generation_ms INTEGER,
                measured_output_tokens INTEGER,
                ttft_ms INTEGER,
                timed_requests INTEGER,
                error_status_code INTEGER,
                error_kind TEXT
            );
            CREATE INDEX IF NOT EXISTS llm_calls_started_at_idx
                ON llm_calls(started_at_ms);
            CREATE INDEX IF NOT EXISTS llm_calls_provider_model_time_idx
                ON llm_calls(provider, model, started_at_ms);
            """
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection = connection
        self._connection_pid = pid
        return connection

    def _read_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=0.25,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 250")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.create_function("llm_usage_local_day", 2, self._local_day, deterministic=True)
        return connection

    @staticmethod
    def _local_day(started_at_ms: object, timezone_name: object) -> str | None:
        if not isinstance(started_at_ms, int) or not isinstance(timezone_name, str):
            return None
        dt = datetime.fromtimestamp(started_at_ms / 1000, timezone.utc)
        return dt.astimezone(_zone(timezone_name)).date().isoformat()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            self._connection_pid = None
            self._cached_payload_key = None
            self._cached_payload = None

    def record(self, call: LLMCallRecord) -> None:
        usage = call.usage
        usage_data = usage.to_dict() if usage is not None else {}
        values: tuple[object, ...] = (
            call.started_at_ms,
            call.duration_ms,
            call.provider[:120],
            call.model[:240],
            call.source,
            int(call.stream),
            _clean_finish_reason(call.finish_reason),
            *(
                usage_data.get(key)
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                    "reported_tokens",
                    "estimated_tokens",
                    "generation_ms",
                    "measured_output_tokens",
                    "ttft_ms",
                    "timed_requests",
                )
            ),
            _clean_status_code(call.error_status_code),
            _clean_error_kind(call.error_kind),
        )
        with self._lock:
            connection = self._connect()
            connection.execute(
                """
                INSERT INTO llm_calls (
                    started_at_ms, duration_ms, provider, model, source, stream,
                    finish_reason, input_tokens, output_tokens, total_tokens,
                    cache_read_tokens, cache_write_tokens, reported_tokens,
                    estimated_tokens, generation_ms, measured_output_tokens,
                    ttft_ms, timed_requests, error_status_code, error_kind
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                values,
            )
            self._write_version += 1
            self._cached_payload_key = None
            self._cached_payload = None
            self._prune_if_due(connection)

    def _prune_if_due(self, connection: sqlite3.Connection) -> None:
        utc_day = int(time.time() // 86_400)
        self._writes_since_size_prune += 1
        prune_age = self._last_prune_utc_day != utc_day
        prune_size = self._writes_since_size_prune >= 1_024
        if not prune_age and not prune_size:
            return
        if prune_age:
            cutoff_ms = int(
                (datetime.now(timezone.utc) - timedelta(days=MAX_DAYS_RETAINED)).timestamp()
                * 1000
            )
            connection.execute("DELETE FROM llm_calls WHERE started_at_ms < ?", (cutoff_ms,))
        connection.execute(
            """
            DELETE FROM llm_calls
            WHERE id <= COALESCE((
                SELECT id FROM llm_calls ORDER BY id DESC LIMIT 1 OFFSET ?
            ), -1)
            """,
            (MAX_CALLS_RETAINED,),
        )
        self._last_prune_utc_day = utc_day
        self._writes_since_size_prune = 0

    def count(self) -> int:
        with self._lock:
            row = self._connect().execute("SELECT COUNT(*) AS count FROM llm_calls").fetchone()
        return int(row["count"] if row is not None else 0)

    def _aggregate(
        self,
        *,
        connection: sqlite3.Connection,
        start_ms: int | None,
        end_ms: int,
        group_by: tuple[str, ...] = (),
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        selected = f"{', '.join(group_by)}, " if group_by else ""
        where = "started_at_ms < ?"
        params: list[object] = [end_ms]
        if start_ms is not None:
            where = "started_at_ms >= ? AND started_at_ms < ?"
            params = [start_ms, end_ms]
        query = f"SELECT {selected}{_AGGREGATE_SQL} FROM llm_calls WHERE {where}"
        if group_by:
            query += f" GROUP BY {', '.join(group_by)} ORDER BY total_tokens DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        return list(connection.execute(query, params).fetchall())

    def _daily_rows(
        self,
        *,
        connection: sqlite3.Connection,
        start_ms: int,
        end_ms: int,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT llm_usage_local_day(started_at_ms, ?) AS date, source,
                   {_AGGREGATE_SQL}
            FROM llm_calls
            WHERE started_at_ms >= ? AND started_at_ms < ?
            GROUP BY date, source
            ORDER BY date, source
        """
        rows = connection.execute(
            query,
            (timezone_name, start_ms, end_ms),
        ).fetchall()
        by_date: dict[str, dict[str, Any]] = {}
        for row in rows:
            day = cast(str | None, row["date"])
            if day is None:
                continue
            values = _as_int_row(row)
            aggregate = by_date.setdefault(
                day,
                {"date": day, **_empty_totals(), "sources": {}},
            )
            for key, value in values.items():
                aggregate[key] += value
            aggregate["sources"][str(row["source"])] = values
        return list(by_date.values())

    @staticmethod
    def _midnight_ms(value: date, zone: timezone | ZoneInfo) -> int:
        return int(datetime.combine(value, datetime.min.time(), tzinfo=zone).timestamp() * 1000)

    def usage_payload(
        self,
        *,
        days: int = 371,
        timezone_name: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        zone = _zone(timezone_name)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        today = current.astimezone(zone).date()
        safe_days = max(1, days)
        zone_name = getattr(zone, "key", "UTC")

        with self._lock:
            data_version_row = self._connect().execute("PRAGMA data_version").fetchone()
            data_version = int(data_version_row[0]) if data_version_row is not None else 0
            write_version = self._write_version
            cache_key = (
                safe_days,
                zone_name,
                today.isoformat(),
                write_version,
                data_version,
            )
            if self._cached_payload_key == cache_key and self._cached_payload is not None:
                return deepcopy(self._cached_payload)

        connection = self._read_connection()
        try:
            connection.execute("BEGIN")
            end_ms = self._midnight_ms(today + timedelta(days=1), zone)
            retained_start = today - timedelta(days=MAX_DAYS_RETAINED - 1)
            retained_start_ms = self._midnight_ms(retained_start, zone)
            daily = self._daily_rows(
                connection=connection,
                start_ms=retained_start_ms,
                end_ms=end_ms,
                timezone_name=zone_name,
            )

            requested_start = today - timedelta(days=safe_days - 1)
            visible_days = [row for row in daily if row["date"] >= requested_start.isoformat()]
            last_30_start_ms = self._midnight_ms(today - timedelta(days=29), zone)

            last_30_date = (today - timedelta(days=29)).isoformat()
            last_365_date = (today - timedelta(days=364)).isoformat()
            all_totals = _sum_rows(daily)
            totals_30 = _sum_rows(row for row in daily if row["date"] >= last_30_date)
            totals_365 = _sum_rows(row for row in daily if row["date"] >= last_365_date)

            provider_rows = self._aggregate(
                connection=connection,
                start_ms=last_30_start_ms,
                end_ms=end_ms,
                group_by=("provider", "model"),
                limit=50,
            )
            providers_30d = [
                {
                    "provider": str(row["provider"]),
                    "model": str(row["model"]),
                    **_as_int_row(row),
                }
                for row in provider_rows
            ]

            active_dates = {
                date.fromisoformat(row["date"]) for row in daily if row["total_tokens"] > 0
            }
            current_streak = 0
            cursor = today
            while cursor in active_dates:
                current_streak += 1
                cursor -= timedelta(days=1)
            longest_streak = 0
            running_streak = 0
            previous: date | None = None
            for cursor in sorted(active_dates):
                running_streak = running_streak + 1 if previous == cursor - timedelta(days=1) else 1
                longest_streak = max(longest_streak, running_streak)
                previous = cursor

            latest = (
                connection
                .execute("SELECT MAX(started_at_ms) AS updated_at_ms FROM llm_calls")
                .fetchone()
            )
            updated_at_ms = int(latest["updated_at_ms"] or 0) if latest is not None else 0
            denominator = totals_30["cache_read_observed_input_tokens"]
            payload = {
                "days": visible_days,
                "total_tokens": all_totals["total_tokens"],
                "total_tokens_30d": totals_30["total_tokens"],
                "total_tokens_365d": totals_365["total_tokens"],
                "reported_tokens_30d": totals_30["reported_tokens"],
                "estimated_tokens_30d": totals_30["estimated_tokens"],
                "cache_read_tokens_30d": totals_30["cache_read_tokens"],
                "cache_read_observed_input_tokens_30d": denominator,
                "cache_read_rate_30d": (
                    totals_30["cache_read_tokens"] / denominator if denominator else None
                ),
                "peak_day_tokens": max(
                    (int(row["total_tokens"]) for row in daily),
                    default=0,
                ),
                "current_streak_days": current_streak,
                "longest_streak_days": longest_streak,
                "active_days_30d": sum(
                    1
                    for row in daily
                    if row["date"] >= last_30_date and row["total_tokens"] > 0
                ),
                "requests_30d": totals_30["requests"],
                "failed_requests_30d": totals_30["failed_requests"],
                "providers_30d": providers_30d,
                "updated_at": (
                    datetime.fromtimestamp(updated_at_ms / 1000, timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                    if updated_at_ms
                    else None
                ),
            }
        finally:
            connection.close()

        with self._lock:
            latest_data_version_row = self._connect().execute("PRAGMA data_version").fetchone()
            latest_data_version = (
                int(latest_data_version_row[0])
                if latest_data_version_row is not None
                else 0
            )
            if self._write_version == write_version and latest_data_version == data_version:
                self._cached_payload_key = cache_key
                self._cached_payload = payload
        return deepcopy(payload)

    def recent_calls(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return bounded metadata rows for diagnostics; never returns content."""
        safe_limit = min(max(1, limit), 1_000)
        with self._lock:
            rows = (
                self._connect()
                .execute(
                    """
                SELECT * FROM llm_calls ORDER BY started_at_ms DESC, id DESC LIMIT ?
                """,
                    (safe_limit,),
                )
                .fetchall()
            )
        return [dict(row) for row in rows]

    def record_many(self, calls: Iterable[LLMCallRecord]) -> None:
        for call in calls:
            self.record(call)
