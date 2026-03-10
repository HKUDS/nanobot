"""X user tools — get me, get user by ID, get user by username via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XGetMeTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_me"

    @property
    def description(self) -> str:
        return (
            "Get the authenticated X user's profile (name, username, bio, follower count, etc.). "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when presenting the user profile:\n"
            '::x-user{name="<display_name>" username="@<username>" url="https://x.com/<username>" bio="<bio_text>" metrics="<followers_count> followers · <following_count> following" size="default"}\n'
            "Replace placeholders with actual values. Omit bio if not available.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id}
        return await self._post(f"{coordinator_url}/internal/x/users/me", payload)


class XGetUserByIdTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_user_by_id"

    @property
    def description(self) -> str:
        return (
            "Look up an X user by their numeric user ID. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include this directive when presenting the user:\n"
            '::x-user{name="<display_name>" username="@<username>" url="https://x.com/<username>" bio="<bio_text>" metrics="<followers_count> followers · <following_count> following" size="default"}\n'
            "Replace placeholders with actual values. Omit bio if not available.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The numeric X user ID to look up."},
            },
            "required": ["user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "user_id": kwargs["user_id"]}
        return await self._post(f"{coordinator_url}/internal/x/users/by-id", payload)


class XGetUserByUsernameTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_user_by_username"

    @property
    def description(self) -> str:
        return (
            "Look up an X user by their @username (without the @ symbol). "
            "Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include this directive when presenting the user:\n"
            '::x-user{name="<display_name>" username="@<username>" url="https://x.com/<username>" bio="<bio_text>" metrics="<followers_count> followers · <following_count> following" size="default"}\n'
            "Replace placeholders with actual values. Omit bio if not available.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "The X username to look up (without @)."},
            },
            "required": ["username"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "username": kwargs["username"]}
        return await self._post(f"{coordinator_url}/internal/x/users/by-username", payload)
