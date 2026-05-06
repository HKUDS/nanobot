from __future__ import annotations

from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.local_memory import (
    LocalMemoryConfig,
    build_capture_request,
    build_session_summary_capture,
    build_session_summary_capture_request_from_summary,
    capture_candidate,
    forget_local_memory,
    has_local_memory_server,
    search_local_memory,
    should_capture_candidate,
    should_search_local_memory,
)


class LocalMemoryHook(AgentHook):
    def __init__(self, config: LocalMemoryConfig) -> None:
        self._config = config

    async def capture_pre_reset_session_summary(
        self,
        context: AgentHookContext,
        assistant_text: str,
    ) -> None:
        tools = self._tools(context)
        if tools is None:
            return
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        user_text = _latest_user_text(context.messages)
        capture = build_session_summary_capture(user_text, assistant_text, self._config)
        if capture is None:
            return
        request = build_session_summary_capture_request_from_summary(
            capture.summary_text,
            capture.query_kind,
            self._config,
        )
        if request is None:
            return
        await capture_candidate(tools, request, self._config)

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
        user_text = _latest_user_text(context.messages)
        if context.iteration == 1:
            forget_query = _extract_forget_query(user_text)
            if forget_query:
                context.memory_action = "forget"
                context.memory_target_query = forget_query
                _insert_supplemental_system_message(
                    context.messages,
                    "Local memory instruction: the user asked to forget a remembered item. Confirm removal if matched, and do not rely on that memory.",
                )
                return
            if not user_text and not self._config.enable_bootstrap_recall:
                return
            if user_text and not should_search_local_memory(user_text, self._config):
                return
            if not user_text:
                user_text = "continue with active project context, next steps, and user preferences including preferred name and username"
            injection = await search_local_memory(tools, user_text, self._config)
            if not injection or not injection.content:
                return
            _insert_supplemental_system_message(
                context.messages,
                injection.content,
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        tools = self._tools(context)
        if tools is None:
            return
        if not self._config.enabled or not has_local_memory_server(tools, self._config.server_name):
            return
        if context.memory_action == "forget" and context.memory_target_query:
            forgotten = await forget_local_memory(tools, context.memory_target_query, self._config)
            if forgotten and context.final_content:
                context.final_content = f"Forgot it from local memory: {context.memory_target_query}\n\n{context.final_content}"
            elif context.final_content:
                context.final_content = f"I tried to forget that from local memory but did not find a clear matching record.\n\n{context.final_content}"
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


def _extract_forget_query(user_text: str) -> str | None:
    text = user_text.strip()
    if not text:
        return None
    lowered = text.lower().strip()
    prefixes = (
        "forget that",
        "forget this",
        "forget it",
        "stop remembering",
        "deprecate that memory",
        "deprecate this memory",
    )
    for prefix in prefixes:
        if lowered == prefix:
            return "recent memory"
        if lowered.startswith(prefix + " "):
            remainder = text[len(prefix):].strip(" :,-")
            return remainder or "recent memory"
    return None


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
