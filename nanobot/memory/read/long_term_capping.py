"""Long-term memory text capping utilities.

Extracted from ``ContextAssembler`` to reduce file size (LAN-210 Phase 4.2).
Pure functions — no I/O, no class state.
"""

from __future__ import annotations

import re
from typing import Callable

__all__ = ["cap_long_term_text", "split_md_sections"]


def split_md_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown text into (heading, body) pairs.

    Sections are delimited by ``## `` headings.  Text before the first
    heading is returned with heading ``""``.
    """
    parts = re.split(r"(?m)^(## .+)$", text)
    sections: list[tuple[str, str]] = []
    if parts and not parts[0].startswith("## "):
        preamble = parts.pop(0).strip()
        if preamble:
            sections.append(("", preamble))
    while parts:
        heading = parts.pop(0).strip()
        body = parts.pop(0).strip() if parts else ""
        sections.append((heading, body))
    return sections


def cap_long_term_text(
    long_term_text: str,
    token_cap: int,
    query: str,
    estimate_tokens_fn: Callable[[str], int],
) -> str:
    """Return *long_term_text* capped to *token_cap* tokens.

    When the full text exceeds the cap, sections are ranked by a simple
    keyword-overlap score against *query* and the top sections that fit
    within the budget are selected (most relevant first).
    """
    if token_cap <= 0 or not long_term_text:
        return long_term_text

    if estimate_tokens_fn(long_term_text) <= token_cap:
        return long_term_text

    sections = split_md_sections(long_term_text)
    if not sections:
        # No headings — hard-truncate
        chars = token_cap * 4
        return long_term_text[:chars].rsplit("\n", 1)[0] + "\n(long-term memory truncated)"

    # Score each section by keyword overlap with the query
    query_words = set(query.lower().split()) if query else set()

    def _score(heading: str, body: str) -> float:
        text_words = set((heading + " " + body).lower().split())
        overlap = len(query_words & text_words)
        # Boost: shorter sections cost less budget and are proportionally more valuable
        brevity = 1.0 / max(1, estimate_tokens_fn(body) / 100)
        return overlap + brevity * 0.5

    scored = sorted(
        sections,
        key=lambda s: _score(s[0], s[1]),
        reverse=True,
    )

    selected: list[tuple[str, str]] = []
    used = 0
    for heading, body in scored:
        section_text = f"{heading}\n{body}" if heading else body
        section_tokens = estimate_tokens_fn(section_text)
        if used + section_tokens > token_cap and selected:
            break
        selected.append((heading, body))
        used += section_tokens

    # Preserve original ordering
    original_order = {id(s): i for i, s in enumerate(sections)}
    selected.sort(key=lambda s: original_order.get(id(s), 0))

    out_parts = []
    for heading, body in selected:
        if heading:
            out_parts.append(f"{heading}\n{body}")
        else:
            out_parts.append(body)

    result = "\n\n".join(out_parts)
    if len(selected) < len(sections):
        result += "\n(some long-term memory sections omitted to fit context budget)"
    return result
