"""Generate ephemeral follow-up suggestions for authenticated WebUI requests."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal, TypedDict, cast

from loguru import logger

from nanobot.config.schema import Config
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.session.webui_turns import take_completed_websocket_turn_runtime
from nanobot.utils.prompt_templates import render_template
from nanobot.webui.token_usage import record_response_token_usage

_CHAT_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,64}$")
_GENERATION_TIMEOUT_SECONDS = 15
_MAX_CONTEXT_MESSAGES = 6
_MAX_MESSAGE_CHARS = 4_000
_MAX_SUGGESTIONS = 3
_MAX_SUGGESTION_CHARS = 200


class _ConversationMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class FollowUpRequestError(ValueError):
    """The browser sent an invalid follow-up request payload."""


def _request_context(payload: dict[str, Any]) -> tuple[str, str, list[_ConversationMessage]]:
    chat_id = payload.get("chat_id")
    if not isinstance(chat_id, str) or _CHAT_ID_RE.fullmatch(chat_id) is None:
        raise FollowUpRequestError("invalid chat_id")
    turn_id = payload.get("turn_id")
    if not isinstance(turn_id, str) or _CHAT_ID_RE.fullmatch(turn_id) is None:
        raise FollowUpRequestError("invalid turn_id")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise FollowUpRequestError("messages must be an array")

    messages: list[_ConversationMessage] = []
    for item in cast(list[object], raw_messages):
        if not isinstance(item, dict):
            raise FollowUpRequestError("messages must contain objects")
        typed_item = cast(dict[object, object], item)
        role = typed_item.get("role")
        content = typed_item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            raise FollowUpRequestError("messages must contain conversational text")
        content = content.strip()[:_MAX_MESSAGE_CHARS]
        if content:
            messages.append({"role": cast(Literal["user", "assistant"], role), "content": content})
    return chat_id, turn_id, messages[-_MAX_CONTEXT_MESSAGES:]


def _normalize_suggestions(content: str | None) -> list[str]:
    if not content:
        return []
    parsed = json.loads(content)
    if not isinstance(parsed, list):
        raise ValueError("suggestions response must be a JSON array")

    suggestions: list[str] = []
    seen: set[str] = set()
    for item in cast(list[object], parsed):
        if not isinstance(item, str):
            continue
        suggestion = " ".join(item.split())[:_MAX_SUGGESTION_CHARS].rstrip()
        if not suggestion or suggestion.startswith("/") or suggestion in seen:
            continue
        seen.add(suggestion)
        suggestions.append(suggestion)
        if len(suggestions) == _MAX_SUGGESTIONS:
            break
    return suggestions


async def generate_follow_up_suggestions(
    *,
    config: Config,
    payload: dict[str, Any],
) -> list[str]:
    chat_id, turn_id, messages = _request_context(payload)
    if not config.follow_up_suggestions.enabled or not messages:
        return []
    runtime = take_completed_websocket_turn_runtime(chat_id, turn_id)
    if runtime is None:
        return []

    response = None
    request_started = False
    try:
        provider = runtime.provider
        if isinstance(provider, FallbackProvider):
            provider = provider.primary_provider
        provider_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": render_template("agent/follow_up_suggestions.md", strip=True),
            }
        ]
        provider_messages.extend(dict(message) for message in messages)
        request_started = True
        async with asyncio.timeout(_GENERATION_TIMEOUT_SECONDS):
            response = await provider.chat(
                provider_messages,
                tools=None,
                model=runtime.model,
                max_tokens=runtime.generation.max_tokens,
                temperature=runtime.generation.temperature,
                reasoning_effort="none",
            )
        if response.finish_reason == "error":
            logger.warning("WebUI follow-up suggestion provider returned an error for {}", chat_id)
            return []
        return _normalize_suggestions(response.content)
    except Exception:
        logger.opt(exception=True).warning(
            "WebUI follow-up suggestion generation failed for {}",
            chat_id,
        )
        return []
    finally:
        if request_started:
            record_response_token_usage(
                response,
                source="user",
                timezone_name=config.agents.defaults.timezone,
                count_request=True,
            )
