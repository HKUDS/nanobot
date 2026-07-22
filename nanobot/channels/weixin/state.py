"""WeChat-owned persisted login-state detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.channels.contracts import channel_field_value
from nanobot.config.loader import get_config_path


def local_state_present(section: Any) -> bool:
    configured_dir = channel_field_value(section, "stateDir")
    state_dir = (
        Path(str(configured_dir)).expanduser()
        if configured_dir
        else get_config_path().parent / "weixin"
    )
    try:
        payload = json.loads((state_dir / "account.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return bool(str(payload.get("token") or "").strip())


__all__ = ["local_state_present"]
