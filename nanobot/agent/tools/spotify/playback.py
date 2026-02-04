from typing import Any
from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.spotify import controller


class SpotifyPlayTool(Tool):

    @property
    def name(self) -> str:
        return "spotify_play"

    @property
    def description(self) -> str:
        return "Play or resume Spotify using system media controls."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        try:
            controller.play()
            return "Spotify playback started"
        except Exception as e:
            return f"Error playing Spotify: {e}"


class SpotifyPauseTool(Tool):

    @property
    def name(self) -> str:
        return "spotify_pause"

    @property
    def description(self) -> str:
        return "Pause Spotify playback."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        try:
            controller.pause()
            return "Spotify playback paused"
        except Exception as e:
            return f"Error pausing Spotify: {e}"


class SpotifyNextTool(Tool):

    @property
    def name(self) -> str:
        return "spotify_next"

    @property
    def description(self) -> str:
        return "Skip to next Spotify track."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        try:
            controller.next_track()
            return "Skipped to next track"
        except Exception as e:
            return f"Error skipping track: {e}"


class SpotifyPreviousTool(Tool):

    @property
    def name(self) -> str:
        return "spotify_previous"

    @property
    def description(self) -> str:
        return "Go to previous Spotify track."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        try:
            controller.previous_track()
            return "Moved to previous track"
        except Exception as e:
            return f"Error going to previous track: {e}"