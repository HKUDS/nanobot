#!/usr/bin/env python3
"""
Analyze prefix cache hit rate from API logs.

This script analyzes the request_messages in audit logs to calculate
potential prefix caching benefits.
"""

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from datetime import datetime

from nanobot.providers.audit_logger import APILogger


def extract_session_info(request_messages: str) -> dict:
    """Extract session info from formatted request messages."""
    info = {"channel": None, "chat_id": None}

    for line in request_messages.split("\n"):
        if line.startswith("Channel: "):
            info["channel"] = line[9:].strip()
        elif line.startswith("Chat ID: "):
            info["chat_id"] = line[9:].strip()

    return info


def extract_system_prompt(request_messages: str) -> str:
    """Extract system prompt from formatted request messages."""
    lines = request_messages.split("\n")
    system_lines = []
    in_system = False

    for line in lines:
        if line.startswith("system: "):
            in_system = True
            system_lines.append(line[8:])  # Remove "system: " prefix
        elif line.startswith("user: ") or line.startswith("assistant: "):
            in_system = False
        elif in_system:
            system_lines.append(line)

    return "\n".join(system_lines)


def compute_prefix_hash(content: str) -> str:
    """Compute hash of content for comparison."""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def group_requests_into_sessions(
    requests: list[dict],
    gap_threshold_seconds: int = 300,  # 5 minutes default
) -> list[list[dict]]:
    """
    Group requests into sessions based on time gaps.

    Args:
        requests: List of requests with timestamp
        gap_threshold_seconds: Max gap between requests in same session

    Returns:
        List of sessions (each session is a list of requests)
    """
    if not requests:
        return []

    # Sort by timestamp
    sorted_requests = sorted(requests, key=lambda r: r.get("timestamp", ""))

    sessions: list[list[dict]] = []
    current_session: list[dict] = []
    last_time: datetime | None = None

    for req in sorted_requests:
        ts_str = req.get("timestamp", "")
        try:
            req_time = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError):
            continue

        if last_time is None:
            # First request
            current_session = [req]
        elif (req_time - last_time).total_seconds() <= gap_threshold_seconds:
            # Same session
            current_session.append(req)
        else:
            # New session
            sessions.append(current_session)
            current_session = [req]

        last_time = req_time

    # Don't forget the last session
    if current_session:
        sessions.append(current_session)

    return sessions


def analyze_cache_by_session(
    log_dir: Path | None = None,
    days: int = 7,
    gap_threshold_seconds: int = 300,
) -> dict:
    """
    Analyze cache hit rate grouped by sessions (conversations).

    Args:
        log_dir: Log directory path
        days: Number of days to analyze
        gap_threshold_seconds: Gap threshold for session separation

    Returns:
        dict with session-based cache statistics
    """
    from datetime import timedelta

    log_dir = log_dir or APILogger._get_default_log_dir()

    if not log_dir.exists():
        return {"error": "No log files found"}

    cutoff_date = datetime.now() - timedelta(days=days)

    # Collect all requests
    all_requests: list[dict] = []

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
                        request_messages = data.get("request_messages", "")
                        system_prompt = extract_system_prompt(request_messages)

                        all_requests.append({
                            "timestamp": data.get("timestamp"),
                            "model": data.get("model"),
                            "prompt_tokens": data.get("prompt_tokens", 0),
                            "system_prompt": system_prompt,
                            "system_prompt_hash": compute_prefix_hash(system_prompt) if system_prompt else "",
                            "request_messages": request_messages,
                        })
                    except (json.JSONDecodeError, TypeError):
                        continue
        except (ValueError, IOError):
            continue

    # Group into sessions
    sessions = group_requests_into_sessions(all_requests, gap_threshold_seconds)

    # Analyze each session
    session_stats = []
    total_requests = 0

    for i, session in enumerate(sessions, 1):
        if not session:
            continue

        # Within this session, calculate cache hits
        seen_hashes: set[str] = set()
        session_hits = 0
        session_misses = 0
        session_tokens = 0

        for req in session:
            prefix_hash = req.get("system_prompt_hash", "")
            if not prefix_hash:
                continue

            total_requests += 1
            session_tokens += req.get("prompt_tokens", 0)

            if prefix_hash in seen_hashes:
                session_hits += 1
            else:
                session_misses += 1
                seen_hashes.add(prefix_hash)

        session_total = session_hits + session_misses
        session_stats.append({
            "session_id": i,
            "requests": len(session),
            "hits": session_hits,
            "misses": session_misses,
            "hit_rate": (session_hits / session_total * 100) if session_total > 0 else 0,
            "total_tokens": session_tokens,
            "start_time": session[0].get("timestamp") if session else None,
            "end_time": session[-1].get("timestamp") if session else None,
            "model": session[0].get("model") if session else "unknown",
            "unique_system_prompts": len(seen_hashes),
        })

    return {
        "total_sessions": len(sessions),
        "total_requests": total_requests,
        "sessions": session_stats,
        "gap_threshold_seconds": gap_threshold_seconds,
    }


