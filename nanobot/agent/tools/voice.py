"""Tool for controlling text-to-speech output."""

from typing import Any

from nanobot.agent.tools.base import Tool


class VoiceTool(Tool):
    """
    Enable or disable text-to-speech output for responses.

    Usage:
    - voice(on) - Enable voice output for responses
    - voice(off) - Disable voice output
    - voice(status) - Check current voice status

    Voice state is stored in session metadata by the agent loop.
    """

    name = "voice"
    description = (
        "Enable or disable text-to-speech output. "
        "Use: voice('on') to enable, voice('off') to disable, voice('status') to check."
    )

    @property
    def parameters(self) -> dict[str, Any]:
        """Tool parameter schema."""
        return {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": ["on", "off", "status"],
                    "description": "Voice state: 'on' to enable, 'off' to disable, 'status' to check.",
                }
            },
            "required": ["state"],
        }

    def __init__(self, available_voices=None):
        """
        Initialize the voice tool.

        Args:
            available_voices: List of available voice names.
        """
        self.available_voices = available_voices or []

    async def execute(self, state: str) -> str:
        """
        Execute the voice command.

        Note: Session metadata is updated by the agent loop based on
        the state argument. This tool just returns a confirmation message.

        Args:
            state: Command state ("on", "off", "status").

        Returns:
            Response message.
        """
        state_lower = state.lower().strip()

        if state_lower in ("on", "enabled", "true", "yes"):
            voices_msg = ""
            if self.available_voices:
                voices_msg = f" Available voices: {', '.join(self.available_voices)}"
            return f"Voice output enabled.{voices_msg}"

        elif state_lower in ("off", "disabled", "false", "no"):
            return "Voice output disabled."

        elif state_lower in ("status", "current", "check"):
            # The agent loop will check session metadata
            return "Voice status check requested."

        else:
            return (
                f"Unknown voice state: {state}. "
                f"Use 'on', 'off', or 'status'."
            )
