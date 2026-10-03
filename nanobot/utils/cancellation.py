"""Async cancellation helpers."""

from __future__ import annotations

import asyncio


def task_is_cancelling() -> bool:
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0
