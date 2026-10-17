"""Bounded storage for scheduled results; never reruns an agent turn."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from loguru import logger

from nanobot.bus.delivery import DeliveryRequest
from nanobot.bus.events import OutboundMessage

DeliveryStatus = Literal["pending", "sending", "sent", "failed", "unknown"]
RETRY_SECONDS = 30
MAX_AGE_SECONDS = 3600
MAX_PENDING = 256
MAX_PAYLOAD_BYTES = 1024 * 1024
RETENTION_SECONDS = 7 * 86400


class DeliveryOutbox:
    """One gateway lease owns this instance store. Terminal rows contain no message text."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialized = False

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA secure_delete=ON")
        db.row_factory = sqlite3.Row
        try:
            with db:
                if not self._initialized:
                    db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
                        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, channel TEXT NOT NULL,
                        chat_id TEXT NOT NULL,
                        payload TEXT, status TEXT NOT NULL, created REAL NOT NULL,
                        updated REAL NOT NULL, next_attempt REAL NOT NULL, error TEXT
                    )""")
                    # A crash during send cannot tell us whether the service accepted it.
                    interrupted = db.execute("SELECT id, run_id, channel FROM deliveries WHERE status='sending'").fetchall()
                    db.execute("""UPDATE deliveries SET status='unknown', payload=NULL,
                        error='interrupted_send', updated=? WHERE status='sending'""", (time.time(),))
                    for row in interrupted:
                        logger.warning("Channel delivery: run={} delivery={} channel={} status=unknown error=interrupted_send",
                                       row["run_id"], row["id"], row["channel"])
                yield db
            self._initialized = True
        finally:
            db.close()

    def record(self, msg: OutboundMessage) -> None:
        """Commit before queue acceptance. Do not store runtime events or empty replies."""
        if msg.delivery is None or msg.event is not None or not (msg.content.strip() or msg.media):
            return
        if msg.delivery_id is not None:
            return
        delivery_id = uuid.uuid4().hex
        data = asdict(msg)
        data["delivery_id"] = delivery_id
        # Cron prompt audit data is already in the run record, not routing context.
        data["metadata"] = {key: value for key, value in msg.metadata.items()
                            if not key.startswith("_cron_")}
        payload = json.dumps(data, ensure_ascii=False)
        if len(payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("Scheduled delivery exceeds the 1 MiB queue limit")
        now = time.time()
        with self._connect() as db:
            self._prune(db, now)
            count = db.execute(
                "SELECT count(*) FROM deliveries WHERE status IN ('pending','sending')",
            ).fetchone()[0]
            if count >= MAX_PENDING:
                raise RuntimeError("Scheduled delivery queue is full; check channel connectivity")
            db.execute("INSERT INTO deliveries VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, NULL)",
                       (delivery_id, msg.delivery.run_id, msg.channel, msg.chat_id, payload, now, now, now))
        msg.delivery_id = delivery_id
        self._log(msg, "pending")

    @staticmethod
    def _prune(db: sqlite3.Connection, now: float) -> None:
        expired = db.execute("""UPDATE deliveries SET status='failed', payload=NULL,
            error='expired', updated=? WHERE status='pending' AND created<=?""",
                             (now, now - MAX_AGE_SECONDS)).rowcount
        if expired:
            logger.warning("{} scheduled deliveries expired; check the instance delivery store", expired)
        db.execute("DELETE FROM deliveries WHERE status NOT IN ('pending','sending') AND updated<?",
                   (now - RETENTION_SECONDS,))
        db.execute("""DELETE FROM deliveries WHERE id IN (
            SELECT id FROM deliveries WHERE status NOT IN ('pending','sending')
            ORDER BY updated DESC LIMIT -1 OFFSET 1000)""")

    def ready(self) -> list[OutboundMessage]:
        if not self.path.exists():
            return []
        now = time.time()
        with self._connect() as db:
            self._prune(db, now)
            rows = db.execute("""SELECT payload FROM deliveries WHERE status='pending'
                AND next_attempt<=? ORDER BY created LIMIT ?""", (now, MAX_PENDING)).fetchall()
        messages: list[OutboundMessage] = []
        for row in rows:
            data = json.loads(row["payload"])
            data["delivery"] = DeliveryRequest(**data["delivery"])
            messages.append(OutboundMessage(**data))
        return messages

    def claim(self, msg: OutboundMessage) -> bool:
        """Only one queued copy may start an attempt; expired messages never start."""
        now = time.time()
        with self._connect() as db:
            self._prune(db, now)
            changed = db.execute("""UPDATE deliveries SET status='sending', updated=?
                WHERE id=? AND status='pending' AND next_attempt<=?
                AND NOT EXISTS (SELECT 1 FROM deliveries AS older
                    WHERE older.channel=deliveries.channel AND older.chat_id=deliveries.chat_id
                    AND older.rowid<deliveries.rowid AND older.status IN ('pending','sending'))""",
                                 (now, msg.delivery_id, now)).rowcount
        return changed == 1

    def finish(self, msg: OutboundMessage, status: DeliveryStatus, error: str | None = None) -> None:
        now = time.time()
        with self._connect() as db:
            changed = db.execute("""UPDATE deliveries SET status=?, error=?, updated=?, next_attempt=?,
                payload=CASE WHEN ?='pending' THEN payload ELSE NULL END
                WHERE id=? AND status IN ('pending','sending')""",
                                 (status, error, now, now + RETRY_SECONDS, status, msg.delivery_id)).rowcount
            self._prune(db, now)
        if changed:
            self._log(msg, status, error)

    @staticmethod
    def _log(msg: OutboundMessage, status: DeliveryStatus, error: str | None = None) -> None:
        logger.info("Channel delivery: run={} delivery={} channel={} status={} error={}",
                    msg.delivery.run_id if msg.delivery else "-", msg.delivery_id,
                    msg.channel, status, error or "-")
