"""Pre-send prompt budgeting and context editing."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from nanobot.config.schema import ContextEditingConfig


class ContextEditor:
    """Prepare message lists for provider calls under a prompt budget."""

    _MESSAGE_OVERHEAD_TOKENS = 8

    def __init__(self, config: ContextEditingConfig | None = None):
        self.config = config or ContextEditingConfig()

    def prepare(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return a budgeted, edited copy of the message list."""
        prepared = [deepcopy(msg) for msg in messages]
        if not self.config.enabled or not prepared:
            return prepared

        self._strip_thinking(prepared)
        self._compact_old_tool_results(prepared)

        while self.estimate_tokens(prepared) > self.config.max_prompt_tokens:
            if not self._drop_oldest_turn(prepared):
                if self._compact_remaining_tool_result(prepared):
                    continue
                if self._compact_old_message(prepared):
                    continue
                if self._compact_last_user_message(prepared):
                    continue
                if self._drop_oldest_message(prepared):
                    continue
                break
            self._compact_old_tool_results(prepared)

        return prepared

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate prompt tokens from structured messages."""
        total = 0
        for msg in messages:
            total += self._MESSAGE_OVERHEAD_TOKENS
            total += self._estimate_value(msg.get("role"))
            total += self._estimate_value(msg.get("content"))

            for key in ("name", "tool_call_id", "reasoning_content", "thinking_blocks", "tool_calls"):
                if key in msg:
                    total += self._estimate_value(msg[key])
        return total

    def _strip_thinking(self, messages: list[dict[str, Any]]) -> None:
        for msg in messages:
            msg.pop("reasoning_content", None)
            msg.pop("thinking_blocks", None)

    def _compact_old_tool_results(self, messages: list[dict[str, Any]]) -> None:
        tool_positions = [idx for idx, msg in enumerate(messages) if msg.get("role") == "tool"]
        if len(tool_positions) <= self.config.keep_recent_tool_messages:
            return

        detail_cutoff = tool_positions[-self.config.keep_recent_tool_messages]
        for idx in tool_positions:
            if idx >= detail_cutoff:
                continue

            self._compact_tool_message(messages[idx])

    def _compact_remaining_tool_result(self, messages: list[dict[str, Any]]) -> bool:
        for msg in messages:
            if msg.get("role") != "tool":
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith("[context-edited tool result:"):
                continue
            self._compact_tool_message(msg)
            return True
        return False

    def _drop_oldest_turn(self, messages: list[dict[str, Any]]) -> bool:
        non_system = [idx for idx, msg in enumerate(messages) if msg.get("role") != "system"]
        keep_count = min(self.config.keep_recent_messages, len(non_system))
        droppable = non_system[: len(non_system) - keep_count]
        if not droppable:
            return False

        user_starts = [idx for idx in droppable if messages[idx].get("role") == "user"]
        if user_starts:
            start = user_starts[0]
            next_user = next(
                (idx for idx in non_system if idx > start and messages[idx].get("role") == "user"),
                None,
            )
            end = next_user if next_user is not None else (droppable[-1] + 1)
        else:
            start = droppable[0]
            end = start + 1

        del messages[start:end]
        return True

    def _compact_old_message(self, messages: list[dict[str, Any]]) -> bool:
        last_user_idx = next(
            (idx for idx in range(len(messages) - 1, -1, -1) if messages[idx].get("role") == "user"),
            None,
        )

        for idx, msg in enumerate(messages):
            if msg.get("role") == "system" or idx == last_user_idx:
                continue

            content = msg.get("content")
            if not isinstance(content, str):
                continue
            if content.startswith("[context-edited message]"):
                continue

            compact = " ".join(content.split())
            if len(compact) <= self.config.max_tool_chars:
                continue

            msg["content"] = f"[context-edited message] {compact[: self.config.max_tool_chars].rstrip()}..."
            return True
        return False

    def _compact_last_user_message(self, messages: list[dict[str, Any]]) -> bool:
        last_user_idx = next(
            (idx for idx in range(len(messages) - 1, -1, -1) if messages[idx].get("role") == "user"),
            None,
        )
        if last_user_idx is None:
            return False

        msg = messages[last_user_idx]
        content = msg.get("content")
        if not isinstance(content, str):
            return False
        if content.startswith("[context-edited message]"):
            return False

        compact = " ".join(content.split())
        if len(compact) <= self.config.max_tool_chars:
            return False

        msg["content"] = f"[context-edited message] {compact[: self.config.max_tool_chars].rstrip()}..."
        return True

    def _drop_oldest_message(self, messages: list[dict[str, Any]]) -> bool:
        last_user_idx = next(
            (idx for idx in range(len(messages) - 1, -1, -1) if messages[idx].get("role") == "user"),
            None,
        )

        for idx, msg in enumerate(messages):
            if msg.get("role") == "system" or idx == last_user_idx:
                continue
            del messages[idx]
            return True
        return False

    def _compact_tool_message(self, msg: dict[str, Any]) -> None:
        content = msg.get("content")
        if not isinstance(content, str):
            return

        compact = " ".join(content.split())
        if len(compact) > self.config.max_tool_chars:
            compact = compact[: self.config.max_tool_chars].rstrip() + "..."
        label = msg.get("name") or "tool"
        msg["content"] = f"[context-edited tool result: {label}] {compact}" if compact else f"[context-edited tool result: {label}]"

    def _estimate_value(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return max(1, len(value) // 4)
        if isinstance(value, list):
            return sum(self._estimate_value(item) for item in value)
        if isinstance(value, dict):
            if "type" in value and value.get("type") in {"text", "input_text", "output_text"}:
                return self._estimate_value(value.get("text"))
            if value.get("type") == "image_url":
                return self._estimate_value(value.get("image_url", {}).get("url"))
            return max(1, len(json.dumps(value, ensure_ascii=False)) // 4)
        return self._estimate_value(str(value))
