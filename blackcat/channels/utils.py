"""
Channel utilities - pure functions and constants (no class state).

This module provides:
- Constants: paths, intervals, limits
- Text conversion: markdown_to_telegram_html, extract_markdown_tables
- File helpers: get_file_extension, MIME mappings
- Message formatting: format_reply_context

For the base class and stateful behavior, see base.py.
"""

import re
import unicodedata
from pathlib import Path

# ============================================================================
# Constants
# ============================================================================

MEDIA_DIR = Path.home() / ".blackcat" / "media"

# Typing indicator intervals (seconds) - platforms have different timeout behaviors
TYPING_INTERVAL_TELEGRAM = 4  # Telegram typing expires after ~5s
TYPING_INTERVAL_DISCORD = 8  # Discord typing expires after ~10s

# Reconnect backoff: starts at 5s, doubles each failure, caps at 1 hour
RECONNECT_DELAY_INITIAL = 5
RECONNECT_DELAY_MAX = 3600  # 1 hour
RECONNECT_DELAY_SECONDS = RECONNECT_DELAY_INITIAL  # backwards compat

# Attachment limits
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB

# Platform message length limits
MAX_MESSAGE_LENGTH_TELEGRAM = 4096
MAX_MESSAGE_LENGTH_DISCORD = 2000


# ============================================================================
# Markdown Conversion
# ============================================================================

def _strip_md(s: str) -> str:
    """Strip markdown inline formatting from text."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'~~(.+?)~~', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    return s.strip()


def markdown_to_telegram_html(text: str) -> str: # FIXME: Deadcode
    """
    Convert markdown to Telegram-safe HTML.

    Handles: code blocks, inline code, headers, blockquotes, links,
    bold, italic, strikethrough, bullet lists, and tables.
    """
    if not text:
        return ""

    # 0. Extract and convert markdown tables to preformatted blocks
    table_blocks: list[str] = []

    def save_table(m: re.Match) -> str:
        table_blocks.append(m.group(0))
        return f"\x00TB{len(table_blocks) - 1}\x00"

    # Match tables (lines with | separators)
    text = re.sub(
        r'(^[|].+[|]\n)(^[|][-:| ]+[|]\n)(^[|].+[|]\n?)+',
        save_table,
        text,
        flags=re.MULTILINE
    )

    # 1. Extract and protect code blocks
    code_blocks: list[str] = []

    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r"```[\w]*\n?([\s\S]*?)```", save_code_block, text)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []

    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", save_inline_code, text)

    # 3. Headers -> plain text
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)

    # 4. Blockquotes -> plain text
    text = re.sub(r"^>\s*(.*)$", r"\1", text, flags=re.MULTILINE)

    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # 7. Bold **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # 8. Italic _text_ (avoid matching inside words)
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<i>\1</i>", text)

    # 9. Strikethrough ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # 10. Bullet lists
    text = re.sub(r"^[-*]\s+", "• ", text, flags=re.MULTILINE)

    # 11. Restore inline code
    for i, code in enumerate(inline_codes):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks
    for i, code in enumerate(code_blocks):
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    # 13. Restore tables as preformatted blocks
    for i, table in enumerate(table_blocks):
        lines = table.strip().split('\n')
        rendered = _render_table_box(lines)
        escaped = rendered.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00TB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text

def _render_table_box(table_lines: list[str]) -> str:
    """Convert markdown pipe-table to compact aligned text for <pre> display."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip('|').split('|')]
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return '\n'.join(table_lines)

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([''] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return '  '.join(f'{c}{" " * (w - dw(c))}' for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append('  '.join('─' * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return '\n'.join(out)

