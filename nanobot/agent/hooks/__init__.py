"""Concrete agent hook implementations."""

from nanobot.agent.hooks.file_edit_activity import (
    FileEditActivityHook,
    create_file_edit_activity_hook,
)
from nanobot.agent.hooks.sound_hook import (
    SoundCompletionHook,
    create_sound_hook,
)

__all__ = [
    "FileEditActivityHook",
    "create_file_edit_activity_hook",
    "SoundCompletionHook",
    "create_sound_hook",
]
