"""Example plugin: weather lookup via wttr.in.

Demonstrates making HTTP requests from a plugin tool.
Copy to ~/.nanobot/workspace/tools/ and restart nanobot.

Requires: httpx (already a nanobot dependency)
"""

import httpx

from nanobot.agent.tools import Tool


class WeatherTool(Tool):
    """Get current weather for a city using the free wttr.in API."""

    @property
    def name(self):
        return "weather"

    @property
    def description(self):
        return "Get current weather for a city using wttr.in"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name (e.g. 'London', 'New York')",
                },
            },
            "required": ["city"],
        }

    async def execute(self, city: str, **kwargs) -> str:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"https://wttr.in/{city}",
                    params={"format": "3"},
                    timeout=10.0,
                )
                r.raise_for_status()
                return r.text.strip()
        except Exception as e:
            return f"Error fetching weather: {e}"
