"""Build one bounded grep page from streams of located source lines."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from itertools import chain, islice
from typing import Iterable, Literal

from nanobot.utils.document import LocatedDocumentLine


class MatchTooLargeError(ValueError):
    """A match and its source locator cannot fit in an empty page."""


def _clip_line(text: str, limit: int, match_start: int | None) -> str:
    if len(text) <= limit:
        return text
    marker = "..."
    available = limit - len(marker)
    if match_start is None:
        return text[:available] + marker
    start = min(max(0, match_start - available // 3), len(text) - available)
    end = start + available
    prefix = marker if start else ""
    suffix = marker if end < len(text) else ""
    visible = text[start:end]
    if prefix and suffix:
        visible = visible[: available - len(marker)]
    return prefix + visible + suffix


def _format_line(line: LocatedDocumentLine, start: int | None, limit: int) -> str:
    marker = ">" if start is not None else " "
    coordinate = str(line.extracted_line)
    if line.locator:
        coordinate += f" [{line.locator}]"
    return f"{marker} {coordinate}| {_clip_line(line.text, limit, start)}"


def _format_header(path: str, line: LocatedDocumentLine, start: int) -> str:
    locator = line.locator
    if locator.startswith("sheet="):
        column_index = line.text[:start].count("\t") + 1
        column = ""
        while column_index:
            column_index, remainder = divmod(column_index - 1, 26)
            column = chr(ord("A") + remainder) + column
        row = re.search(r",row=(\d+)$", locator)
        if row:
            locator += f",cell={column}{row[1]}"
    suffix = f" [{locator}]" if locator else ""
    return f"{path}:{line.extracted_line}{suffix}"


@dataclass
class ContentPage:
    """Select matches and append only context not already present in the page."""

    limit: int | None
    offset: int
    max_chars: int
    line_limit: int
    blocks: list[list[str]] = field(default_factory=list, init=False)
    seen: int = field(default=0, init=False)
    returned: int = field(default=0, init=False)
    chars: int = field(default=0, init=False)
    stopped: Literal["limit", "size"] | None = field(default=None, init=False)

    def scan(
        self, path: str, lines: Iterable[LocatedDocumentLine], regex: re.Pattern[str],
        before: int, after: int,
    ) -> None:
        source = (line for line in lines if line.searchable)
        history: deque[LocatedDocumentLine] = deque(maxlen=before)
        following = deque(islice(source, after + 1))
        positions: dict[int, int] = {}
        while following:
            match = regex.search(following[0].text)
            if match is not None:
                self.seen += 1
                if self.seen > self.offset:
                    if self.limit is not None and self.returned >= self.limit:
                        self.stopped = "limit"
                        return
                    self._append_match(path, history, following, match.start(), positions)
                    if self.stopped:
                        return
            history.append(following.popleft())
            if (line := next(source, None)) is not None:
                following.append(line)

    def _append_match(
        self, path: str, history: deque[LocatedDocumentLine],
        following: deque[LocatedDocumentLine], start: int, positions: dict[int, int],
    ) -> None:
        match = following[0]
        last_line = next(reversed(positions), 0)
        first_line = history[0] if history else match
        merge = bool(positions and first_line.extracted_line <= last_line)
        header = "" if merge else _format_header(path, match, start)
        replacement = _format_line(match, start, self.line_limit)
        additions = [
            (line.extracted_line, replacement if line is match else _format_line(line, None, self.line_limit))
            for line in chain(history, following)
            if not merge or line.extracted_line > last_line
        ]
        replace_at = positions.get(match.extracted_line) if merge else None
        replacement_chars = (
            len(replacement) - len(self.blocks[-1][replace_at]) if replace_at is not None else 0
        )
        header_chars = len(header) + (2 if self.blocks else 0) if not merge else 0
        added_chars = header_chars + sum(len(text) + 1 for _, text in additions) + replacement_chars
        if self.chars + added_chars > self.max_chars:
            self.stopped = "size"
            if self.blocks:
                return
            # Even an oversized first context must return a match and advance the offset.
            additions = [(match.extracted_line, replacement)]
            added_chars = header_chars + len(replacement) + 1
            if added_chars > self.max_chars:
                raise MatchTooLargeError("match exceeds output budget; narrow path or pattern")
        if not merge:
            self.blocks.append([header])
            positions.clear()
        block = self.blocks[-1]
        if replace_at is not None:
            block[replace_at] = replacement
        for line_number, text in additions:
            positions[line_number] = len(block)
            block.append(text)
        self.chars += added_chars
        self.returned += 1

    def render(self, no_matches: str) -> tuple[str, str | None]:
        result = "\n\n".join("\n".join(block) for block in self.blocks) or no_matches
        if self.stopped == "limit":
            note = f"pagination: limit={self.limit}, offset={self.offset}"
        elif self.stopped == "size":
            note = "output truncated due to size"
        else:
            note = f"(pagination: offset={self.offset})" if self.offset and self.blocks else None
            return result, note
        return result, f"({note}; use offset={self.offset + self.returned} to continue)"
