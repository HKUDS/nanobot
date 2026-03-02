"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.agent.memory_store import FactStore
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session, SessionManager


_SAVE_MEMORY_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save the memory consolidation result to persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]

_SAVE_FACTS_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "save_facts",
            "description": "Save discrete facts and a history log entry from the conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph (2-5 sentences) summarizing key events. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",
                    },
                    "facts": {
                        "type": "array",
                        "description": "List of discrete facts to remember (1-3 sentences each).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "description": "The fact in 1-3 sentences."},
                                "category": {
                                    "type": "string",
                                    "description": "One of: preference, contact, project, learning, system, general",
                                    "enum": ["preference", "contact", "project", "learning", "system", "general"],
                                },
                            },
                            "required": ["content"],
                        },
                    },
                },
                "required": ["history_entry", "facts"],
            },
        },
    }
]


class MemoryStore:
    """Two-layer memory: MEMORY.md (long-term facts) + HISTORY.md (grep-searchable log)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        long_term = self.read_long_term()
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
        fact_store: FactStore | None = None,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md (or FactStore) via LLM tool call.

        When fact_store is provided, uses save_facts tool and fact_store.add_facts; otherwise save_memory.
        Returns True on success (including no-op), False on failure.
        """
        if archive_all:
            old_messages = session.messages
            keep_count = 0
            logger.info("Memory consolidation (archive_all): {} messages", len(session.messages))
        else:
            keep_count = memory_window // 2
            if len(session.messages) <= keep_count:
                return True
            if len(session.messages) - session.last_consolidated <= 0:
                return True
            old_messages = session.messages[session.last_consolidated:-keep_count]
            if not old_messages:
                return True
            logger.info("Memory consolidation: {} to consolidate, {} keep", len(old_messages), keep_count)

        lines = []
        for m in old_messages:
            if not m.get("content"):
                continue
            tools = f" [tools: {', '.join(m['tools_used'])}]" if m.get("tools_used") else ""
            lines.append(f"[{m.get('timestamp', '?')[:16]}] {m['role'].upper()}{tools}: {m['content']}")

        use_facts = fact_store is not None
        logger.debug(
            "Memory consolidation: use_facts={} session={} messages_to_process={}",
            use_facts,
            session.key,
            len(old_messages),
        )
        if use_facts:
            current_memory = ""
            try:
                facts = fact_store._get_all_facts()
                current_memory = "\n".join(f.get("content", "") for f in facts[:50])
            except Exception:
                pass
            prompt = f"""Process this conversation and call the save_facts tool.
Extract discrete facts (1-3 sentences each) and one history_entry for the log.

## Existing facts (sample)
{current_memory or "(none)"}

## Conversation to Process
{chr(10).join(lines)}"""
            tools_used = _SAVE_FACTS_TOOL
            system_msg = "You are a memory consolidation agent. Call the save_facts tool with a history_entry and a list of discrete facts."
        else:
            current_memory = self.read_long_term()
            prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{chr(10).join(lines)}"""
            tools_used = _SAVE_MEMORY_TOOL
            system_msg = "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."

        try:
            response = await provider.chat(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                tools=tools_used,
                model=model,
            )

            if not response.has_tool_calls:
                name = "save_facts" if use_facts else "save_memory"
                logger.warning("Memory consolidation: LLM did not call {}, skipping", name)
                return False

            args = response.tool_calls[0].arguments
            if isinstance(args, str):
                args = json.loads(args)
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            entry = args.get("history_entry")
            if entry is not None:
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                if fact_store is not None:
                    fact_store.append_history(entry)
                else:
                    self.append_history(entry)

            if use_facts:
                raw_facts = args.get("facts") or []
                facts_list = []
                for f in raw_facts if isinstance(raw_facts, list) else []:
                    if isinstance(f, dict) and f.get("content"):
                        facts_list.append({
                            "content": str(f["content"]).strip(),
                            "category": f.get("category") or "general",
                        })
                if facts_list:
                    added = await fact_store.add_facts(facts_list, source_session=session.key)
                    logger.info(
                        "Memory consolidation (save_facts): {} facts extracted, {} added for session {}",
                        len(facts_list),
                        added,
                        session.key,
                    )
            else:
                if update := args.get("memory_update"):
                    if not isinstance(update, str):
                        update = json.dumps(update, ensure_ascii=False)
                    if update != current_memory:
                        self.write_long_term(update)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False


async def ensure_rolling_summary(
    session: Session,
    provider: LLMProvider,
    model: str,
    memory_config: Any,
    session_manager: SessionManager,
) -> None:
    """
    If unconsolidated messages exceed the conversation token budget,
    summarize the oldest chunk and merge into rolling_summary (Zone B).
    """
    try:
        from nanobot.agent.budget import TokenBudget, count_tokens
    except Exception:
        return
    token_budget_cfg = getattr(memory_config, "token_budget", None)
    if not token_budget_cfg:
        return
    history_summary_budget = getattr(token_budget_cfg, "history_summary", 500)
    raw_conversation = getattr(token_budget_cfg, "conversation", 0)
    if raw_conversation > 0:
        conversation_budget = raw_conversation
    else:
        budget = TokenBudget(model, 4096, token_budget_cfg)
        conversation_budget = budget.get_budget("conversation")
    if conversation_budget <= 0:
        return

    unconsolidated = session.messages[session.last_consolidated:]
    if len(unconsolidated) < 4:
        return

    total_tokens = 0
    for m in unconsolidated:
        content = m.get("content")
        if isinstance(content, str):
            total_tokens += count_tokens(content)
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    total_tokens += count_tokens(c.get("text", ""))

    if total_tokens <= conversation_budget:
        logger.debug(
            "Rolling summary: skip session {} (total_tokens={} <= budget={})",
            session.key,
            total_tokens,
            conversation_budget,
        )
        return

    logger.debug(
        "Rolling summary: session {} over budget (total_tokens={} > {}), compressing chunk",
        session.key,
        total_tokens,
        conversation_budget,
    )
    summarization_model = getattr(memory_config, "summarization_model", None) or model
    summary_anchor = (session.metadata or {}).get("summary_anchor", 0)
    summary_anchor = min(summary_anchor, len(unconsolidated))
    rolling = (session.metadata or {}).get("rolling_summary", "")

    chunk_tokens = 0
    chunk_end = summary_anchor
    target_chunk = min(800, history_summary_budget)
    for i in range(summary_anchor, len(unconsolidated)):
        m = unconsolidated[i]
        content = m.get("content")
        t = count_tokens(content) if isinstance(content, str) else 0
        if not isinstance(content, str) and isinstance(content, list):
            t = sum(count_tokens(c.get("text", "")) for c in content if isinstance(c, dict))
        chunk_tokens += t
        chunk_end = i + 1
        if chunk_tokens >= target_chunk:
            break

    if chunk_end <= summary_anchor:
        return

    to_summarize = unconsolidated[summary_anchor:chunk_end]
    lines = []
    for m in to_summarize:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, str):
            lines.append(f"{role}: {content[:500]}")
        else:
            lines.append(f"{role}: [content]")

    prompt = "Summarize this conversation segment in 2-4 sentences. Preserve key facts and decisions.\n\n" + "\n".join(lines)
    try:
        response = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            model=summarization_model,
        )
        new_bit = (response.content or "").strip()
        if not new_bit:
            return
        if session.metadata is None:
            session.metadata = {}
        session.metadata["rolling_summary"] = (rolling + "\n\n" + new_bit).strip() if rolling else new_bit
        session.metadata["summary_anchor"] = chunk_end
        session.updated_at = __import__("datetime").datetime.now()
        session_manager.save(session)
        logger.info(
            "Rolling summary: updated for session {}, anchor={} (summarized {} messages)",
            session.key,
            chunk_end,
            chunk_end - summary_anchor,
        )
    except Exception as e:
        logger.warning("Rolling summary update failed for session {}: {}", session.key, e)
