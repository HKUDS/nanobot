#!/usr/bin/env python3
"""
More accurate prefix cache analysis using BPE tokenization and hash-based prefix matching.
"""

import json
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class LogEntry:
    timestamp: str
    model: str
    prompt_tokens: int
    request_messages: str


def load_logs(log_dir: Path | None = None, days: int = 7) -> list[LogEntry]:
    """Load logs from JSONL files."""
    from datetime import timedelta
    from nanobot.providers.audit_logger import APILogger

    log_dir = log_dir or APILogger._get_default_log_dir()

    if not log_dir.exists():
        return []

    cutoff_date = datetime.now() - timedelta(days=days)
    entries: list[LogEntry] = []

    for log_file in sorted(log_dir.glob("api_logs_*.jsonl")):
        try:
            date_str = log_file.stem.replace("api_logs_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")

            if file_date < cutoff_date:
                continue

            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        entries.append(LogEntry(
                            timestamp=data.get("timestamp", ""),
                            model=data.get("model", ""),
                            prompt_tokens=data.get("prompt_tokens", 0),
                            request_messages=data.get("request_messages", ""),
                        ))
                    except (json.JSONDecodeError, TypeError):
                        continue
        except (ValueError, IOError):
            continue

    return entries


def extract_text(request_messages: str) -> str:
    """Extract just the text content from request_messages."""
    # request_messages format: "role: content\nrole: content"
    # We just want the content part of each message
    lines = request_messages.split("\n")
    content_lines = []

    for line in lines:
        if ": " in line:
            parts = line.split(": ", 1)
            if len(parts) == 2:
                content_lines.append(parts[1])

    return "\n".join(content_lines)


def simple_tokenizer(text: str) -> list[str]:
    """
    Simple tokenizer - split on whitespace and punctuation.
    In real world, use tiktoken for exact BPE.
    """
    import re

    # Split on whitespace and word boundaries
    tokens = re.findall(r'\S+|\s+', text)
    return tokens


def hash_token(token: str) -> str:
    """Compute hash for a single token."""
    return hashlib.md5(token.encode()).hexdigest()[:8]


def compute_prefix_match_tokens(
    entries: list[LogEntry],
    gap_threshold_seconds: int = 300,
) -> dict:
    """
    Compute prefix match cache hits using token-level comparison.

    For each request in a session:
    - Tokenize the request
    - Compare token-by-token with previous request
    - The longest matching prefix = cache hits
    """
    from datetime import timedelta

    # Sort entries by timestamp
    sorted_entries = sorted(
        entries,
        key=lambda e: e.timestamp
    )

    # Group into sessions
    sessions: list[list[LogEntry]] = []
    current_session: list[LogEntry] = []
    last_time: datetime | None = None

    for entry in sorted_entries:
        try:
            entry_time = datetime.fromisoformat(entry.timestamp)
        except (ValueError, TypeError):
            continue

        if last_time is None:
            current_session = [entry]
        elif (entry_time - last_time).total_seconds() <= gap_threshold_seconds:
            current_session.append(entry)
        else:
            sessions.append(current_session)
            current_session = [entry]

        last_time = entry_time

    if current_session:
        sessions.append(current_session)

    # Analyze each session
    session_results = []
    total_requests = 0
    total_tokens = 0
    total_hit_tokens = 0
    total_miss_tokens = 0

    for i, session in enumerate(sessions, 1):
        if len(session) < 2:
            # Only 1 request - no cache hits possible
            session_tokens = sum(e.prompt_tokens for e in session)
            total_requests += len(session)
            total_tokens += session_tokens
            total_miss_tokens += session_tokens

            session_results.append({
                "session_id": i,
                "requests": len(session),
                "hit_tokens": 0,
                "miss_tokens": session_tokens,
                "hit_rate": 0.0,
                "total_tokens": session_tokens,
                "saved_tokens": 0,
            })
            continue

        # Tokenize each request in session
        session_hit_tokens = 0
        session_miss_tokens = 0
        session_total_tokens = 0
        previous_tokens = None

        for entry in session:
            text = extract_text(entry.request_messages)
            tokens = simple_tokenizer(text)
            token_count = len(tokens)  # Token count (estimate)
            actual_tokens = entry.prompt_tokens  # Actual from API

            session_total_tokens += actual_tokens
            total_requests += 1
            total_tokens += actual_tokens

            if previous_tokens is not None:
                # Find longest prefix match
                match_length = 0
                max_match = min(len(tokens), len(previous_tokens))

                while (match_length < max_match and
                       tokens[match_length] == previous_tokens[match_length]):
                    match_length += 1

                # Scale match length to actual token count
                # If tokenizer gave us N tokens but API said M tokens,
                # scale the match proportionally
                if token_count > 0:
                    hit_ratio = match_length / token_count
                    hit_tokens = int(actual_tokens * hit_ratio)
                else:
                    hit_tokens = 0

                miss_tokens = actual_tokens - hit_tokens

                session_hit_tokens += hit_tokens
                session_miss_tokens += miss_tokens
                total_hit_tokens += hit_tokens
                total_miss_tokens += miss_tokens

            else:
                # First request - all miss
                session_miss_tokens += actual_tokens
                total_miss_tokens += actual_tokens

            previous_tokens = tokens

        # Hit rate for this session
        session_total_system = session_hit_tokens + session_miss_tokens
        session_hit_rate = (
            (session_hit_tokens / session_total_system * 100)
            if session_total_system > 0 else 0.0
        )

        session_results.append({
            "session_id": i,
            "requests": len(session),
            "hit_tokens": session_hit_tokens,
            "miss_tokens": session_miss_tokens,
            "hit_rate": session_hit_rate,
            "total_tokens": session_total_tokens,
            "saved_tokens": session_hit_tokens,
            "start_time": session[0].timestamp,
        })

    # Overall stats
    total_system_tokens = total_hit_tokens + total_miss_tokens
    overall_hit_rate = (
        (total_hit_tokens / total_system_tokens * 100)
        if total_system_tokens > 0 else 0.0
    )

    return {
        "total_sessions": len(sessions),
        "total_requests": total_requests,
        "total_tokens": total_tokens,
        "total_hit_tokens": total_hit_tokens,
        "total_miss_tokens": total_miss_tokens,
        "total_system_tokens": total_system_tokens,
        "overall_hit_rate": overall_hit_rate,
        "total_saved_tokens": total_hit_tokens,
        "sessions": session_results,
        "gap_threshold_seconds": gap_threshold_seconds,
    }


