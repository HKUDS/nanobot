"""X follow tools — follow, unfollow, get followers, get following via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XFollowUserTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_follow_user"

    @property
    def description(self) -> str:
        return (
            "Follow a user on X by their user ID. "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when confirming the follow:\n"
            '::x-user{name="<display_name>" username="@<username>" url="https://x.com/<username>" size="inline"}\n'
            "Replace placeholders with actual values from the response. Omit attributes not available.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_user_id": {"type": "string", "description": "The X user ID of the user to follow."},
            },
            "required": ["target_user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "target_user_id": kwargs["target_user_id"]}
        return await self._post(f"{coordinator_url}/internal/x/follows/follow", payload)


class XUnfollowUserTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_unfollow_user"

    @property
    def description(self) -> str:
        return "Unfollow a user on X by their user ID. Authentication is automatic."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target_user_id": {"type": "string", "description": "The X user ID of the user to unfollow."},
            },
            "required": ["target_user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "target_user_id": kwargs["target_user_id"]}
        return await self._post(f"{coordinator_url}/internal/x/follows/unfollow", payload)


class XGetFollowersTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_followers"

    @property
    def description(self) -> str:
        return (
            "Get the followers of an X user by their user ID. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH follower in your response:\n"
            '::x-user{name="<display_name>" username="@<username>" url="https://x.com/<username>" metrics="<followers_count> followers" size="compact"}\n'
            "Use compact size when listing multiple users. Replace placeholders with actual values from each user.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The X user ID whose followers to list."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (1-1000, default 100).",
                    "default": 100,
                },
            },
            "required": ["user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id, "user_id": kwargs["user_id"]}
        if kwargs.get("max_results"):
            payload["max_results"] = kwargs["max_results"]
        return await self._post(f"{coordinator_url}/internal/x/follows/followers", payload)


class XGetFollowingTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_following"

    @property
    def description(self) -> str:
        return (
            "Get the users that an X user is following by their user ID. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH followed user in your response:\n"
            '::x-user{name="<display_name>" username="@<username>" url="https://x.com/<username>" metrics="<followers_count> followers" size="compact"}\n'
            "Use compact size when listing multiple users. Replace placeholders with actual values from each user.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The X user ID whose following list to retrieve."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (1-1000, default 100).",
                    "default": 100,
                },
            },
            "required": ["user_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id, "user_id": kwargs["user_id"]}
        if kwargs.get("max_results"):
            payload["max_results"] = kwargs["max_results"]
        return await self._post(f"{coordinator_url}/internal/x/follows/following", payload)
