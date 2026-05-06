from __future__ import annotations

from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.local_memory import (
    LocalMemoryConfig,
    build_capture_request,
    capture_candidate,
    has_local_memory_server,
    search_local_memory,
    should_capture_candidate,
    should_search_local_memory,
)


class LocalMemoryHook(AgentHook):
    def __init__(self, config: LocalMemoryConfig) -> None:
        self._config = config

    def _tools(self, context: AgentHookContext):
        if context.agent is None:
            return None
        return context.agent.tools

    async def before_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools(context)
        if tools is None:
            return
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.iteration != 1:
            return
        user_text = _latest_user_text(context.messages)
        if not user_text and not self._config.enable_bootstrap_recall:
            return
        if user_text and not should_search_local_memory(user_text, self._config):
            return
        if not user_text:
            user_text = "continue with active project context and user preferences"
        injection = await search_local_memory(tools, user_text, self._config)
        if not injection or not injection.content:
            return
        _insert_supplemental_system_message(
            context.messages,
            f"{injection.heading}:\n{injection.content}",
        )

    async def after_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools(context)
        if tools is None:
            return
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.stop_reason != "completed" or not context.final_content:
            return
        user_text = _latest_user_text(context.messages)
        if not should_capture_candidate(user_text, context.final_content, self._config):
            return
        request = build_capture_request(user_text, context.final_content, self._config)
        if request is None:
            return
        await capture_candidate(tools, request, self._config)


def _insert_supplemental_system_message(messages: list[dict[str, Any]], content: str) -> None:
    message = {"role": "system", "content": content}
    if messages and messages[0].get("role") == "system":
        messages.insert(1, message)
        return
    messages.insert(0, message)


def _latest_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text)
                return "\n".join(parts).strip()
    return ""
