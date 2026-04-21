"""
Nanobot status dashboard server.

Runs a lightweight HTTP server on port 18791 that serves a single-page
status dashboard and a JSON /api/status endpoint.

Usage:
    python -m nanobot.dashboard.server
    python -m nanobot.dashboard.server --port 18791
    python -m nanobot.dashboard.server --host 127.0.0.1 --port 18791
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

try:
    from prometheus_client import (
        Counter, Histogram, Gauge, generate_latest,
        CONTENT_TYPE_LATEST, CollectorRegistry, REGISTRY,
    )
    _PROM_AVAILABLE = True
except ImportError:
    _PROM_AVAILABLE = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_NANOBOT_DIR = Path.home() / ".nanobot"
_WORKSPACE_DIR = _NANOBOT_DIR / "workspace"
_SESSIONS_DIR = _WORKSPACE_DIR / "sessions"
_MEMORY_DIR = _WORKSPACE_DIR / "memory"
_MEMORY_FILE = _MEMORY_DIR / "MEMORY.md"
_HISTORY_FILE = _MEMORY_DIR / "HISTORY.md"
_CRON_JOBS_FILE = _WORKSPACE_DIR / "cron_jobs.json"
_SKILLS_DIR = _WORKSPACE_DIR / "skills"
_AUDIT_FILE = _WORKSPACE_DIR / "audit.jsonl"
_PENDING_MESSAGES_FILE = _WORKSPACE_DIR / "pending_messages.jsonl"
_CONFIG_FILE = _NANOBOT_DIR / "config.json"
_ARCHITECTURE_FILE = _WORKSPACE_DIR / "architecture.json"

# Keys in config JSON whose values should be redacted
_SENSITIVE_KEYS = re.compile(
    r"(key|token|secret|password|credential|auth)", re.IGNORECASE
)

# Boot time for uptime tracking
_START_TIME = time.monotonic()
_START_WALL = time.time()

# Optional bearer token for API authentication.
# Set via NANOBOT_DASHBOARD_TOKEN env var to require auth on /api/* endpoints.
_AUTH_TOKEN: str | None = os.environ.get("NANOBOT_DASHBOARD_TOKEN") or None

# ---------------------------------------------------------------------------
# Prometheus metrics (lazily used by agent loop instrumentation)
# ---------------------------------------------------------------------------
if _PROM_AVAILABLE:
    PROM_TOOL_CALLS = Counter(
        'nanobot_tool_calls_total', 'Total tool calls', ['tool_name', 'status'],
    )
    PROM_TOOL_ERRORS = Counter(
        'nanobot_tool_errors_total', 'Total tool call errors', ['tool_name'],
    )
    PROM_TOOL_DURATION = Histogram(
        'nanobot_tool_duration_ms', 'Tool call duration in ms', ['tool_name'],
        buckets=[5, 10, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000],
    )
    PROM_LLM_DURATION = Histogram(
        'nanobot_llm_call_duration_ms', 'LLM inference duration in ms',
        buckets=[500, 1000, 2500, 5000, 10000, 20000, 30000, 60000],
    )
    PROM_MESSAGES = Counter(
        'nanobot_messages_total', 'Total messages processed', ['channel'],
    )
    PROM_ACTIVE_SESSIONS = Gauge(
        'nanobot_active_sessions', 'Sessions active in last hour',
    )
    PROM_UPTIME = Gauge(
        'nanobot_uptime_seconds', 'Process uptime in seconds',
    )


# ---------------------------------------------------------------------------
# Audit -> Prometheus sync (cross-process bridge)
# ---------------------------------------------------------------------------
# The gateway process writes llm_call entries to audit.jsonl; this dashboard
# process serves /prom/metrics.  Since prometheus_client histograms are
# in-process-only, we replay new llm_call lines from the audit file into our
# local PROM_LLM_DURATION histogram at every scrape, tracking a byte offset
# so we only parse each line once.

_audit_prom_offset: int = 0  # byte offset of last-read position in audit.jsonl


def _sync_audit_to_prom() -> None:
    """Replay unread audit.jsonl entries into Prometheus metrics.

    Processes two event shapes:
    - llm_call events (have event_type == "llm_call"): observed into PROM_LLM_DURATION.
    - tool_call events (have tool_name, no event_type field): increment
      PROM_TOOL_CALLS{tool_name, status} and PROM_TOOL_ERRORS{tool_name} on error.

    A byte-offset watermark (_audit_prom_offset) ensures each line is processed
    exactly once across scrapes.  On process startup the offset is 0, so the
    first scrape performs a full backfill of all historical entries in the file.
    """
    global _audit_prom_offset
    if not _PROM_AVAILABLE:
        return
    if not _AUDIT_FILE.exists():
        return
    try:
        with open(_AUDIT_FILE, 'rb') as fh:
            fh.seek(_audit_prom_offset)
            new_bytes = fh.read()
            new_offset = _audit_prom_offset + len(new_bytes)
        for raw_line in new_bytes.split(b'\n'):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except (json.JSONDecodeError, ValueError):
                continue
            event_type = entry.get('event_type')
            if event_type == 'llm_call':
                # LLM call: observe latency histogram
                latency = entry.get('latency_ms')
                if isinstance(latency, (int, float)):
                    PROM_LLM_DURATION.observe(float(latency))
            elif 'tool_name' in entry:
                # Tool call: increment per-tool counters
                tool_name = entry.get('tool_name') or 'unknown'
                result_status = entry.get('result_status') or 'unknown'
                PROM_TOOL_CALLS.labels(tool_name=tool_name, status=result_status).inc()
                if result_status != 'ok':
                    PROM_TOOL_ERRORS.labels(tool_name=tool_name).inc()
        _audit_prom_offset = new_offset
    except OSError:
        pass



# ---------------------------------------------------------------------------
# Data collection helpers
# ---------------------------------------------------------------------------


def _check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _check_llama_server() -> dict[str, Any]:
    """
    Hit localhost:8001/health and return a small status dict.
    Returns: {"status": "ok"|"error"|"unreachable", "detail": str}
    """
    url = "http://localhost:8001/health"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                data = {"raw": body}
            # llama.cpp returns {"status": "ok"} when healthy
            status_val = data.get("status", "")
            if status_val == "ok" or resp.status == 200:
                return {"status": "ok", "detail": status_val or "200 OK"}
            return {"status": "error", "detail": status_val or f"HTTP {resp.status}"}
    except urllib.error.URLError as exc:
        return {"status": "unreachable", "detail": str(exc.reason)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_gateway(port: int = 18790) -> dict[str, Any]:
    """Check if the nanobot gateway TCP port is open."""
    up = _check_port("localhost", port)
    return {"status": "up" if up else "down", "port": port}


def _collect_sessions() -> dict[str, Any]:
    """Gather session file stats from the sessions directory."""
    if not _SESSIONS_DIR.exists():
        return {"count": 0, "last_modified": None, "last_modified_ts": None}

    files = list(_SESSIONS_DIR.glob("*.jsonl"))
    if not files:
        return {"count": 0, "last_modified": None, "last_modified_ts": None}

    newest = max(files, key=lambda p: p.stat().st_mtime)
    mtime = newest.stat().st_mtime
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return {
        "count": len(files),
        "last_modified": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_modified_ts": mtime,
    }


def _collect_memory() -> dict[str, Any]:
    """Return byte sizes of MEMORY.md and HISTORY.md."""
    def _size(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0

    return {
        "memory_bytes": _size(_MEMORY_FILE),
        "history_bytes": _size(_HISTORY_FILE),
        "memory_exists": _MEMORY_FILE.exists(),
        "history_exists": _HISTORY_FILE.exists(),
    }


def _collect_cron_jobs() -> dict[str, Any]:
    """Count entries in cron_jobs.json (or the data-dir jobs.json)."""
    # Try workspace-level file first, then the data-dir location used by CronService
    candidates = [
        _CRON_JOBS_FILE,
        _NANOBOT_DIR / "cron" / "jobs.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                # CronService stores {"jobs": [...]} or a raw list
                if isinstance(data, dict):
                    jobs = data.get("jobs", [])
                elif isinstance(data, list):
                    jobs = data
                else:
                    jobs = []
                return {"count": len(jobs), "path": str(path)}
            except Exception:
                return {"count": 0, "path": str(path), "error": "parse error"}
    return {"count": 0, "path": None}


def _collect_disk_usage() -> dict[str, Any]:
    """Walk ~/.nanobot/ and return total bytes used."""
    total = 0
    if _NANOBOT_DIR.exists():
        for dirpath, _dirs, filenames in os.walk(_NANOBOT_DIR):
            for fname in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass
    return {"bytes": total, "human": _human_bytes(total)}


def _human_bytes(n: int) -> str:
    """Format bytes as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _format_uptime(seconds: float) -> str:
    """Format elapsed seconds as d h m s string."""
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def _parse_query_params(full_path: str) -> dict[str, str]:
    """Extract query parameters from the full request path."""
    parsed = urllib.parse.urlparse(full_path)
    params = urllib.parse.parse_qs(parsed.query)
    # Flatten: take first value for each key
    return {k: v[0] for k, v in params.items()}


