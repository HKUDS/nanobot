"""X like tools — like, unlike, and get liked tweets via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XLikeTweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_like_tweet"

    @property
    def description(self) -> str:
        return (
            "Like a tweet on X. "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when confirming the liked tweet:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" size="inline"}\n'
            "Replace placeholders with actual values. If tweet text is not available from the response, omit the text attribute.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tweet_id": {"type": "string", "description": "The ID of the tweet to like."},
            },
            "required": ["tweet_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "tweet_id": kwargs["tweet_id"]}
        return await self._post(f"{coordinator_url}/internal/x/likes/like", payload)


class XUnlikeTweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_unlike_tweet"

    @property
    def description(self) -> str:
        return "Unlike a previously liked tweet on X. Authentication is automatic."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tweet_id": {"type": "string", "description": "The ID of the tweet to unlike."},
            },
            "required": ["tweet_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "tweet_id": kwargs["tweet_id"]}
        return await self._post(f"{coordinator_url}/internal/x/likes/unlike", payload)


class XGetLikedTweetsTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_liked_tweets"

    @property
    def description(self) -> str:
        return (
            "Get the authenticated user's liked tweets on X. Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH liked tweet in your response:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" metrics="<likes> likes · <retweets> retweets" size="compact"}\n'
            "Use compact size when listing multiple tweets. Replace placeholders with actual values from each tweet.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (10-100, default 10).",
                    "default": 10,
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id}
        if kwargs.get("max_results"):
            payload["max_results"] = kwargs["max_results"]
        return await self._post(f"{coordinator_url}/internal/x/likes/liked-tweets", payload)
