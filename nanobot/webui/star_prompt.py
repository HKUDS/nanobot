"""Instance-local usage and dismissal state for the optional GitHub invitation."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Literal

from filelock import FileLock
from pydantic import BaseModel, Field

from nanobot.config.paths import get_webui_dir
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

COOLDOWN_SECONDS = 30 * 24 * 60 * 60


class StarPromptState(BaseModel):
    completed_replies: int = Field(default=0, ge=0, le=10)
    active_days: list[str] = Field(default_factory=list, max_length=3)
    recent_turns: list[str] = Field(default_factory=list, max_length=10)
    shown_count: int = Field(default=0, ge=0, le=2)
    next_prompt_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    dismissed_forever: bool = False


def update_star_prompt(
    action: Literal["completed", "claim", "dismiss"],
    *,
    turn_id: str = "",
) -> bool:
    """Persist before granting a display; serialize claims across gateway processes.

    A claim starts the cooldown even if the browser closes before displaying it.
    Invalid existing state raises instead of resetting a user's dismissal.
    """
    path = get_webui_dir() / "star-prompt.json"
    with FileLock(str(path) + ".lock", timeout=2):
        state = (
            StarPromptState.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists() else StarPromptState()
        )
        if state.dismissed_forever or (state.shown_count >= 2 and action != "dismiss"):
            return False
        now = time.time()
        granted = False
        if action == "dismiss":
            state.dismissed_forever = True
        elif action == "completed":
            if not turn_id or turn_id in state.recent_turns:
                return False
            day = datetime.fromtimestamp(now, UTC).date().isoformat()
            if state.completed_replies >= 10 and len(state.active_days) >= 3:
                return False
            state.completed_replies = min(10, state.completed_replies + 1)
            if day not in state.active_days and len(state.active_days) < 3:
                state.active_days.append(day)
            state.recent_turns = [*state.recent_turns[-9:], turn_id]
        else:
            if (
                state.completed_replies < 10 or len(state.active_days) < 3
                or now < state.next_prompt_at
            ):
                return False
            state.shown_count += 1
            state.next_prompt_at = now + COOLDOWN_SECONDS
            granted = True
        _write_text_atomic(path, state.model_dump_json(indent=2))
        return granted
