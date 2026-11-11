"""Analyze bounded file reads; syntax support is registered by suffix."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Protocol
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

from nanobot.context_sources import SourceReceipt
from nanobot.utils.token_encoding import get_token_encoding

if TYPE_CHECKING:
    from tiktoken import Encoding


class ReferenceParser(Protocol):
    def references(self, content: str) -> Iterator[str]: ...


class MarkdownReferences:
    def references(self, content: str) -> Iterator[str]:
        for block in MarkdownIt("commonmark").parse(content):
            for token in block.children or ():
                if token.type == "link_open" and (href := token.attrGet("href")):
                    if isinstance(href, str):
                        yield href


# Bound retained source text, rather than evicting a normal prompt's working set
# after sixteen files. Results contain unresolved links so directory/symlink
# changes still take effect on every observation.
_ANALYSIS_SOURCE_BYTES = 4 * 1024 * 1024
_ANALYSIS_ENTRIES = 256
_analysis_cache: OrderedDict[
    tuple[str, ReferenceParser | None, Encoding | None],
    tuple[int, tuple[str, ...], int],
] = OrderedDict()
_analysis_bytes = 0
_analysis_lock = Lock()


def _analyze_source(content: str, parser: ReferenceParser | None) -> tuple[int, tuple[str, ...]]:
    global _analysis_bytes
    encoding = get_token_encoding()
    key = (content, parser, encoding)
    with _analysis_lock:
        if (cached := _analysis_cache.get(key)) is not None:
            _analysis_cache.move_to_end(key)
            return cached[0], cached[1]
    source_bytes = len(content.encode("utf-8"))
    links = tuple(dict.fromkeys(parser.references(content))) if parser else ()
    tokens = source_bytes
    if encoding is not None:
        try:
            tokens = len(encoding.encode_ordinary(content))
        except Exception:
            # Do not cache a transient encoding failure as a successful estimate.
            return tokens, links
    if source_bytes <= _ANALYSIS_SOURCE_BYTES:
        with _analysis_lock:
            # Concurrent observers may have analyzed the same content meanwhile.
            if key not in _analysis_cache:
                while _analysis_cache and (
                    _analysis_bytes + source_bytes > _ANALYSIS_SOURCE_BYTES
                    or len(_analysis_cache) >= _ANALYSIS_ENTRIES
                ):
                    _analysis_bytes -= _analysis_cache.popitem(last=False)[1][2]
                _analysis_cache[key] = (tokens, links, source_bytes)
                _analysis_bytes += source_bytes
    return tokens, links


REFERENCE_PARSERS: dict[str, ReferenceParser] = {
    ".md": MarkdownReferences(),
    ".markdown": MarkdownReferences(),
}
def source_receipt(path: Path, content: str, *, loaded: bool = True) -> SourceReceipt:
    """Discover links without opening, checking, or fetching their targets."""
    path = path.resolve()
    links: list[str] = []
    parser = REFERENCE_PARSERS.get(path.suffix.lower()) if loaded else None
    tokens, references = _analyze_source(content, parser) if loaded else (0, ())
    if parser:
        seen: set[str] = set()
        for href in references:
            if href in seen:
                continue
            seen.add(href)
            try:
                parsed = urlsplit(href)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                decoded_path = unquote(parsed.path)
                if "\x00" in decoded_path:
                    continue
                target = str((path.parent / decoded_path).resolve())
            except (ValueError, OSError, RuntimeError):
                # Link text is untrusted; invalid paths must not break prompt assembly.
                continue
            if target != str(path) and target not in links:
                links.append(target)
            if len(links) >= 128:
                break
    return {"path": str(path), "name": path.parent.name if path.name == "SKILL.md" else path.name, "tokens": tokens,
            "links": links, "loaded": loaded}


