"""Helpers for routing bound cron turns back through their origin session."""

from __future__ import annotations

from typing import Any

from nanobot.cron.types import CronJob


def origin_delivery_context(job: CronJob) -> tuple[str, str, dict[str, Any]]:
    """Return ``(channel, chat_id, metadata)`` for a session-bound cron job."""
    payload = job.payload
    if not payload.origin_channel or not payload.origin_chat_id:
        raise ValueError(f"cron job {job.id} is missing origin delivery context")
    return payload.origin_channel, payload.origin_chat_id, dict(payload.origin_metadata or {})


def configured_delivery_context(job: CronJob) -> tuple[str, str, dict[str, Any]]:
    """Return the configured result route, falling back to the origin route."""
    payload = job.payload
    if payload.delivery_channel is None and payload.delivery_chat_id is None:
        return origin_delivery_context(job)
    if not payload.delivery_channel or not payload.delivery_chat_id:
        raise ValueError(f"cron job {job.id} has incomplete delivery target")
    return (
        payload.delivery_channel,
        payload.delivery_chat_id,
        dict(payload.delivery_metadata or {}),
    )
