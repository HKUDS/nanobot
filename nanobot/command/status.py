"""Structured status snapshots for the /status command."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from nanobot.bus.outbound_events import CommandLine
from nanobot.command.results import line

if TYPE_CHECKING:
    from nanobot.llm_usage.types import LLMUsage
    from nanobot.utils.searchusage import SearchUsageInfo


def search_lines(usage: SearchUsageInfo) -> list[CommandLine]:
    rows = [line("search.provider", provider=usage.provider)]
    if not usage.supported:
        return [*rows, line("search.unsupported")]
    if usage.error:
        return [*rows, line("search.unavailable", error=usage.error)]
    if usage.used is not None:
        if usage.limit is None:
            rows.append(line("search.used", count=usage.used))
        else:
            rows.append(line("search.quota", count=usage.used, limit=usage.limit))
    for key, count in (
        ("search.search", usage.search_used), ("search.extract", usage.extract_used),
        ("search.crawl", usage.crawl_used), ("search.remaining", usage.remaining),
    ):
        if count is not None:
            rows.append(line(key, count=count))
    if usage.reset_date:
        rows.append(line("search.reset", date=usage.reset_date))
    return rows


def status_lines(
    *, version: str, model: str, start_time: float, last_usage: LLMUsage | None,
    context_window_tokens: int, session_msg_count: int, context_tokens: int | None,
    search_usage: SearchUsageInfo | None = None, active_task_count: int = 0,
    recorded_context: bool = False,
) -> list[CommandLine]:
    seconds = max(int(time.time() - start_time), 0)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    incoming = last_usage.input_tokens if last_usage else 0
    outgoing = last_usage.output_tokens if last_usage else 0
    rows = [
        line("status.version", version=version),
        line("status.model", model=model),
        line("status.tokens", incoming=incoming, outgoing=outgoing),
    ]
    if last_usage and last_usage.cache_read_tokens and incoming:
        rows.append(line("status.cache", percent=last_usage.cache_read_tokens * 100 // incoming))
    if context_tokens is not None and context_window_tokens > 0:
        rows.append(line(
            "status.context_recorded" if recorded_context else "status.context",
            used=context_tokens,
            total=context_window_tokens,
            percent=min(100, (100 * context_tokens + context_window_tokens // 2) // context_window_tokens),
        ))
    elif last_usage is not None and last_usage.context_tokens is not None:
        rows.append(line("status.context_previous", used=last_usage.context_tokens))
    else:
        rows.append(line("status.context_unavailable"))
    rows.extend((
        line("status.session", count=session_msg_count),
        line("status.uptime", uptime=f"{hours}:{minutes:02}:{secs:02}"),
        line("status.tasks", count=active_task_count),
    ))
    if search_usage:
        rows.extend(search_lines(search_usage))
    return rows
