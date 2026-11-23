from __future__ import annotations

import os
import re
from urllib.parse import urlparse


def abbreviate_path(path: str, max_len: int = 40) -> str:
    """Abbreviate a file path or URL, preserving basename and key directories.

    Strategy:
    1. Return as-is if short enough
    2. Replace home directory with ~/
    3. From right, keep basename + parent dirs until budget exhausted
    4. Prefix with …/
    """
    if not path:
        return path

    if re.match(r"https?://", path):
        return _abbreviate_url(path, max_len)

    normalized = path.replace("\\", "/")

    home = os.path.expanduser("~").replace("\\", "/")
    if normalized.startswith(home + "/"):
        normalized = "~" + normalized[len(home):]
    elif normalized == home:
        normalized = "~"

    if len(normalized) <= max_len:
        return normalized

    parts = normalized.rstrip("/").split("/")
    if len(parts) <= 1:
        return normalized[:max_len - 1] + "\u2026"

    basename = parts[-1]
    budget = max_len - len(basename) - 3

    kept: list[str] = []
    for seg in reversed(parts[:-1]):
        needed = len(seg) + 1
        if not kept and needed <= budget:
            kept.append(seg)
            budget -= needed
        elif kept:
            needed_with_sep = len(seg) + 1
            if needed_with_sep <= budget:
                kept.append(seg)
                budget -= needed_with_sep
            else:
                break
        else:
            break

    kept.reverse()
    if kept:
        return "\u2026/" + "/".join(kept) + "/" + basename
    return "\u2026/" + basename


def _abbreviate_url(url: str, max_len: int = 40) -> str:
    if len(url) <= max_len:
        return url

    parsed = urlparse(url)
    domain = parsed.netloc
    path_part = parsed.path

    segments = path_part.rstrip("/").split("/")
    basename = segments[-1] if segments else ""

    if not basename:
        return url[: max_len - 1] + "\u2026"

    budget = max_len - len(domain) - len(basename) - 4
    if budget < 0:
        trunc = max_len - len(domain) - 5
        return domain + "/\u2026/" + (basename[:trunc] if trunc > 0 else "")

    kept: list[str] = []
    for seg in reversed(segments[:-1]):
        if len(seg) + 1 <= budget:
            kept.append(seg)
            budget -= len(seg) + 1
        else:
            break

    kept.reverse()
    if kept:
        return domain + "/\u2026/" + "/".join(kept) + "/" + basename
    return domain + "/\u2026/" + basename