def _redact_sensitive(obj: Any) -> Any:
    """
    Recursively walk a JSON-compatible object and fully redact values whose
    keys look like secrets/tokens/keys.  No partial reveal.
    """
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if isinstance(v, str) and _SENSITIVE_KEYS.search(k):
                result[k] = "***REDACTED***"
            elif isinstance(v, str) and k.lower() in ("extra_headers", "headers"):
                result[k] = "***REDACTED***"
            else:
                result[k] = _redact_sensitive(v)
        return result
    elif isinstance(obj, list):
        return [_redact_sensitive(item) for item in obj]
    return obj


def _parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """
    Parse simple YAML frontmatter between --- delimiters.
    Only handles flat key: value pairs (strings).  Good enough for
    name/description in SKILL.md files without pulling in PyYAML.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            result[key] = value
    return result


def _read_file_safe(path: Path) -> str:
    """Read a text file, returning empty string on any error."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# API status builder
# ---------------------------------------------------------------------------


def build_status() -> dict[str, Any]:
    """Collect and return the full status payload."""
    elapsed = time.monotonic() - _START_TIME
    sessions = _collect_sessions()
    return {
        "uptime": _format_uptime(elapsed),
        "uptime_seconds": round(elapsed, 1),
        "server_time": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "llama_server": _check_llama_server(),
        "gateway": _check_gateway(),
        "sessions": sessions,
        "last_message_time": sessions.get("last_modified"),
        "last_message_ts": sessions.get("last_modified_ts"),
        "memory": _collect_memory(),
        "cron_jobs": _collect_cron_jobs(),
        "disk_usage": _collect_disk_usage(),
    }


