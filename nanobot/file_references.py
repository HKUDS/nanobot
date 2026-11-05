"""Analyze bounded file reads; syntax support is registered by suffix."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
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
        if len(content) <= 128_000:
            yield from self._cached_references(content)
        else:
            yield from self._references(content)

    @staticmethod
    @lru_cache(maxsize=16)
    def _cached_references(content: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(MarkdownReferences._references(content)))

    @staticmethod
    def _references(content: str) -> Iterator[str]:
        for block in MarkdownIt("commonmark").parse(content):
            for token in block.children or ():
                if token.type == "link_open" and (href := token.attrGet("href")):
                    if isinstance(href, str):
                        yield href


@lru_cache(maxsize=16)
def _encoded_source_tokens(content: str, encoding: Encoding) -> int:
    return len(encoding.encode_ordinary(content))


def _source_tokens(content: str) -> int:
    encoding = get_token_encoding()
    if encoding is not None:
        try:
            return (_encoded_source_tokens(content, encoding) if len(content) <= 128_000
                    else len(encoding.encode_ordinary(content)))
        except Exception:
            pass
    return len(content.encode("utf-8"))


REFERENCE_PARSERS: dict[str, ReferenceParser] = {
    ".md": MarkdownReferences(),
    ".markdown": MarkdownReferences(),
}
def source_receipt(path: Path, content: str, *, loaded: bool = True) -> SourceReceipt:
    """Discover links without opening, checking, or fetching their targets."""
    path = path.resolve()
    links: list[str] = []
    parser = REFERENCE_PARSERS.get(path.suffix.lower()) if loaded else None
    if parser:
        seen: set[str] = set()
        for href in parser.references(content):
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
    return {"path": str(path), "name": path.parent.name if path.name == "SKILL.md" else path.name, "tokens": _source_tokens(content) if loaded else 0,
            "links": links, "loaded": loaded}


