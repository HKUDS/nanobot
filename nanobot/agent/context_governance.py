"""Model-message governance for agent runner requests.

This module owns model-facing message shaping and tool-result content normalization.
It may return copied messages or persisted-result placeholders, but it must not
mutate an existing session history list in place.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.utils.helpers import (
    estimate_message_tokens,
    estimate_prompt_tokens_chain,
    find_legal_message_start,
    maybe_persist_tool_result,
    truncate_text,
)
from nanobot.utils.runtime import ensure_nonempty_tool_result

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

SNIP_SAFETY_BUFFER = 1024
MICROCOMPACT_KEEP_RECENT = 10
MICROCOMPACT_MIN_CHARS = 500
STALE_ERROR_USER_TURNS = 4
ADAPTIVE_TOOL_RESULT_MIN_CHARS = 4_000
ADAPTIVE_TOOL_RESULT_BUDGET_RATIO = 0.08
SUBAGENT_RESULT_MAX_CHARS = 6_000
INFLIGHT_COMPACT_TARGET_RATIO = 0.85
COMPACTABLE_TOOLS = frozenset({
    "read_file", "exec", "grep", "find_files",
    "web_search", "web_fetch", "list_dir", "list_exec_sessions",
})
# read_file is the recovery path for persisted results; exempting it prevents persist->read->persist loops.
TOOL_RESULT_OFFLOAD_EXEMPT_TOOLS = frozenset({"read_file"})
BACKFILL_CONTENT = "[Tool result unavailable — call was interrupted or lost]"


@dataclass(slots=True)
class ContextGovernanceConfig:
    provider: LLMProvider
    model: str
    tools: Any
    workspace: Path | None
    session_key: str | None
    max_tool_result_chars: int
    context_window_tokens: int | None = None
    context_block_limit: int | None = None
    max_tokens: int | None = None
    inflight_start_index: int = 0


class ContextGovernor:
    """Prepare model-copy messages while preserving persisted history."""

    def prepare_for_model(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        compacted_tool_call_ids: set[str],
    ) -> list[dict[str, Any]]:
        updated = self.drop_orphan_tool_results(messages)
        updated = self.backfill_missing_tool_results(updated)
        updated = self.compact_subagent_announcements(updated)
        updated = self.apply_tool_result_budget(config, updated)
        updated = self.compact_duplicate_tool_results(updated)
        updated = self.compact_stale_error_tool_results(updated)
        updated = self.compact_inflight_overflow(config, updated, compacted_tool_call_ids)
        updated = self.snip_history(config, updated)
        updated = self.drop_orphan_tool_results(updated)
        return self.backfill_missing_tool_results(updated)

    @staticmethod
    def input_budget(config: ContextGovernanceConfig) -> int:
        if not config.context_window_tokens:
            return 0

        provider_max_tokens = getattr(
            getattr(config.provider, "generation", None),
            "max_tokens",
            4096,
        )
        max_output = config.max_tokens if isinstance(config.max_tokens, int) else (
            provider_max_tokens if isinstance(provider_max_tokens, int) else 4096
        )
        budget = config.context_block_limit or (
            config.context_window_tokens - max_output - SNIP_SAFETY_BUFFER
        )
        return budget if budget > 0 else 0

    @staticmethod
    def normalize_tool_result(
        config: ContextGovernanceConfig,
        tool_call_id: str,
        tool_name: str,
        result: Any,
        *,
        max_chars: int | None = None,
    ) -> Any:
        result = ensure_nonempty_tool_result(tool_name, result)
        if tool_name in TOOL_RESULT_OFFLOAD_EXEMPT_TOOLS:
            return result
        max_chars = max_chars if max_chars is not None else config.max_tool_result_chars
        try:
            content = maybe_persist_tool_result(
                config.workspace,
                config.session_key,
                tool_call_id,
                result,
                max_chars=max_chars,
            )
        except Exception:
            logger.exception(
                "Tool result persist failed for {} in {}; using raw result",
                tool_call_id,
                config.session_key or "default",
            )
            content = result
        if isinstance(content, str) and len(content) > max_chars:
            return truncate_text(content, max_chars)
        return content

    @staticmethod
    def drop_orphan_tool_results(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Drop tool results that have no matching assistant tool_call earlier in history."""
        declared: set[str] = set()
        updated: list[dict[str, Any]] | None = None
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        declared.add(str(tc["id"]))
            if role == "tool":
                tid = msg.get("tool_call_id")
                if tid and str(tid) not in declared:
                    if updated is None:
                        updated = [dict(m) for m in messages[:idx]]
                    continue
            if updated is not None:
                updated.append(dict(msg))

        if updated is None:
            return messages
        return updated

    @staticmethod
    def backfill_missing_tool_results(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Insert synthetic error results for assistant tool_calls with missing tool outputs."""
        declared: list[tuple[int, str, str]] = []
        fulfilled: set[str] = set()
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict) and tc.get("id"):
                        name = ""
                        func = tc.get("function")
                        if isinstance(func, dict):
                            name = func.get("name", "")
                        declared.append((idx, str(tc["id"]), name))
            elif role == "tool":
                tid = msg.get("tool_call_id")
                if tid:
                    fulfilled.add(str(tid))

        missing = [(ai, cid, name) for ai, cid, name in declared if cid not in fulfilled]
        if not missing:
            return messages

        updated = list(messages)
        offset = 0
        for assistant_idx, call_id, name in missing:
            insert_at = assistant_idx + 1 + offset
            while insert_at < len(updated) and updated[insert_at].get("role") == "tool":
                insert_at += 1
            updated.insert(insert_at, {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": BACKFILL_CONTENT,
            })
            offset += 1
        return updated

    def apply_tool_result_budget(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        updated = messages
        max_chars = self._effective_tool_result_chars(config)
        for idx, message in enumerate(messages):
            if message.get("role") != "tool":
                continue
            normalized = self.normalize_tool_result(
                config,
                str(message.get("tool_call_id") or f"tool_{idx}"),
                str(message.get("name") or "tool"),
                message.get("content"),
                max_chars=max_chars,
            )
            if normalized != message.get("content"):
                if updated is messages:
                    updated = [dict(m) for m in messages]
                updated[idx]["content"] = normalized
        return updated

    def compact_inflight_overflow(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        compacted_tool_call_ids: set[str],
    ) -> list[dict[str, Any]]:
        """Compact in-flight tool results only when the request would overflow."""
        budget = self.input_budget(config)
        if budget <= 0:
            return messages

        tools = config.tools.get_definitions()
        updated = self._apply_recorded_compactions(messages, compacted_tool_call_ids)
        estimate, source = estimate_prompt_tokens_chain(
            config.provider,
            config.model,
            updated,
            tools,
        )
        if estimate <= budget:
            return updated

        target = int(budget * INFLIGHT_COMPACT_TARGET_RATIO)
        candidates = self._inflight_compaction_candidates(
            config,
            updated,
            compacted_tool_call_ids,
        )
        if not candidates:
            return updated

        for candidate_idx, (idx, tool_call_id) in enumerate(candidates):
            is_newest_candidate = candidate_idx == len(candidates) - 1
            if is_newest_candidate and estimate <= budget:
                break
            if tool_call_id in compacted_tool_call_ids:
                continue
            if updated is messages:
                updated = [dict(m) for m in messages]
            compacted_tool_call_ids.add(tool_call_id)
            self._compact_tool_result_at(updated, idx)
            estimate, source = estimate_prompt_tokens_chain(
                config.provider,
                config.model,
                updated,
                tools,
            )
            if estimate <= target:
                break

        logger.debug(
            "In-flight context compaction for {}: prompt={} budget={} target={} via {}, ids={}",
            config.session_key or "default",
            estimate,
            budget,
            target,
            source,
            len(compacted_tool_call_ids),
        )
        return updated

    def snip_history(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not messages or not config.context_window_tokens:
            return messages

        budget = self.input_budget(config)
        if budget <= 0:
            return messages

        tools = config.tools.get_definitions()
        estimate, _ = estimate_prompt_tokens_chain(
            config.provider,
            config.model,
            messages,
            tools,
        )
        if estimate <= budget:
            return messages

        system_messages = [dict(msg) for msg in messages if msg.get("role") == "system"]
        non_system = [dict(msg) for msg in messages if msg.get("role") != "system"]
        if not non_system:
            return messages

        system_tokens = sum(estimate_message_tokens(msg) for msg in system_messages)
        fixed_tokens, _ = estimate_prompt_tokens_chain(
            config.provider,
            config.model,
            system_messages,
            tools,
        )
        remaining_budget = max(0, budget - max(system_tokens, fixed_tokens))
        kept: list[dict[str, Any]] = []
        kept_tokens = 0
        for message in reversed(non_system):
            msg_tokens = estimate_message_tokens(message)
            if kept and kept_tokens + msg_tokens > remaining_budget:
                break
            kept.append(message)
            kept_tokens += msg_tokens
        kept.reverse()

        return system_messages + self._legal_history_tail(kept, non_system)

    def compact_subagent_announcements(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Trim oversized persisted subagent announcements before model replay."""
        updated = messages
        for idx, message in enumerate(messages):
            content = message.get("content")
            if message.get("role") != "user" or not isinstance(content, str):
                continue
            compacted = self._compact_subagent_announcement(content)
            if compacted == content:
                continue
            if updated is messages:
                updated = [dict(m) for m in messages]
            updated[idx]["content"] = compacted
        return updated

    def compact_duplicate_tool_results(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compact older duplicate compactable tool results in the model copy.

        The raw session history remains intact. Only exact repeats of the same
        tool name, normalized arguments, user turn, and content are compacted,
        and the newest result stays visible as the recovery path for the model.
        """
        tool_signatures = self._tool_call_signatures(messages)
        seen: dict[tuple[str, str, int, str], list[int]] = {}
        for idx, msg in enumerate(messages):
            if not self._is_compactable_tool_result(msg):
                continue
            call_id = str(msg.get("tool_call_id") or "")
            signature = tool_signatures.get(call_id)
            if signature is None:
                continue
            content = str(msg.get("content") or "")
            seen.setdefault((*signature, self._content_digest(content)), []).append(idx)

        compact_indexes = {idx for indexes in seen.values() for idx in indexes[:-1]}
        if not compact_indexes:
            return messages

        updated = [dict(m) for m in messages]
        for idx in sorted(compact_indexes):
            self._compact_tool_result_at(updated, idx)
        return updated

    def compact_stale_error_tool_results(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compact old failed tool payloads after several newer user turns."""
        turns_after = 0
        compact_indexes: list[int] = []
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if msg.get("role") == "user":
                if self._is_subagent_announcement(msg.get("content")):
                    continue
                turns_after += 1
                continue
            if turns_after < STALE_ERROR_USER_TURNS:
                continue
            if not self._is_compactable_tool_result(msg):
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.lstrip().startswith("Error:"):
                compact_indexes.append(idx)

        if not compact_indexes:
            return messages

        updated = [dict(m) for m in messages]
        for idx in compact_indexes:
            self._compact_tool_result_at(updated, idx)
        return updated

    @staticmethod
    def _summary_for(message: dict[str, Any]) -> str:
        name = message.get("name", "tool")
        return f"[{name} result omitted from context]"

    @classmethod
    def _is_compacted_summary(cls, message: dict[str, Any]) -> bool:
        content = message.get("content")
        return isinstance(content, str) and content == cls._summary_for(message)

    @classmethod
    def _is_compactable_tool_result(
        cls,
        message: dict[str, Any],
        *,
        min_chars: int = MICROCOMPACT_MIN_CHARS,
    ) -> bool:
        if message.get("role") != "tool" or message.get("name") not in COMPACTABLE_TOOLS:
            return False
        if cls._is_compacted_summary(message):
            return False
        content = message.get("content")
        return isinstance(content, str) and len(content) >= min_chars

    @classmethod
    def _tool_call_signatures(
        cls,
        messages: list[dict[str, Any]],
    ) -> dict[str, tuple[str, str, int]]:
        signatures: dict[str, tuple[str, str, int]] = {}
        user_turn = 0
        for msg in messages:
            if msg.get("role") == "user":
                user_turn += 1
                continue
            if msg.get("role") != "assistant":
                continue
            for tool_call in msg.get("tool_calls") or []:
                if not isinstance(tool_call, dict) or not tool_call.get("id"):
                    continue
                func = tool_call.get("function")
                if not isinstance(func, dict):
                    continue
                name = str(func.get("name") or "")
                if name not in COMPACTABLE_TOOLS:
                    continue
                signatures[str(tool_call["id"])] = (
                    name,
                    cls._normalize_tool_arguments(func.get("arguments")),
                    user_turn,
                )
        return signatures

    @staticmethod
    def _normalize_tool_arguments(arguments: Any) -> str:
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                return arguments.strip()
        try:
            return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        except TypeError:
            return str(arguments)

    @staticmethod
    def _content_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()

    @staticmethod
    def _effective_tool_result_chars(config: ContextGovernanceConfig) -> int:
        limit = config.max_tool_result_chars
        budget = ContextGovernor.input_budget(config)
        if budget <= 0:
            return limit
        adaptive = max(
            ADAPTIVE_TOOL_RESULT_MIN_CHARS,
            int(budget * ADAPTIVE_TOOL_RESULT_BUDGET_RATIO),
        )
        return min(limit, adaptive)

    @staticmethod
    def _compact_subagent_announcement(content: str) -> str:
        normalized = content.replace("\r\n", "\n")
        if not ContextGovernor._is_subagent_announcement(normalized):
            return content
        lower = normalized.lower()
        result_marker = "\nresult:\n"
        result_idx = lower.find(result_marker)
        if result_idx == -1:
            result_marker = "\nresult:"
            result_idx = lower.find(result_marker)
        if result_idx == -1:
            return content

        result_start = result_idx + len(result_marker)
        after_result = normalized[result_start:].lstrip()
        instruction_marker = "summarize this naturally"
        instruction_idx = after_result.lower().find(instruction_marker)
        if instruction_idx == -1:
            result_text = after_result.rstrip()
            instruction = ""
        else:
            result_text = after_result[:instruction_idx].rstrip()
            instruction = after_result[instruction_idx:].lstrip()

        if len(result_text) <= SUBAGENT_RESULT_MAX_CHARS:
            return content

        prefix = normalized[:result_start]
        compacted_result = truncate_text(result_text, SUBAGENT_RESULT_MAX_CHARS)
        compacted_result += "\n\n[Subagent result truncated for context replay.]"
        suffix = f"\n\n{instruction}" if instruction else ""
        return f"{prefix}{compacted_result}{suffix}"

    @staticmethod
    def _is_subagent_announcement(content: Any) -> bool:
        return isinstance(content, str) and content.lstrip().startswith("[Subagent")

    def _legal_history_tail(
        self,
        kept: list[dict[str, Any]],
        non_system: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fallback = kept if kept else (non_system[-1:] if non_system else [])
        kept = self._user_tail(kept) or self._user_tail(non_system, last=True) or fallback

        start = find_legal_message_start(kept)
        return kept[start:] if start else kept

    @staticmethod
    def _user_tail(messages: list[dict[str, Any]], *, last: bool = False) -> list[dict[str, Any]]:
        indexes = range(len(messages) - 1, -1, -1) if last else range(len(messages))
        for idx in indexes:
            if messages[idx].get("role") == "user":
                return messages[idx:]
        return []

    def _apply_recorded_compactions(
        self,
        messages: list[dict[str, Any]],
        compacted_tool_call_ids: set[str],
    ) -> list[dict[str, Any]]:
        if not compacted_tool_call_ids:
            return messages
        updated = messages
        for idx, msg in enumerate(messages):
            if msg.get("role") != "tool":
                continue
            tool_call_id = msg.get("tool_call_id")
            if not tool_call_id or str(tool_call_id) not in compacted_tool_call_ids:
                continue
            summary = self._summary_for(msg)
            if msg.get("content") == summary:
                continue
            if updated is messages:
                updated = [dict(m) for m in messages]
            updated[idx]["content"] = summary
        return updated

    def _inflight_compaction_candidates(
        self,
        config: ContextGovernanceConfig,
        messages: list[dict[str, Any]],
        compacted_tool_call_ids: set[str],
    ) -> list[tuple[int, str]]:
        compactable: list[tuple[int, str]] = []
        for idx, msg in enumerate(messages):
            if idx < config.inflight_start_index:
                continue
            if msg.get("role") != "tool" or msg.get("name") not in COMPACTABLE_TOOLS:
                continue
            tool_call_id = msg.get("tool_call_id")
            if not tool_call_id or str(tool_call_id) in compacted_tool_call_ids:
                continue
            content = msg.get("content")
            if not isinstance(content, str) or len(content) < MICROCOMPACT_MIN_CHARS:
                continue
            compactable.append((idx, str(tool_call_id)))

        if not compactable:
            return []
        primary_count = max(0, len(compactable) - MICROCOMPACT_KEEP_RECENT)
        primary = compactable[:primary_count]
        # Hard overflow beats the keep-recent preference. Return recent results
        # after stale ones so the newest result is naturally last.
        fallback = compactable[primary_count:]
        return primary + fallback

    def _compact_tool_result_at(self, messages: list[dict[str, Any]], idx: int) -> None:
        messages[idx]["content"] = self._summary_for(messages[idx])