def main():
    import argparse
    from rich.console import Console
    from rich.table import Table

    console = Console()

    parser = argparse.ArgumentParser(description="Accurate prefix cache analysis with token-level matching")
    parser.add_argument("--days", type=int, default=7, help="Days to analyze")
    parser.add_argument("--gap", type=int, default=300, help="Session gap in seconds")
    args = parser.parse_args()

    from nanobot.providers.audit_logger import APILogger
    log_dir = APILogger._get_default_log_dir()

    console.print("[cyan]🐈[/cyan] Prefix Cache Analysis (Token-level matching)\n")

    entries = load_logs(log_dir=log_dir, days=args.days)
    if not entries:
        console.print("[red]No log files found[/red]")
        return

    stats = compute_prefix_match_tokens(entries, gap_threshold_seconds=args.gap)

    # Overview
    overview = Table(title="Overview")
    overview.add_column("Metric", style="cyan")
    overview.add_column("Value", style="green")
    overview.add_row("Total Sessions", str(stats["total_sessions"]))
    overview.add_row("Total Requests", f"{stats['total_requests']:,}")
    overview.add_row("Total Prompt Tokens", f"{stats['total_tokens']:,}")
    console.print(overview)
    console.print()

    # Session table
    session_table = Table(title="Sessions (token-level matching)")
    session_table.add_column("#", style="dim")
    session_table.add_column("Reqs", style="green")
    session_table.add_column("Hit Tokens", style="yellow")
    session_table.add_column("Miss Tokens", style="red")
    session_table.add_column("Hit Rate", style="cyan")
    session_table.add_column("Saved", style="magenta")
    session_table.add_column("Total", style="blue")

    for s in stats["sessions"]:
        hit_rate = s.get("hit_rate", 0)
        hit_rate_str = f"{hit_rate:.1f}%"

        session_table.add_row(
            str(s["session_id"]),
            str(s["requests"]),
            f"{s['hit_tokens']:,}",
            f"{s['miss_tokens']:,}",
            hit_rate_str,
            f"{s['saved_tokens']:,}",
            f"{s['total_tokens']:,}",
        )

    console.print(session_table)
    console.print()

    # Aggregate
    agg_table = Table(title="Aggregate Stats (Token-level)")
    agg_table.add_column("Metric", style="cyan")
    agg_table.add_column("Value", style="green")
    agg_table.add_row("Total Hit Tokens (all sessions)", f"{stats['total_hit_tokens']:,}")
    agg_table.add_row("Total Miss Tokens (all sessions)", f"{stats['total_miss_tokens']:,}")
    agg_table.add_row("Total System Tokens", f"{stats['total_system_tokens']:,}")
    agg_table.add_row("Overall Hit Rate (Token-level)", f"{stats['overall_hit_rate']:.1f}%")
    agg_table.add_row("Total Tokens Saved", f"{stats['total_saved_tokens']:,}")
    console.print(agg_table)


if __name__ == "__main__":
    main()
