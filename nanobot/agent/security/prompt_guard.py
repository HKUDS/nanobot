"""Prompt injection defense utilities."""
import re
from typing import Optional
from loguru import logger

INJECTION_PATTERNS = [
    r'(?i)ignore\s+(all\s+)?previous\s+instructions',
    r'(?i)disregard\s+(all\s+)?prior\s+(instructions|context)',
    r'(?i)you\s+are\s+now\s+a',
    r'(?i)new\s+instructions?:',
    r'(?i)system\s*:\s*',
    r'(?i)\[system\]',
    r'(?i)<<\s*SYS\s*>>',
    r'(?i)\[INST\]',
    r'(?i)execute\s+(shell|command|bash)',
]


def detect_injection(content: str) -> list[str]:
    """Detect potential prompt injection patterns.

    Args:
        content: The content to scan for injection patterns.

    Returns:
        A list of patterns that matched in the content.
    """
    return [p for p in INJECTION_PATTERNS if re.search(p, content)]


def sanitize_external_content(content: str, source: str = "web") -> str:
    """Sanitize external content with boundary markers.

    This function wraps external content in boundary markers and sanitizes
    potentially dangerous patterns that could be used for prompt injection.

    Args:
        content: The external content to sanitize.
        source: The source of the content (e.g., "web", "file", "api").

    Returns:
        Sanitized content wrapped in boundary markers.
    """
    injections = detect_injection(content)
    if injections:
        logger.warning(f"SECURITY: Potential prompt injection from {source}")

    # Sanitize role markers that could confuse the LLM
    sanitized = re.sub(r'(?i)(system|assistant|user)\s*:', r'[\1]:', content)
    sanitized = re.sub(r'(?i)<<\s*SYS\s*>>', '[SYS]', sanitized)

    return f'<external_content source="{source}">\n{sanitized}\n</external_content>'
