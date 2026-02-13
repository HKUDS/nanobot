"""Message splitting utilities for handling character limits across channels."""

import re
from typing import List
from loguru import logger


def split_telegram_message(text: str, limit: int = 4096) -> List[str]:
    """
    Split a message into chunks that fit within Telegram's 4096 character limit.
    Preserves HTML formatting and avoids breaking code blocks.

    Args:
        text: The message content (HTML formatted for Telegram)
        limit: Character limit (default: 4096 for Telegram)

    Returns:
        List of message chunks, each under the character limit
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        # If remaining fits, we're done
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Find a good split point within the limit
        chunk = _extract_chunk(remaining, limit)

        # Handle case where chunk couldn't be split properly
        if not chunk:
            logger.warning("Could not split message cleanly, forcing split")
            chunk = remaining[:limit]
            remaining = remaining[limit:]
        else:
            remaining = remaining[len(chunk):]

        chunks.append(chunk)

    return chunks


def _extract_chunk(text: str, limit: int) -> str | None:
    """
    Extract a chunk from text that fits within the limit.
    Tries to split at safe boundaries preserving HTML structure.

    Priority of split points:
    1. After closing </pre> tag (code blocks)
    2. At double newline (paragraphs)
    3. After closing </b>, </i>, </s>, </a>, </code> tag
    4. At single newline
    5. After punctuation (. ! ?)
    6. At space
    7. Force split at limit (last resort)

    Returns:
        The chunk to extract, or None if extraction failed
    """
    # Define HTML tags we care about preserving
    CONTAINER_TAGS = ['pre', 'code']  # These must stay together
    INLINE_TAGS = ['b', 'i', 's', 'a', 'u', 'strong', 'em']

    # First, check if we can fit everything
    if len(text) <= limit:
        return text

    # We need to find a split point. Work backwards from limit.
    search_space = text[:limit]

    # Track open tags to avoid breaking inside them
    open_tags = _find_open_tags(search_space)

    # Strategy 1: Split after a complete code block (</pre>)
    # Find the last </pre> before the limit
    last_pre_close = search_space.rfind('</pre>')
    if last_pre_close != -1 and last_pre_close > limit // 2:
        # Only use if we'd get a reasonably sized chunk
        return text[:last_pre_close + 6]  # +6 for '</pre>'

    # Strategy 2: Split at double newline (paragraph boundary)
    # Find last double newline that's not inside a pre/code block
    lines = search_space.split('\n')
    best_double_nl = -1
    current_pos = 0

    in_pre = False
    for i in range(len(lines) - 1):
        line = lines[i]
        if '<pre>' in line:
            in_pre = True
        if '</pre>' in line:
            in_pre = False

        if not in_pre and not line.strip().endswith('<br>'):
            # Check if next line is empty (double newline)
            if i + 1 < len(lines) and not lines[i + 1].strip():
                double_nl_pos = current_pos + len(line) + 2  # +2 for \n\n
                if double_nl_pos > limit * 0.5:  # At least 50% of limit
                    best_double_nl = double_nl_pos

        current_pos += len(line) + 1  # +1 for \n

    if best_double_nl != -1 and best_double_nl <= limit:
        return text[:best_double_nl]

    # Strategy 3: Split after closing inline formatting tags (but not inside container tags)
    # This prevents breaking bold/italic in the middle
    if 'pre' not in open_tags and 'code' not in open_tags:
        for tag in ['</b>', '</i>', '</s>', '</a>', '</u>', '</strong>', '</em>', '</code>']:
            last_tag = search_space.rfind(tag)
            if last_tag != -1 and last_tag > limit * 0.7:
                return text[:last_tag + len(tag)]

    # Strategy 4: Split at single newline (but not in code block)
    if 'pre' not in open_tags and 'code' not in open_tags:
        last_newline = search_space.rfind('\n')
        if last_newline > limit * 0.5:
            return text[:last_newline]

    # Strategy 5: Split after punctuation (but not in code block)
    if 'pre' not in open_tags and 'code' not in open_tags:
        # Look for . ! ? followed by space or end
        for punct in ['. ', '! ', '? ']:
            last_punct = search_space.rfind(punct)
            if last_punct != -1 and last_punct > limit * 0.7:
                return text[:last_punct + 2]  # +2 for punctuation + space

    # Strategy 6: Split at space (but not in code block)
    if 'pre' not in open_tags and 'code' not in open_tags:
        last_space = search_space.rfind(' ')
        if last_space > limit * 0.5:
            return text[:last_space]

    # Strategy 7: Force split at limit (worst case - might break HTML)
    # Try to at least avoid breaking a tag
    last_open_bracket = search_space.rfind('<')
    if last_open_bracket > limit - 100:  # If a tag starts near the limit
        # Split before the tag
        return text[:last_open_bracket].rstrip()

    # Last resort - just split at limit
    return text[:limit].rstrip()


def _find_open_tags(text: str) -> List[str]:
    """
    Find all HTML tags that are open (not closed) in the given text.

    Returns a list of tag names that are currently open.
    Only tracks formatting and container tags (b, i, pre, code, etc).
    """
    tags = []
    # Find all tags
    for match in re.finditer(r'</?([a-z]+)|/>', text, re.IGNORECASE):
        tag_content = match.group(0)
        tag_name = match.group(1)

        if not tag_name:
            # Self-closing tag or invalid, skip
            continue

        tag_name = tag_name.lower()

        # Only track formatting/container tags
        if tag_name not in ['b', 'i', 'u', 's', 'strong', 'em', 'a', 'pre', 'code']:
            continue

        if tag_content.startswith('</'):
            # Closing tag - remove from stack
            if tags and tags[-1] == tag_name:
                tags.pop()
        elif tag_content.endswith('/>'):
            # Self-closing tag, ignore
            pass
        else:
            # Opening tag
            tags.append(tag_name)

    return tags


def split_discord_message(text: str, limit: int = 2000) -> List[str]:
    """
    Split a message for Discord's 2000 character limit.
    Discord uses markdown, not HTML.

    Args:
        text: The message content (markdown formatted)
        limit: Character limit (default: 2000 for Discord)

    Returns:
        List of message chunks
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        chunk = _extract_markdown_chunk(remaining, limit)
        if not chunk:
            chunk = remaining[:limit]
            remaining = remaining[limit:]
        else:
            remaining = remaining[len(chunk):]

        chunks.append(chunk)

    return chunks


