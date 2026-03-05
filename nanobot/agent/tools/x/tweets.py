"""X tweet tools — post, delete, get, search, user timeline, and mentions via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XPostTweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_post_tweet"

    @property
    def description(self) -> str:
        return (
            "Post a tweet on X (Twitter). Can optionally reply to an existing tweet or quote-tweet. "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when confirming the posted tweet:\n"
            '::x-tweet{text="<tweet_text>" author="@<your_username>" url="https://x.com/<your_username>/status/<tweet_id>" size="default"}\n'
            "Replace placeholders with actual values from the response. Use the tweet_id from the response for the url.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text content of the tweet (max 280 characters)."},
                "reply_to": {"type": "string", "description": "Tweet ID to reply to (optional)."},
                "quote_tweet_id": {"type": "string", "description": "Tweet ID to quote (optional)."},
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id, "text": kwargs["text"]}
        if kwargs.get("reply_to"):
            payload["reply_to"] = kwargs["reply_to"]
        if kwargs.get("quote_tweet_id"):
            payload["quote_tweet_id"] = kwargs["quote_tweet_id"]
        return await self._post(f"{coordinator_url}/internal/x/tweets/post", payload)


class XDeleteTweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_delete_tweet"

    @property
    def description(self) -> str:
        return (
            "Delete a tweet by its ID. Only works for tweets posted by the authenticated user. "
            "Authentication is automatic."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tweet_id": {"type": "string", "description": "The ID of the tweet to delete."},
            },
            "required": ["tweet_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "tweet_id": kwargs["tweet_id"]}
        return await self._post(f"{coordinator_url}/internal/x/tweets/delete", payload)


class XGetTweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_tweet"

    @property
    def description(self) -> str:
        return (
            "Get the full content of a specific tweet by its ID, including author info and engagement metrics. "
            "Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include this directive when presenting the tweet:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" metrics="<likes> likes · <retweets> retweets" size="default"}\n'
            "Replace placeholders with actual values. Build the url from the author's username and tweet id.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tweet_id": {"type": "string", "description": "The ID of the tweet to retrieve."},
            },
            "required": ["tweet_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "tweet_id": kwargs["tweet_id"]}
        return await self._post(f"{coordinator_url}/internal/x/tweets/get", payload)


class XSearchTweetsTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_search_tweets"

    @property
    def description(self) -> str:
        return (
            "Search recent tweets on X using a query string. Supports X search operators "
            "(e.g. 'from:username', '#hashtag', 'keyword -filter:retweets'). "
            "Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH matching tweet in your response:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" metrics="<likes> likes · <retweets> retweets" size="compact"}\n'
            "Use compact size when listing multiple tweets. Replace placeholders with actual values from each tweet.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "X search query string."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (10-100, default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload: dict[str, Any] = {"bot_id": bot_id, "query": kwargs["query"]}
        if kwargs.get("max_results"):
            payload["max_results"] = kwargs["max_results"]
        return await self._post(f"{coordinator_url}/internal/x/tweets/search", payload)


class XGetUserTweetsTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_user_tweets"

    @property
    def description(self) -> str:
        return (
            "Get recent tweets posted by a specific X user (by their X user ID). "
            "Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH tweet in your response:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" metrics="<likes> likes · <retweets> retweets" size="compact"}\n'
            "Use compact size when listing multiple tweets. Replace placeholders with actual values from each tweet.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The X user ID whose tweets to retrieve."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (5-100, default 10).",
                    "default": 10,
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
        return await self._post(f"{coordinator_url}/internal/x/tweets/user-tweets", payload)


class XGetUserMentionsTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_get_user_mentions"

    @property
    def description(self) -> str:
        return (
            "Get recent tweets mentioning a specific X user (by their X user ID). "
            "Authentication is automatic.\n\n"
            "DISPLAY FORMAT: Include a directive for EACH mention in your response:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" metrics="<likes> likes · <retweets> retweets" size="compact"}\n'
            "Use compact size when listing multiple mentions. Replace placeholders with actual values from each tweet.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The X user ID whose mentions to retrieve."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results (5-100, default 10).",
                    "default": 10,
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
        return await self._post(f"{coordinator_url}/internal/x/tweets/user-mentions", payload)