def analyze_cache_hit_rate(
    log_dir: Path | None = None,
    days: int = 7,
) -> dict:
    """
    Analyze potential prefix cache hit rate.

    Returns:
        dict with cache statistics
    """
    from datetime import timedelta

    log_dir = log_dir or APILogger._get_default_log_dir()

    if not log_dir.exists():
        return {"error": "No log files found"}

    cutoff_date = datetime.now() - timedelta(days=days)

    # Track prefix usage
    prefix_hashes: dict[str, list[dict]] = defaultdict(list)
    total_requests = 0
    total_prompt_tokens = 0
    system_prompt_tokens = 0

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
                        total_requests += 1
                        total_prompt_tokens += data.get("prompt_tokens", 0)

                        request_messages = data.get("request_messages", "")
                        if not request_messages:
                            continue

                        # Extract system prompt
                        system_prompt = extract_system_prompt(request_messages)
                        if system_prompt:
                            prefix_hash = compute_prefix_hash(system_prompt)
                            prefix_hashes[prefix_hash].append({
                                "timestamp": data.get("timestamp"),
                                "model": data.get("model"),
                                "prompt_tokens": data.get("prompt_tokens", 0),
                                "system_prompt_length": len(system_prompt),
                            })
                            # Estimate system prompt tokens (rough: 4 chars per token)
                            system_prompt_tokens += len(system_prompt) // 4

                    except (json.JSONDecodeError, TypeError):
                        continue

        except (ValueError, IOError):
            continue

    # Calculate cache statistics
    cache_stats = {
        "total_requests": total_requests,
        "total_prompt_tokens": total_prompt_tokens,
        "estimated_system_tokens": system_prompt_tokens,
        "unique_prefixes": len(prefix_hashes),
        "prefix_details": [],
    }

    # Calculate hits and misses
    total_hits = 0
    total_misses = 0
    potential_saved_tokens = 0

    for prefix_hash, requests in prefix_hashes.items():
        if len(requests) > 1:
            # First request is a miss, rest are hits
            misses = 1
            hits = len(requests) - 1

            total_hits += hits
            total_misses += misses

            # Calculate potential token savings
            avg_tokens = sum(r["prompt_tokens"] for r in requests) / len(requests)
            system_tokens = requests[0].get("system_prompt_length", 0) // 4
            potential_saved_tokens += hits * system_tokens

            cache_stats["prefix_details"].append({
                "prefix_hash": prefix_hash,
                "requests": len(requests),
                "hits": hits,
                "misses": misses,
                "avg_prompt_tokens": int(avg_tokens),
                "system_tokens_estimated": system_tokens,
                "first_request": requests[0]["timestamp"],
                "model": requests[0]["model"],
                "system_prompt_preview": extract_system_prompt(
                    requests[0].get("request_messages", "")
                )[:200] if requests[0].get("request_messages") else "N/A",
            })

            # Add system_prompt_length to each request for later analysis
            for r in requests:
                if "request_messages" in r:
                    r["system_prompt_length"] = len(extract_system_prompt(r.get("request_messages", "")))
        else:
            total_misses += 1

    # Final statistics
    total_requests_with_prefix = total_hits + total_misses
    cache_stats["cache_analysis"] = {
        "total_hits": total_hits,
        "total_misses": total_misses,
        "hit_rate": (total_hits / total_requests_with_prefix * 100) if total_requests_with_prefix > 0 else 0,
        "potential_token_savings": potential_saved_tokens,
        "savings_percentage": (potential_saved_tokens / total_prompt_tokens * 100) if total_prompt_tokens > 0 else 0,
    }

    # Sort prefix details by number of requests
    cache_stats["prefix_details"].sort(key=lambda x: x["requests"], reverse=True)

    return cache_stats


def print_cache_report(stats: dict) -> None:
    """Print a formatted cache analysis report."""
    print("=" * 70)
    print("  Prefix Cache Hit Rate Analysis")
    print("=" * 70)

    if "error" in stats:
        print(f"\n  Error: {stats['error']}")
        return

    print(f"\n  Overview:")
    print(f"    Total Requests:        {stats['total_requests']:,}")
    print(f"    Total Prompt Tokens:   {stats['total_prompt_tokens']:,}")
    print(f"    Est. System Tokens:    {stats['estimated_system_tokens']:,}")
    print(f"    Unique Prefixes:       {stats['unique_prefixes']}")

    analysis = stats.get("cache_analysis", {})
    print(f"\n  Cache Analysis:")
    print(f"    Cache Hits:            {analysis.get('total_hits', 0):,}")
    print(f"    Cache Misses:          {analysis.get('total_misses', 0):,}")
    print(f"    Hit Rate:              {analysis.get('hit_rate', 0):.1f}%")
    print(f"    Potential Token Savings: {analysis.get('potential_token_savings', 0):,}")
    print(f"    Savings %:             {analysis.get('savings_percentage', 0):.1f}%")

    print(f"\n  Top Prefixes by Request Count:")
    print("-" * 70)

    for i, detail in enumerate(stats.get("prefix_details", [])[:10], 1):
        print(f"\n  [{i}] Hash: {detail['prefix_hash']}")
        print(f"      Requests: {detail['requests']} (Hits: {detail['hits']}, Misses: {detail['misses']})")
        print(f"      Avg Prompt Tokens: {detail['avg_prompt_tokens']:,}")
        print(f"      Est. System Tokens: {detail['system_tokens_estimated']:,}")
        print(f"      Model: {detail['model']}")

    print("\n" + "=" * 70)


def main():
    """Run cache analysis."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze prefix cache hit rate")
    parser.add_argument("--days", type=int, default=7, help="Days to analyze (default: 7)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    stats = analyze_cache_hit_rate(days=args.days)

    if args.json:
        print(json.dumps(stats, indent=2, default=str))
    else:
        print_cache_report(stats)


if __name__ == "__main__":
    main()
