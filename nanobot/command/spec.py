from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from nanobot.command_copy import command_text

# WebUI protocol contract for how a slash command participates in turn state:
# - side_channel: returns control text without starting or ending an agent turn.
# - finalize_active_turn: side-channel command that also closes the active UI turn.
# - stop_active_turn: cancels the active turn; WebUI may intercept exact submits.
# - agent_turn: always enters the normal agent path.
# - agent_turn_with_args: no args is side-channel usage; args enter the agent path.
CommandLifecycle = Literal[
    "side_channel",
    "finalize_active_turn",
    "stop_active_turn",
    "agent_turn",
    "agent_turn_with_args",
]


@dataclass(frozen=True)
class BuiltinCommandSpec:
    command: str
    title: str
    description: str
    icon: str
    arg_hint: str = ""
    lifecycle: CommandLifecycle = "side_channel"
    accepts_args: bool = False
    description_key: str | None = None

    @classmethod
    def localized(
        cls, command: str, icon: str, arg_hint: str = "", *,
        lifecycle: CommandLifecycle = "side_channel", accepts_args: bool = False,
    ) -> BuiltinCommandSpec:
        prefix = f"palette.{command.removeprefix('/')}"
        description_key = f"{prefix}.description"
        return cls(
            command=command, icon=icon, arg_hint=arg_hint, lifecycle=lifecycle, accepts_args=accepts_args,
            title=command_text(f"{prefix}.title", "en"), description=command_text(description_key, "en"),
            description_key=description_key,
        )

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "command": self.command,
            "title": self.title,
            "description": self.description,
            "icon": self.icon,
            "arg_hint": self.arg_hint,
            "lifecycle": self.lifecycle,
            "accepts_args": self.accepts_args,
        }
