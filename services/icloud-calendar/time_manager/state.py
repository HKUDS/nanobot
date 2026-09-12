from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .core import Event, Notice

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS events (
  key TEXT PRIMARY KEY, payload TEXT NOT NULL, source_hash TEXT NOT NULL,
  start TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  missing_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notices (
  key TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT NOT NULL, delivered_at TEXT, expired_at TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(events)")}
        if "missing_count" not in columns:
            self.db.execute("ALTER TABLE events ADD COLUMN missing_count INTEGER NOT NULL DEFAULT 0")
        notice_columns = {row[1] for row in self.db.execute("PRAGMA table_info(notices)")}
        if "expired_at" not in notice_columns:
            self.db.execute("ALTER TABLE notices ADD COLUMN expired_at TEXT")
        self.db.commit()
        try:
            path.parent.chmod(0o700)
            path.chmod(0o600)
        except OSError:
            pass

    def close(self) -> None:
        self.db.close()

    def is_initialized(self) -> bool:
        return self.meta("initialized") == "1"

    def meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    def reconcile(self, events: Iterable[Event], now: datetime, window_start: datetime, window_end: datetime) -> tuple[list[Event], list[Event], list[Event]]:
        stamp = now.isoformat()
        incoming = {event.key: event for event in events}
        created: list[Event] = []
        changed: list[Event] = []
        removed: list[Event] = []
        with self.db:
            for event in incoming.values():
                row = self.db.execute("SELECT source_hash,active FROM events WHERE key=?", (event.key,)).fetchone()
                digest = event.hash()
                payload = json.dumps(asdict(event), ensure_ascii=False)
                if row is None:
                    created.append(event)
                    self.db.execute("INSERT INTO events(key,payload,source_hash,start,active,first_seen,last_seen,missing_count) VALUES(?,?,?,?,?,?,?,0)", (event.key, payload, digest, event.start, 1, stamp, stamp))
                else:
                    if not row["active"]:
                        created.append(event)
                    elif row["source_hash"] != digest:
                        changed.append(event)
                    self.db.execute("UPDATE events SET payload=?,source_hash=?,start=?,active=1,last_seen=?,missing_count=0 WHERE key=?", (payload, digest, event.start, stamp, event.key))

            rows = self.db.execute("SELECT key,payload,start,missing_count FROM events WHERE active=1 AND last_seen<>?", (stamp,)).fetchall()
            for row in rows:
                try:
                    start = datetime.fromisoformat(row["start"])
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=window_start.tzinfo)
                except ValueError:
                    continue
                if window_start <= start < window_end:
                    missing_count = int(row["missing_count"]) + 1
                    if missing_count >= 3:
                        data = json.loads(row["payload"])
                        data["attendees"] = tuple(data.get("attendees", ()))
                        data["categories"] = tuple(data.get("categories", ()))
                        removed.append(Event(**data))
                        self.db.execute("UPDATE events SET active=0,last_seen=?,missing_count=? WHERE key=?", (stamp, missing_count, row["key"]))
                    else:
                        self.db.execute("UPDATE events SET missing_count=? WHERE key=?", (missing_count, row["key"]))
        return created, changed, removed

    def active_events(self) -> list[Event]:
        rows = self.db.execute("SELECT payload FROM events WHERE active=1").fetchall()
        result = []
        for row in rows:
            data = json.loads(row["payload"])
            data["attendees"] = tuple(data.get("attendees", ()))
            data["categories"] = tuple(data.get("categories", ()))
            result.append(Event(**data))
        return result

    def reserve_notice(self, notice: Notice, now: datetime) -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT INTO notices(key,kind,payload,created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,expired_at=NULL "
                "WHERE notices.delivered_at IS NULL",
                (notice.key, notice.kind, json.dumps({"title": notice.title, "urgency": notice.urgency, **notice.payload}, ensure_ascii=False), now.isoformat()),
            )
        return cursor.rowcount == 1

    def expire_transient_notices(self, valid_keys: set[str], now: datetime) -> None:
        transient = {"event_reminder", "missing_information", "conflict", "morning_briefing",
                     "bedtime_reminder", "wake_reminder", "post_event"}
        rows = self.db.execute(
            "SELECT key,kind FROM notices WHERE delivered_at IS NULL AND expired_at IS NULL"
        ).fetchall()
        with self.db:
            self.db.executemany(
                "UPDATE notices SET expired_at=? WHERE key=?",
                [(now.isoformat(), row["key"]) for row in rows
                 if row["kind"] in transient and row["key"] not in valid_keys],
            )

    def pending_notices(self, limit: int = 20) -> list[Notice]:
        rows = self.db.execute(
            "SELECT key,kind,payload FROM notices WHERE delivered_at IS NULL AND expired_at IS NULL "
            "ORDER BY CASE json_extract(payload, '$.urgency') WHEN 'critical' THEN 0 ELSE 1 END, created_at LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            result.append(Notice(
                key=row["key"], kind=row["kind"], urgency=payload.pop("urgency", "normal"),
                title=payload.pop("title", row["kind"]), payload=payload,
            ))
        return result

    def mark_delivered(self, key: str, now: datetime) -> None:
        with self.db:
            self.db.execute("UPDATE notices SET delivered_at=? WHERE key=?", (now.isoformat(), key))