def _extract_markdown_chunk(text: str, limit: int) -> str | None:
    """
    Extract a chunk from markdown text that fits within the limit.
    Preserves code blocks and other formatting.
    """
    if len(text) <= limit:
        return text

    search_space = text[:limit]

    # Check for open code blocks
    in_code_block = search_space.count('```') % 2 == 1

    # Strategy 1: Split after code block close
    if in_code_block:
        # Find last ``` before limit and see if there's a closing one
        last_code_start = search_space.rfind('```')
        if last_code_start != -1:
            # Look for closing ``` after the start
            remainder = text[last_code_start:]
            code_close = remainder.find('```', 3)  # +3 to skip the opening ```
            if code_close != -1:
                split_point = last_code_start + code_close + 3
                if split_point <= limit:
                    return text[:split_point]

    # Strategy 2: Split at double newline (paragraph)
    last_double_nl = search_space.rstrip().rfind('\n\n')
    if last_double_nl != -1 and last_double_nl > limit * 0.5:
        return text[:last_double_nl]

    # Strategy 3: Split at newline
    last_newline = search_space.rfind('\n')
    if last_newline > limit * 0.5:
        return text[:last_newline]

    # Strategy 4: Split after punctuation
    for punct in ['. ', '! ', '? ']:
        last_punct = search_space.rfind(punct)
        if last_punct != -1 and last_punct > limit * 0.7:
            return text[:last_punct + 2]

    # Strategy 5: Split at space
    last_space = search_space.rfind(' ')
    if last_space > limit * 0.5:
        return text[:last_space]

    # Last resort - force split
    return text[:limit]
