"""Tool result cache with LLM-based summary generation.

Stores full tool outputs outside the chat history so the LLM only sees
compact summary envelopes with a cache key.  Follow-up tools can retrieve
specific slices of cached results on demand.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult

# ---------------------------------------------------------------------------
# Summary generation
# ---------------------------------------------------------------------------

_SUMMARY_THRESHOLD = 3000  # chars — results below this pass through as-is

_SUMMARY_SYSTEM = (
    "You are a tool-output summariser for an AI agent. Given the raw output of a tool call, "
    "produce a concise structured summary that preserves the key information the agent needs "
    "to reason about the data WITHOUT seeing the full output.\n\n"
    "Requirements:\n"
    "- Include data structure (row count, column names for tabular data, key names for JSON)\n"
    "- Include a representative preview (first few rows or items)\n"
    "- Include total size and the cache key so the agent knows how to retrieve more\n"
    "- For spreadsheet/tabular data: list ALL task/item names with their key attributes "
    "(status, dates, owner) so the agent can produce a complete summary without fetching raw rows. "
    "Prefer a compact table or bullet list format.\n"
    '- End with a note: \'Full data cached. Use excel_get_rows(cache_key="{key}", start_row=N, '
    'end_row=M) for row ranges, or cache_get_slice(cache_key="{key}", start=N, end=M) '
    "for raw lines.'\n"
    "- Keep the summary under 4000 characters\n"
    "- Do NOT reproduce raw JSON — restructure into human-readable format"
)


class _ChatProvider(Protocol):
    """Minimal provider interface for summary generation."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> Any: ...


def _heuristic_summary(tool_name: str, output: str, cache_key: str) -> str:
    """Deterministic fallback summary when LLM is unavailable."""
    total = len(output)
    preview = output[:400]
    return (
        f"[{tool_name}] returned {total:,} chars of output.\n"
        f"Preview:\n{preview}\n...\n"
        f"Full result cached as {cache_key} ({total:,} chars). "
        f'Use excel_get_rows(cache_key="{cache_key}", start_row=0, end_row=25) '
        f"for row ranges, or "
        f'cache_get_slice(cache_key="{cache_key}", start=0, end=25) '
        f"for raw lines."
    )


async def generate_summary(
    tool_name: str,
    output: str,
    cache_key: str,
    provider: _ChatProvider | None = None,
    model: str | None = None,
) -> str:
    """Generate a summary for a large tool result.

    Uses the LLM when *provider* is available, falling back to a
    deterministic heuristic on failure or when no provider is given.
    """
    if provider is None or model is None:
        return _heuristic_summary(tool_name, output, cache_key)

    prompt = (
        f"Tool: {tool_name}\nCache key: {cache_key}\n"
        f"Output length: {len(output):,} characters\n\n"
        f"--- RAW OUTPUT (first 8000 chars) ---\n{output[:8000]}"
    )

    try:
        resp = await provider.chat(
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            model=model,
            temperature=0.0,
            max_tokens=500,
        )
        summary = (resp.content or "").strip()
        if summary:
            logger.debug(
                "LLM summary for {}(key={}) — {} chars", tool_name, cache_key, len(summary)
            )
            return summary
    except Exception:
        logger.warning("LLM summary failed for {}, using heuristic fallback", tool_name)

    return _heuristic_summary(tool_name, output, cache_key)


# ---------------------------------------------------------------------------
# Cache key generation
# ---------------------------------------------------------------------------


def _make_cache_key(tool_name: str, args: dict[str, Any]) -> str:
    """Deterministic cache key from tool name + canonical args."""
    canonical = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha256(f"{tool_name}:{canonical}".encode()).hexdigest()[:12]
    return digest


# ---------------------------------------------------------------------------
# Cache entry + store
# ---------------------------------------------------------------------------

_MAX_DISK_ENTRY_BYTES = 200_000  # entries larger than this are memory-only
_MAX_DISK_ENTRIES = 50
_MAX_MEMORY_ENTRIES = 500  # LRU cap for in-memory cache


@dataclass(slots=True)
class CacheEntry:
    """A cached tool result with its summary."""

    cache_key: str
    tool_name: str
    full_output: str
    summary: str
    token_estimate: int
    created_at: float
    truncated: bool = False


