"""Memory system for persistent agent memory."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.utils.helpers import ensure_dir

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session


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
                    "skill": {
                        "type": "string",
                        "description": (
                            "If the conversation contains a successful multi-step task using tools, "
                            "extract a REUSABLE workflow template as JSON: "
                            '{"task": "abstract task description (generalized, no specific names/paths)", '
                            '"steps": ["generalized step 1", "generalized step 2", ...], '
                            '"tools": ["tool_name_1", "tool_name_2", ...], '
                            '"tags": ["lowercase_keyword1", "lowercase_keyword2", ...]}. '
                            "Return empty string if no reusable multi-step workflow was found."
                        ),
                    },
                },
                "required": ["history_entry", "memory_update"],
            },
        },
    }
]


class MemoryStore:
    """Three-layer memory: MEMORY.md (facts) + HISTORY.md (event log) + SKILLS.jsonl (workflow patterns)."""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"
        self.skills_file = self.memory_dir / "SKILLS.jsonl"

    def read_long_term(self) -> str:
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    # ── Skill Memory ──────────────────────────────────────────────

    def load_skills(self) -> list[dict]:
        """Load all skills from SKILLS.jsonl."""
        if not self.skills_file.exists():
            return []
        skills = []
        for line in self.skills_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    skills.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return skills

    def save_skill(self, skill: dict) -> None:
        """Append a skill to SKILLS.jsonl after deduplication check."""
        if self._is_duplicate_skill(skill):
            logger.info("Skill extraction: duplicate skill '{}', skipping", skill.get("task", ""))
            return
        skill.setdefault("recorded", datetime.now().isoformat()[:16])
        with open(self.skills_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(skill, ensure_ascii=False) + "\n")
        logger.info("Skill saved: {}", skill.get("task", ""))

    def _is_duplicate_skill(self, new_skill: dict) -> bool:
        """Check if a similar skill already exists (Jaccard similarity on tags > 0.5)."""
        new_tags = {t.lower() for t in new_skill.get("tags", [])}
        if not new_tags:
            return False
        for skill in self.load_skills():
            existing_tags = {t.lower() for t in skill.get("tags", [])}
            if not existing_tags:
                continue
            jaccard = len(new_tags & existing_tags) / len(new_tags | existing_tags)
            if jaccard > 0.5:
                return True
        return False

    def find_relevant_skills(self, query: str, top_k: int = 3) -> list[dict]:
        """Find skills relevant to a query via keyword overlap on tags + task."""
        skills = self.load_skills()
        if not skills:
            return []
        query_tokens = set(query.lower().split())
        scored = []
        for skill in skills:
            skill_tokens: set[str] = set()
            for tag in skill.get("tags", []):
                skill_tokens.update(tag.lower().split())
            skill_tokens.update(skill.get("task", "").lower().split())
            score = len(query_tokens & skill_tokens)
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s[1] for s in scored[:top_k]]

    def get_skills_context(self, query: str = "", top_k: int = 3) -> str:
        """Build a formatted skills string for prompt injection."""
        skills = self.find_relevant_skills(query, top_k) if query else self.load_skills()[-top_k:]
        if not skills:
            return ""
        logger.info(
            "Skill retrieval: query='{}' -> {} skill(s) injected: {}",
            query[:60],
            len(skills),
            [s.get("task", "?") for s in skills],
        )
        parts = []
        for s in skills:
            steps = "\n".join(f"  {i + 1}. {step}" for i, step in enumerate(s.get("steps", [])))
            tools = ", ".join(s.get("tools", []))
            parts.append(f"### {s.get('task', 'Untitled')}\n- Tools: {tools}\n- Steps:\n{steps}")
        return "\n\n".join(parts)

    # ── Context ───────────────────────────────────────────────────

    def get_memory_context(self, query: str = "") -> str:
        """Build the full memory context block (long-term facts + relevant skills)."""
        parts = []
        long_term = self.read_long_term()
        if long_term:
            parts.append(f"## Long-term Memory\n{long_term}")
        skills_ctx = self.get_skills_context(query)
        if skills_ctx:
            parts.append(f"## Learned Skills\nReusable workflow patterns from past tasks:\n\n{skills_ctx}")
        return "\n\n".join(parts)

    async def consolidate(
        self,
        session: Session,
        provider: LLMProvider,
        model: str,
        *,
        archive_all: bool = False,
        memory_window: int = 50,
    ) -> bool:
        """Consolidate old messages into MEMORY.md + HISTORY.md via LLM tool call.

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

        current_memory = self.read_long_term()
        existing_skills = self.load_skills()
        skills_summary = "\n".join(f"- {s.get('task', '?')}" for s in existing_skills) if existing_skills else "(none)"
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Existing Skills (avoid duplicates)
{skills_summary}

## Conversation to Process
{chr(10).join(lines)}

If the conversation contains a successful multi-step task using tools, also extract a reusable skill in the 'skill' field — generalize specific details into abstract, reusable patterns. Skip if trivial or conversational."""

        try:
            response = await provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a memory consolidation agent. Call the save_memory tool with your consolidation. "
                            "If the conversation contains a successful multi-step task, also extract a reusable skill — "
                            "generalize specific details into abstract, reusable workflow patterns."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
            )

            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            args = response.tool_calls[0].arguments
            # Some providers return arguments as a JSON string instead of dict
            if isinstance(args, str):
                args = json.loads(args)
            # Some providers return arguments as a list (handle edge case)
            if isinstance(args, list):
                if args and isinstance(args[0], dict):
                    args = args[0]
                else:
                    logger.warning("Memory consolidation: unexpected arguments as empty or non-dict list")
                    return False
            if not isinstance(args, dict):
                logger.warning("Memory consolidation: unexpected arguments type {}", type(args).__name__)
                return False

            if entry := args.get("history_entry"):
                if not isinstance(entry, str):
                    entry = json.dumps(entry, ensure_ascii=False)
                self.append_history(entry)
            if update := args.get("memory_update"):
                if not isinstance(update, str):
                    update = json.dumps(update, ensure_ascii=False)
                if update != current_memory:
                    self.write_long_term(update)

            if skill_json := args.get("skill"):
                if isinstance(skill_json, str) and skill_json.strip():
                    try:
                        skill = json.loads(skill_json)
                        if isinstance(skill, dict) and skill.get("task") and skill.get("steps"):
                            self.save_skill(skill)
                    except json.JSONDecodeError:
                        logger.debug("Skill extraction: invalid JSON, skipping")
                elif isinstance(skill_json, dict) and skill_json.get("task") and skill_json.get("steps"):
                    self.save_skill(skill_json)

            session.last_consolidated = 0 if archive_all else len(session.messages) - keep_count
            logger.info("Memory consolidation done: {} messages, last_consolidated={}", len(session.messages), session.last_consolidated)
            return True
        except Exception:
            logger.exception("Memory consolidation failed")
            return False
