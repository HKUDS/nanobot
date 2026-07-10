"""Shared Markdown helpers for chat channel renderers."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable

_BASIC_INLINE_STRIP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"`([^`]+)`"), r"\1"),
)

_PIPE_TABLE_LINE_RE = re.compile(r"^\s*\|.+\|")
_TABLE_SEPARATOR_RE = re.compile(r"^:?-+:?$")
_FENCED_CODE_BLOCK_RE = re.compile(r"```[\w]*\n?([\s\S]*?)```")


def strip_basic_inline_markdown(text: str) -> str:
    """Strip common inline Markdown markers for plain-text surfaces."""
    for pattern, repl in _BASIC_INLINE_STRIP_PATTERNS:
        text = pattern.sub(repl, text)
    return text.strip()


def display_width(text: str) -> int:
    """Return a monospace display width that accounts for wide CJK glyphs."""
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def parse_pipe_table_rows(table_lines: list[str]) -> tuple[list[list[str]], bool]:
    """Parse Markdown pipe-table lines into rows and report whether a separator exists."""
    rows: list[list[str]] = []
    has_separator = False
    for line in table_lines:
        cells = [strip_basic_inline_markdown(cell) for cell in line.strip().strip("|").split("|")]
        if all(_TABLE_SEPARATOR_RE.match(cell) for cell in cells if cell):
            has_separator = True
            continue
        rows.append(cells)
    return rows, has_separator


def render_pipe_table_box(table_lines: list[str]) -> str:
    """Render a Markdown pipe-table as compact aligned plain text."""
    rows, has_separator = parse_pipe_table_rows(table_lines)
    if not rows or not has_separator:
        return "\n".join(table_lines)

    column_count = max(len(row) for row in rows)
    for row in rows:
        row.extend([""] * (column_count - len(row)))
    widths = [
        max(display_width(row[column_index]) for row in rows)
        for column_index in range(column_count)
    ]

    def render_row(cells: list[str]) -> str:
        return "  ".join(
            f"{cell}{' ' * (width - display_width(cell))}"
            for cell, width in zip(cells, widths)
        )

    output = [render_row(rows[0])]
    output.append("  ".join("\u2500" * width for width in widths))
    for row in rows[1:]:
        output.append(render_row(row))
    return "\n".join(output)


def replace_pipe_tables(text: str, replace: Callable[[list[str]], str]) -> str:
    """Replace contiguous Markdown pipe-table lines using *replace*."""
    lines = text.split("\n")
    rebuilt: list[str] = []
    index = 0
    while index < len(lines):
        if _PIPE_TABLE_LINE_RE.match(lines[index]):
            table_lines: list[str] = []
            while index < len(lines) and _PIPE_TABLE_LINE_RE.match(lines[index]):
                table_lines.append(lines[index])
                index += 1
            rebuilt.append(replace(table_lines))
        else:
            rebuilt.append(lines[index])
            index += 1
    return "\n".join(rebuilt)


def protect_fenced_code_blocks(
    text: str,
    make_token: Callable[[int], str],
    *,
    include_fence: bool = False,
) -> tuple[str, list[str]]:
    """Replace fenced code blocks with tokens and return protected payloads."""
    protected: list[str] = []

    def save(match: re.Match[str]) -> str:
        protected.append(match.group(0) if include_fence else match.group(1))
        return make_token(len(protected) - 1)

    return _FENCED_CODE_BLOCK_RE.sub(save, text), protected