class ToolResultCache:
    """In-memory tool result cache with optional JSONL disk persistence."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._disk_path: Path | None = None
        if workspace:
            self._disk_path = workspace / "memory" / "tool_cache.jsonl"
            self._load_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """Return cache key if a matching entry exists, else ``None``."""
        key = _make_cache_key(tool_name, args)
        if key in self._entries:
            return key
        return None

    def get(self, cache_key: str) -> CacheEntry | None:
        """Retrieve an entry by cache key."""
        return self._entries.get(cache_key)

    def store(
        self,
        tool_name: str,
        args: dict[str, Any],
        full_output: str,
        summary: str,
        *,
        truncated: bool = False,
        token_estimate: int = 0,
    ) -> str:
        """Store a tool result and its summary.  Returns the cache key."""
        key = _make_cache_key(tool_name, args)
        entry = CacheEntry(
            cache_key=key,
            tool_name=tool_name,
            full_output=full_output,
            summary=summary,
            token_estimate=token_estimate,
            created_at=time.time(),
            truncated=truncated,
        )
        self._entries[key] = entry
        # LRU eviction: pop the oldest entry when the cap is exceeded
        if len(self._entries) > _MAX_MEMORY_ENTRIES:
            self._entries.popitem(last=False)
        self._persist_entry(entry)
        return key

    async def store_with_summary(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
        provider: _ChatProvider | None = None,
        model: str | None = None,
    ) -> tuple[str, ToolResult]:
        """Generate an LLM summary and store the result.

        Returns ``(cache_key, new_result)`` where *new_result* is a fresh
        ``ToolResult`` with ``cache_key`` and ``summary`` added to its
        metadata.  The original *result* is never mutated.
        """
        key = _make_cache_key(tool_name, args)
        summary = await generate_summary(
            tool_name, result.output, key, provider=provider, model=model
        )
        self.store(
            tool_name,
            args,
            result.output,
            summary,
            truncated=result.truncated,
            token_estimate=len(result.output) // 4,
        )
        # Return a new ToolResult with cache metadata — never mutate the original.
        new_result = ToolResult(
            output=result.output,
            success=result.success,
            error=result.error,
            truncated=result.truncated,
            metadata={**result.metadata, "cache_key": key, "summary": summary},
        )
        return key, new_result

    def store_only(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: ToolResult,
    ) -> tuple[str, ToolResult]:
        """Cache the full output *without* generating a summary.

        The LLM sees raw output on the current turn.  On later turns the
        context compressor can truncate the message and the agent can use
        ``cache_get_slice`` with the returned key to page through the data.

        Returns ``(cache_key, new_result)`` where *new_result* is a fresh
        ``ToolResult`` with ``cache_key`` added to its metadata.  The
        original *result* is never mutated.
        """
        key = _make_cache_key(tool_name, args)
        self.store(
            tool_name,
            args,
            result.output,
            summary="",
            truncated=result.truncated,
            token_estimate=len(result.output) // 4,
        )
        # Return a new ToolResult with cache_key metadata — never mutate the original.
        # Do NOT include "summary" so to_llm_string() returns raw output.
        new_result = ToolResult(
            output=result.output,
            success=result.success,
            error=result.error,
            truncated=result.truncated,
            metadata={**result.metadata, "cache_key": key},
        )
        return key, new_result

    def get_slice(self, cache_key: str, start: int = 0, end: int = 25) -> str | None:
        """Return a slice of the cached output (lines or JSON rows)."""
        entry = self._entries.get(cache_key)
        if entry is None:
            return None
        return _slice_output(entry.full_output, start, end)

    def clear(self) -> None:
        """Flush in-memory and disk caches."""
        self._entries.clear()
        if self._disk_path and self._disk_path.exists():
            self._disk_path.unlink()

    # ------------------------------------------------------------------
    # Disk persistence helpers
    # ------------------------------------------------------------------

    def _persist_entry(self, entry: CacheEntry) -> None:
        """Append an entry to the JSONL disk file (if configured)."""
        if self._disk_path is None:
            return
        if len(entry.full_output) > _MAX_DISK_ENTRY_BYTES:
            return  # too large for disk — memory-only

        record = {
            "cache_key": entry.cache_key,
            "tool_name": entry.tool_name,
            "full_output": entry.full_output,
            "summary": entry.summary,
            "token_estimate": entry.token_estimate,
            "created_at": entry.created_at,
            "truncated": entry.truncated,
        }
        self._disk_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._disk_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._evict_disk()

    def _load_disk(self) -> None:
        """Load entries from the JSONL disk file."""
        if self._disk_path is None or not self._disk_path.exists():
            return
        try:
            lines = self._disk_path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-_MAX_DISK_ENTRIES:]:
                record = json.loads(line)
                entry = CacheEntry(
                    cache_key=record["cache_key"],
                    tool_name=record["tool_name"],
                    full_output=record["full_output"],
                    summary=record["summary"],
                    token_estimate=record.get("token_estimate", 0),
                    created_at=record.get("created_at", 0.0),
                    truncated=record.get("truncated", False),
                )
                self._entries[entry.cache_key] = entry
            logger.debug("Loaded {} cached tool results from disk", len(self._entries))
        except Exception:
            logger.warning("Failed to load tool result cache from disk")

    def _evict_disk(self) -> None:
        """Keep disk file within the entry cap (LRU by file order)."""
        if self._disk_path is None or not self._disk_path.exists():
            return
        try:
            lines = self._disk_path.read_text(encoding="utf-8").strip().splitlines()
            if len(lines) > _MAX_DISK_ENTRIES:
                keep = lines[-_MAX_DISK_ENTRIES:]
                self._disk_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Slice helper
# ---------------------------------------------------------------------------


def _slice_output(output: str, start: int, end: int) -> str:
    """Extract a slice from cached output — JSON-array-aware or line-based."""
    # Try JSON array first (common for tabular tool results)
    try:
        parsed = json.loads(output)
        # If top-level is a dict with a "sheets" key (Excel output), flatten rows
        if isinstance(parsed, dict):
            for sheet_data in parsed.get("sheets", {}).values():
                rows = sheet_data.get("rows", [])
                if rows:
                    sliced = rows[start:end]
                    return json.dumps(sliced, ensure_ascii=False, indent=2, default=str)
            # Generic dict with a "rows" key
            if "rows" in parsed:
                sliced = parsed["rows"][start:end]
                return json.dumps(sliced, ensure_ascii=False, indent=2, default=str)
        # Top-level array
        if isinstance(parsed, list):
            sliced = parsed[start:end]
            return json.dumps(sliced, ensure_ascii=False, indent=2, default=str)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to line-based slicing
    lines = output.splitlines()
    sliced = lines[start:end]
    return "\n".join(sliced)


# ---------------------------------------------------------------------------
# CacheGetSliceTool — generic retrieval from any cached result
# ---------------------------------------------------------------------------


class CacheGetSliceTool(Tool):
    """Retrieve a slice of a previously cached tool result."""

    readonly = True
    cacheable = False

    def __init__(self, cache: ToolResultCache) -> None:
        self._cache = cache

    @property
    def name(self) -> str:
        return "cache_get_slice"

    @property
    def description(self) -> str:
        return (
            "Retrieve a slice (rows or lines) from a previously cached tool result. "
            "Use the cache_key from a prior tool call's summary to access the full data."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cache_key": {
                    "type": "string",
                    "description": "The cache key from a prior tool result summary.",
                },
                "start": {
                    "type": "integer",
                    "description": "Start index (0-based row or line number). Default 0.",
                    "minimum": 0,
                },
                "end": {
                    "type": "integer",
                    "description": "End index (exclusive). Default 25.",
                    "minimum": 1,
                },
            },
            "required": ["cache_key"],
        }

    async def execute(  # type: ignore[override]
        self,
        cache_key: str,
        start: int = 0,
        end: int = 25,
        **kwargs: Any,
    ) -> ToolResult:
        result = self._cache.get_slice(cache_key, start, end)
        if result is None:
            return ToolResult.fail(
                f"No cached result found for key '{cache_key}'. "
                "The cache may have been cleared. Re-run the original tool.",
                error_type="not_found",
            )
        return ToolResult.ok(result)
