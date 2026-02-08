# nanobot/agent/tools/memory_box/utils.py

"""
memory_box.utils:

Utility functions for memory box.
 - credits: File contains codes from Nanobot
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

# credits: https://github.com/HKUDS/nanobot/blob/625fc6028237c690b9b2896fd680de98d13136da/nanobot/utils/helpers.py#L7
def ensure_dir(p: Path) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p

# credits: https://github.com/HKUDS/nanobot/blob/625fc6028237c690b9b2896fd680de98d13136da/nanobot/utils/helpers.py#L52
def today_date() -> str:
    """Local YYYY-MM-DD."""
    return datetime.now().astimezone().date().isoformat()
