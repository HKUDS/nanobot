"""File chunking and SQLite write pipeline for the memory index."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TOKEN_ESTIMATE_RATIO = 4  # characters per token (heuristic)
TARGET_TOKENS = 400
OVERLAP_TOKENS = 50
MIN_TOKENS = 50
_MIN_BODY_CHARS = 8  # body shorter than this is considered empty and skipped

_HISTORY_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")


@dataclass
class Chunk:
    text: str
    start_line: int
    end_line: int
    created_at: float  # unix timestamp


def file_hash(path: Path) -> str:
    """Return sha256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def chunk_memory_file(path: Path) -> list[Chunk]:
    """Split MEMORY.md into chunks by ## section headers."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    mtime = path.stat().st_mtime

    # Group lines into sections delimited by ## headers
    sections: list[tuple[int, str]] = []
    current_start = 0
    current_lines: list[str] = []

    for i, line in enumerate(lines):
        if line.startswith("## ") and current_lines:
            sections.append((current_start, "".join(current_lines)))
            current_start = i
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_start, "".join(current_lines)))

    chunks: list[Chunk] = []
    for start_line, section_text in sections:
        chunks.extend(_split_section(section_text, start_line, mtime))
    return chunks


def chunk_history_file(path: Path) -> list[Chunk]:
    """Split HISTORY.md into chunks by [YYYY-MM-DD HH:MM] entry boundaries."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # Parse entries
    entries: list[tuple[int, float, list[str]]] = []
    current_start = 0
    current_ts: float | None = None
    current_lines: list[str] = []

    for i, line in enumerate(lines):
        m = _HISTORY_TS_RE.match(line)
        if m:
            if current_lines and current_ts is not None:
                entries.append((current_start, current_ts, current_lines[:]))
            current_start = i
            current_ts = _parse_ts(m.group(1))
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines and current_ts is not None:
        entries.append((current_start, current_ts, current_lines[:]))

    # Group entries into ~TARGET_TOKENS windows
    chunks: list[Chunk] = []
    buf_lines: list[str] = []
    buf_start = 0
    buf_ts: float | None = None
    buf_tokens = 0

    for start_line, ts, entry_lines in entries:
        entry_tokens = len("".join(entry_lines)) // TOKEN_ESTIMATE_RATIO
        if buf_lines and buf_tokens + entry_tokens > TARGET_TOKENS:
            chunk_text = "".join(buf_lines).strip()
            if chunk_text:
                chunks.append(Chunk(chunk_text, buf_start, start_line - 1, buf_ts or ts))
            buf_lines = entry_lines[:]
            buf_start = start_line
            buf_ts = ts
            buf_tokens = entry_tokens
        else:
            if not buf_lines:
                buf_start = start_line
                buf_ts = ts
            buf_lines.extend(entry_lines)
            buf_tokens += entry_tokens

    if buf_lines:
        chunk_text = "".join(buf_lines).strip()
        if chunk_text:
            end_line = buf_start + len(buf_lines) - 1
            chunks.append(Chunk(chunk_text, buf_start, end_line, buf_ts or 0.0))

    return chunks


def _split_section(text: str, base_line: int, created_at: float) -> list[Chunk]:
    """Split one section into <=TARGET_TOKENS chunks with OVERLAP_TOKENS overlap."""
    stripped = text.strip()
    if not stripped:
        return []

    # Filter sections whose body (non-header lines) is trivially short.
    # MIN_TOKENS is the threshold for chunk output, but we use a small absolute
    # char check here so that genuine content ("Some fact.", 10 chars) is kept
    # while near-empty bodies ("hi", 2 chars) are dropped.
    lines = stripped.splitlines()
    body_text = "\n".join(ln for ln in lines if not ln.startswith("## ")).strip()
    if len(body_text) < _MIN_BODY_CHARS:  # near-empty body → skip
        return []

    token_count = len(stripped) // TOKEN_ESTIMATE_RATIO

    if token_count <= TARGET_TOKENS:
        n_lines = stripped.count("\n")
        return [Chunk(stripped, base_line, base_line + n_lines, created_at)]

    paragraphs = re.split(r"\n\n+", stripped)
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0
    line_offset = base_line

    for para in paragraphs:
        para_tokens = len(para) // TOKEN_ESTIMATE_RATIO
        if buf and buf_tokens + para_tokens > TARGET_TOKENS:
            chunk_text = "\n\n".join(buf).strip()
            n_lines = chunk_text.count("\n")
            if len(chunk_text) // TOKEN_ESTIMATE_RATIO >= MIN_TOKENS:
                chunks.append(Chunk(chunk_text, line_offset, line_offset + n_lines, created_at))
            # overlap: use last OVERLAP_TOKENS worth of characters (~200 chars) for context
            overlap_text = (
                chunk_text[-(OVERLAP_TOKENS * TOKEN_ESTIMATE_RATIO) :] if chunk_text else ""
            )
            overlap_lines = overlap_text.count("\n") + 1 if overlap_text.strip() else 0
            # Advance by the chunk's lines, then step back by overlap so next chunk's
            # start_line reflects that it begins with repeated content from the previous chunk.
            line_offset += n_lines + 2 - overlap_lines
            buf = [overlap_text, para] if overlap_text.strip() else [para]
            buf_tokens = len(overlap_text) // TOKEN_ESTIMATE_RATIO + para_tokens
        else:
            buf.append(para)
            buf_tokens += para_tokens

    if buf:
        chunk_text = "\n\n".join(buf).strip()
        if chunk_text:
            n_lines = chunk_text.count("\n")
            tail_tokens = len(chunk_text) // TOKEN_ESTIMATE_RATIO
            if chunks and tail_tokens < MIN_TOKENS:
                # Merge short tail into last chunk
                last = chunks[-1]
                merged = last.text + "\n\n" + chunk_text
                chunks[-1] = Chunk(merged, last.start_line, last.end_line + n_lines + 2, created_at)
            else:
                chunks.append(Chunk(chunk_text, line_offset, line_offset + n_lines, created_at))

    return chunks


def _parse_ts(ts_str: str) -> float:
    return datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