# ---------------------------------------------------------------------------
# API endpoint handlers (return dicts or raise)
# ---------------------------------------------------------------------------


def _api_sessions_list() -> list[dict[str, Any]]:
    """List all sessions with metadata and message counts."""
    if not _SESSIONS_DIR.exists():
        return []

    sessions: list[dict[str, Any]] = []
    for fpath in sorted(_SESSIONS_DIR.glob("*.jsonl")):
        try:
            with open(fpath, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue

        if not lines:
            continue

        # First line is metadata
        metadata: dict[str, Any] = {}
        try:
            first = json.loads(lines[0])
            if first.get("_type") == "metadata":
                metadata = first
        except (json.JSONDecodeError, IndexError):
            pass

        # Message count = total lines minus the metadata line
        message_count = len(lines) - 1 if metadata else len(lines)

        # Session key: use the key from metadata, or derive from filename
        key = metadata.get("key", fpath.stem)

        sessions.append({
            "key": key,
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "message_count": message_count,
        })

    return sessions


def _api_session_detail(session_key: str, limit: int | None, offset: int) -> dict[str, Any]:
    """
    Get messages for a single session.

    session_key uses underscores in the URL (e.g. discord_1234) which maps
    to the filename discord_1234.jsonl on disk.
    """
    # Validate session key: no path traversal
    if "/" in session_key or "\\" in session_key or ".." in session_key:
        return {"error": "Invalid session key"}
    fpath = _SESSIONS_DIR / f"{session_key}.jsonl"
    if fpath.resolve().parent != _SESSIONS_DIR.resolve():
        return {"error": "Invalid session key"}
    if not fpath.exists():
        return {"error": f"Session not found: {session_key}"}

    try:
        with open(fpath, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        return {"error": f"Failed to read session: {exc}"}

    # Parse all lines, skip metadata
    messages: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if i == 0 and obj.get("_type") == "metadata":
            metadata = obj
            continue
        messages.append(obj)

    total = len(messages)

    # Apply pagination
    messages = messages[offset:]
    if limit is not None:
        messages = messages[:limit]

    return {
        "key": metadata.get("key", session_key),
        "created_at": metadata.get("created_at"),
        "updated_at": metadata.get("updated_at"),
        "total_messages": total,
        "offset": offset,
        "limit": limit,
        "messages": messages,
    }


def _api_memory() -> dict[str, Any]:
    """Return contents of MEMORY.md and HISTORY.md."""
    return {
        "memory": _read_file_safe(_MEMORY_FILE),
        "history": _read_file_safe(_HISTORY_FILE),
    }


def _api_skills() -> list[dict[str, Any]]:
    """List installed skills by scanning for SKILL.md with YAML frontmatter."""
    if not _SKILLS_DIR.exists():
        return []

    skills: list[dict[str, Any]] = []
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue
        content = _read_file_safe(skill_file)
        if not content:
            continue
        frontmatter = _parse_yaml_frontmatter(content)
        skills.append({
            "name": frontmatter.get("name", skill_dir.name),
            "description": frontmatter.get("description", ""),
        })

    return skills


def _api_audit(limit: int) -> list[dict[str, Any]]:
    """Return the last N audit log entries."""
    if not _AUDIT_FILE.exists():
        return []

    try:
        with open(_AUDIT_FILE, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []

    # Take the last `limit` lines
    tail = lines[-limit:] if limit < len(lines) else lines

    entries: list[dict[str, Any]] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return entries


_MAX_MESSAGE_CONTENT_LENGTH = 4096

# Simple rate limiter: tracks last N requests per IP
_rate_limit_log: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 10  # max requests per window


def _check_rate_limit(client_ip: str) -> bool:
    """Return True if the request is within rate limits."""
    now = time.time()
    entries = _rate_limit_log.get(client_ip, [])
    entries = [t for t in entries if now - t < _RATE_LIMIT_WINDOW]
    if len(entries) >= _RATE_LIMIT_MAX:
        _rate_limit_log[client_ip] = entries
        return False
    entries.append(now)
    _rate_limit_log[client_ip] = entries
    return True


def _api_post_message(body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """
    Queue a message for the bot by appending to pending_messages.jsonl.
    Returns (response_dict, http_status).
    """
    channel = body.get("channel")
    chat_id = body.get("chat_id")
    content = body.get("content")

    if not channel or not chat_id or not content:
        return {
            "error": "Missing required fields: channel, chat_id, content"
        }, 400

    # Validate channel name
    _VALID_CHANNELS = {"discord", "telegram", "slack", "whatsapp", "feishu",
                       "matrix", "email", "dingtalk", "qq", "mochat", "cli", "api"}
    if channel not in _VALID_CHANNELS:
        return {"error": f"Invalid channel: {channel}"}, 400

    # Enforce content length limit
    if len(content) > _MAX_MESSAGE_CONTENT_LENGTH:
        return {"error": f"Content too long (max {_MAX_MESSAGE_CONTENT_LENGTH} chars)"}, 400

    # Screen for prompt injection
    from nanobot.utils.security import sanitize_input
    content, was_injection = sanitize_input(content)
    if was_injection:
        return {"error": "Message blocked: potential prompt injection detected"}, 400

    entry = {
        "channel": channel,
        "chat_id": chat_id,
        "content": content,
        "queued_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        # Ensure parent directory exists
        _PENDING_MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_PENDING_MESSAGES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        return {"error": f"Failed to queue message: {exc}"}, 500

    return {"status": "queued"}, 200


def _api_metrics() -> dict[str, Any]:
    """
    Compute tool-level and timeline metrics from the audit log.

    Returns a dict with keys: tool_stats, timeline, session_stats, overall,
    recent.
    """
    import statistics
    from collections import defaultdict

    now = time.time()
    now_dt = datetime.now(tz=timezone.utc)
    cutoff_24h = now - 86400

    # -- read audit entries ------------------------------------------------
    entries: list[dict[str, Any]] = []
    if _AUDIT_FILE.exists():
        try:
            with open(_AUDIT_FILE, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass

    # -- per-tool accumulators --------------------------------------------
    tool_counts: dict[str, int] = defaultdict(int)
    tool_durations: dict[str, list[float]] = defaultdict(list)
    tool_errors: dict[str, int] = defaultdict(int)

    # -- timeline accumulators (keyed by ISO hour string) ------------------
    hour_counts: dict[str, int] = defaultdict(int)
    hour_durations: dict[str, list[float]] = defaultdict(list)
    hour_errors: dict[str, int] = defaultdict(int)

    # -- session accumulators ---------------------------------------------
    session_msg_counts: dict[str, int] = defaultdict(int)
    session_last_seen: dict[str, float] = {}

    # -- overall accumulators ---------------------------------------------
    all_durations: list[float] = []
    total_errors = 0

    for entry in entries:
        ts_str = entry.get("timestamp", "")
        tool = entry.get("tool_name", "unknown")
        duration = entry.get("duration_ms")
        status = entry.get("result_status", "ok")
        session = entry.get("session_id", "unknown")
        # channel = entry.get("channel", "unknown")  # available if needed

        # Parse timestamp
        ts_epoch: float | None = None
        try:
            if ts_str:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts_epoch = dt.timestamp()
        except (ValueError, TypeError):
            ts_epoch = None

        is_error = status not in ("ok", "success", "")

        # Per-tool stats (all time)
        tool_counts[tool] += 1
        if duration is not None:
            try:
                dur_f = float(duration)
                tool_durations[tool].append(dur_f)
                all_durations.append(dur_f)
            except (ValueError, TypeError):
                pass
        if is_error:
            tool_errors[tool] += 1
            total_errors += 1

        # Session tracking
        session_msg_counts[session] += 1
        if ts_epoch is not None:
            session_last_seen[session] = max(
                session_last_seen.get(session, 0), ts_epoch,
            )

        # Timeline (last 24h only)
        if ts_epoch is not None and ts_epoch >= cutoff_24h:
            # Bucket by hour: "2026-03-16T14"
            try:
                hour_key = datetime.fromtimestamp(
                    ts_epoch, tz=timezone.utc,
                ).strftime("%Y-%m-%dT%H")
            except (OSError, ValueError):
                continue
            hour_counts[hour_key] += 1
            if duration is not None:
                try:
                    hour_durations[hour_key].append(float(duration))
                except (ValueError, TypeError):
                    pass
            if is_error:
                hour_errors[hour_key] += 1

    # -- build tool_stats -------------------------------------------------
    def _percentile(data: list[float], pct: float) -> float:
        if not data:
            return 0.0
        s = sorted(data)
        k = (len(s) - 1) * pct / 100.0
        f = int(k)
        c = f + 1
        if c >= len(s):
            return round(s[f], 2)
        return round(s[f] + (k - f) * (s[c] - s[f]), 2)

    tool_stats: list[dict[str, Any]] = []
    all_tool_names = sorted(
        tool_counts.keys() | tool_durations.keys() | tool_errors.keys()
    )
    for tool_name in all_tool_names:
        durs = tool_durations.get(tool_name, [])
        tool_stats.append({
            "tool": tool_name,
            "count": tool_counts.get(tool_name, 0),
            "avg_ms": round(statistics.mean(durs), 2) if durs else 0,
            "p50_ms": _percentile(durs, 50),
            "p95_ms": _percentile(durs, 95),
            "error_count": tool_errors.get(tool_name, 0),
        })

    # -- build timeline (24 hour buckets) ---------------------------------
    timeline: list[dict[str, Any]] = []
    for h in range(24):
        dt_hour = now_dt.replace(minute=0, second=0, microsecond=0) - \
                  timedelta(hours=23 - h)
        hour_key = dt_hour.strftime("%Y-%m-%dT%H")
        durs = hour_durations.get(hour_key, [])
        timeline.append({
            "hour": hour_key,
            "count": hour_counts.get(hour_key, 0),
            "avg_ms": round(statistics.mean(durs), 2) if durs else 0,
            "errors": hour_errors.get(hour_key, 0),
        })

    # -- session stats ----------------------------------------------------
    active_cutoff = now - 3600
    active_sessions = sum(
        1 for ts in session_last_seen.values() if ts >= active_cutoff
    )
    msg_per_session = list(session_msg_counts.values())
    session_stats = {
        "total_sessions": len(session_msg_counts),
        "active_last_hour": active_sessions,
        "avg_messages_per_session": round(
            statistics.mean(msg_per_session), 1,
        ) if msg_per_session else 0,
        "max_messages_per_session": max(msg_per_session) if msg_per_session else 0,
    }

    # -- overall ----------------------------------------------------------
    total_messages = len(entries)
    elapsed = time.monotonic() - _START_TIME
    overall = {
        "total_messages": total_messages,
        "avg_response_ms": round(
            statistics.mean(all_durations), 2,
        ) if all_durations else 0,
        "error_rate": round(
            total_errors / total_messages * 100, 2,
        ) if total_messages else 0,
        "uptime": _format_uptime(elapsed),
        "uptime_seconds": round(elapsed, 1),
    }

    # -- recent (last 20 entries) -----------------------------------------
    recent: list[dict[str, Any]] = []
    for entry in entries[-20:]:
        recent.append({
            "timestamp": entry.get("timestamp"),
            "tool_name": entry.get("tool_name"),
            "duration_ms": entry.get("duration_ms"),
            "result_status": entry.get("result_status"),
            "session_id": entry.get("session_id"),
            "channel": entry.get("channel"),
        })

    return {
        "tool_stats": tool_stats,
        "timeline": timeline,
        "session_stats": session_stats,
        "overall": overall,
        "recent": recent,
    }


def _api_config() -> dict[str, Any]:
    """Return sanitized config with secrets redacted."""
    if not _CONFIG_FILE.exists():
        return {"error": "Config file not found"}

    try:
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"Failed to read config: {exc}"}

    return _redact_sensitive(config)


def _api_architecture() -> dict[str, Any]:
    """Return system architecture documentation."""
    if not _ARCHITECTURE_FILE.exists():
        return {"error": "Architecture file not found"}

    try:
        with open(_ARCHITECTURE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": f"Failed to read architecture: {exc}"}


# ---------------------------------------------------------------------------
# HTTP request handler
# ---------------------------------------------------------------------------


class DashboardHandler(BaseHTTPRequestHandler):
    """Minimal request handler: serves / and /api/* endpoints."""

    # Silence default access log noise; override to log or suppress
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102
        pass  # suppress per-request stdout noise; errors still go to stderr

    # ------------------------------------------------------------------
    # CORS helpers
    # ------------------------------------------------------------------

    _ORIGIN_RE = re.compile(r'^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$')

    def _add_cors_headers(self) -> None:
        """Append CORS and security headers to the current response."""
        origin = self.headers.get("Origin", "")
        # Strict localhost-only origin matching (no startswith to prevent localhost.evil.com)
        if origin and self._ORIGIN_RE.match(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "http://localhost:18791")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        # Security headers
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")

    def _check_auth(self, require: bool = False) -> bool:
        """Check bearer token auth. Returns True if ok.

        If *require* is True, the endpoint is always protected even when
        no dashboard token has been configured.
        """
        if _AUTH_TOKEN is None and not require:
            return True
        if _AUTH_TOKEN is None and require:
            self._send_json({"error": "Unauthorized — set NANOBOT_DASHBOARD_TOKEN to use this endpoint"}, 401)
            return False
        auth_header = self.headers.get("Authorization", "")
        if auth_header == f"Bearer {_AUTH_TOKEN}":
            return True
        self._send_json({"error": "Unauthorized"}, 401)
        return False

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-cache")
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(html)

    def _send_404(self) -> None:
        body = b"Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # HTTP method handlers
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._add_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        params = _parse_query_params(self.path)

        # Require auth for API endpoints
        if path.startswith("/api/") and not self._check_auth():
            return

        if path in ("/", "/index.html"):
            tpl = _TEMPLATES_DIR / "index.html"
            try:
                html = tpl.read_bytes()
                self._send_html(html)
            except OSError:
                self._send_html(b"<h1>Template not found</h1>", 500)

        elif path == "/api/status":
            try:
                payload = build_status()
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/sessions":
            if not self._check_auth(require=True):
                return
            try:
                self._send_json(_api_sessions_list())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path.startswith("/api/sessions/"):
            # Extract session key from /api/sessions/<key>
            if not self._check_auth(require=True):
                return
            session_key = path[len("/api/sessions/"):]
            if not session_key:
                self._send_json({"error": "Session key required"}, 400)
                return
            try:
                limit_str = params.get("limit")
                offset_str = params.get("offset", "0")
                limit = min(int(limit_str), 1000) if limit_str is not None else None
                offset = max(int(offset_str), 0)
            except (ValueError, TypeError):
                self._send_json({"error": "Invalid limit/offset parameters"}, 400)
                return
            try:
                result = _api_session_detail(session_key, limit, offset)
                if "error" in result:
                    is_invalid = result["error"] == "Invalid session key"
                    self._send_json(result, 400 if is_invalid else 404)
                    return
                self._send_json(result)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/memory":
            if not self._check_auth(require=True):
                return
            try:
                self._send_json(_api_memory())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/skills":
            try:
                self._send_json(_api_skills())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/audit":
            if not self._check_auth(require=True):
                return
            try:
                limit_str = params.get("limit", "50")
                limit = min(max(int(limit_str), 1), 500)
            except (ValueError, TypeError):
                self._send_json({"error": "Invalid limit parameter"}, 400)
                return
            try:
                self._send_json(_api_audit(limit))
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/config":
            # Always require auth — config contains sensitive info
            if not self._check_auth(require=True):
                return
            try:
                self._send_json(_api_config())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/metrics":
            if not self._check_auth(require=True):
                return
            try:
                self._send_json(_api_metrics())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/api/architecture":
            try:
                self._send_json(_api_architecture())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        elif path == "/metrics":
            tpl = _TEMPLATES_DIR / "metrics.html"
            try:
                html = tpl.read_bytes()
                self._send_html(html)
            except OSError:
                self._send_html(b"<h1>Template not found</h1>", 500)

        elif path == "/prom/metrics":
            if not _PROM_AVAILABLE:
                self._send_json({"error": "prometheus-client not installed"}, 503)
                return
            # Update gauges before serving
            PROM_UPTIME.set(time.monotonic() - _START_TIME)
            # Replay new llm_call entries from audit.jsonl into the histogram
            _sync_audit_to_prom()
            try:
                output = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.send_header("Content-Length", str(len(output)))
                self.end_headers()
                self.wfile.write(output)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)

        else:
            self._send_404()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")

        if path.startswith("/api/") and not self._check_auth():
            return

        if path == "/api/message":
            # Always require auth for message injection (RCE vector)
            if not self._check_auth(require=True):
                return
            # Rate limit
            client_ip = self.client_address[0]
            if not _check_rate_limit(client_ip):
                self._send_json({"error": "Rate limit exceeded (max 10/min)"}, 429)
                return
            # Read and parse JSON body
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_json({"error": "Empty request body"}, 400)
                return
            try:
                raw = self.rfile.read(content_length)
                body = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json({"error": f"Invalid JSON: {exc}"}, 400)
                return

            try:
                result, status = _api_post_message(body)
                self._send_json(result, status)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
        else:
            self._send_404()


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def run(host: str = "127.0.0.1", port: int = 18791) -> None:
    """Start the dashboard HTTP server (blocking)."""
    server = HTTPServer((host, port), DashboardHandler)
    addr = f"http://{host if host != '0.0.0.0' else 'localhost'}:{port}"
    print(f"Nanobot dashboard running at {addr}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard.")
    finally:
        server.server_close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m nanobot.dashboard.server",
        description="Nanobot status dashboard",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=18791,
        help="Port to listen on (default: 18791)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(host=args.host, port=args.port)
