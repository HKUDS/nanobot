"""X retweet tools — retweet and undo retweet via coordinator API."""

from typing import Any

from nanobot.agent.tools.x.base import XBaseTool


class XRetweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_retweet"

    @property
    def description(self) -> str:
        return (
            "Retweet a tweet on X. "
            "Authentication is automatic — never ask the user for credentials, tokens, or bot_id.\n\n"
            "DISPLAY FORMAT: Include this directive when confirming the retweet:\n"
            '::x-tweet{text="<tweet_text>" author="@<author_username>" url="https://x.com/<author_username>/status/<tweet_id>" size="inline"}\n'
            "Replace placeholders with actual values. If tweet text is not available from the response, omit the text attribute.\n"
            'Size options: "default" for standalone results, "compact" when listing multiple items, "inline" for brief mentions in text.'
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tweet_id": {"type": "string", "description": "The ID of the tweet to retweet."},
            },
            "required": ["tweet_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "tweet_id": kwargs["tweet_id"]}
        return await self._post(f"{coordinator_url}/internal/x/retweets/retweet", payload)


class XUndoRetweetTool(XBaseTool):

    @property
    def name(self) -> str:
        return "x_undo_retweet"

    @property
    def description(self) -> str:
        return "Undo a retweet on X. Authentication is automatic."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tweet_id": {"type": "string", "description": "The ID of the tweet to un-retweet."},
            },
            "required": ["tweet_id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        env = self._env()
        if isinstance(env, str):
            return env
        coordinator_url, bot_id = env
        payload = {"bot_id": bot_id, "tweet_id": kwargs["tweet_id"]}
        return await self._post(f"{coordinator_url}/internal/x/retweets/undo", payload)
