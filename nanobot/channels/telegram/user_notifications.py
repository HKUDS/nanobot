"""Classify owner-facing automation receipts without exposing routing metadata.

A receipt is recorded only AFTER Telegram confirms the send. This module never
publishes a message, retries a send, or accepts arbitrary client event payloads.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, cast


def notification_receipt_id(metadata: Mapping[str, Any], text: str) -> str | None:
    for key, field, source in (
        ("_local_trigger", "delivery_id", "trigger"),
        ("_cron_trigger", "run_id", "cron"),
        ("_user_notification", "id", "notification"),
    ):
        value = metadata.get(key)
        if not isinstance(value, dict):
            continue
        identity = cast(dict[str, Any], value).get(field)
        if isinstance(identity, str) and 0 < len(identity) <= 256 and text.strip():
            digest = hashlib.sha256(f"{source}:{identity}:{text}".encode()).hexdigest()
            return f"user-{digest}"
    return None
