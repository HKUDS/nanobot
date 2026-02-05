"""Session compaction for managing conversation history size."""

from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.agent.memory.extractor import extract_facts_from_messages


@dataclass
class CompactionConfig:
    """Configuration for session compaction."""
    threshold: int = 50
    recent_turns_keep: int = 8
    summary_max_turns: int = 15
    max_facts: int = 10


class SessionCompactor:
    """Compacts session history using layered summarization."""

    def __init__(self, config: CompactionConfig | None = None):
        self.config = config or CompactionConfig()

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compact message history to reduce size."""
        if len(messages) < self.config.threshold:
            logger.debug(f"Skipping compaction: {len(messages)} < {self.config.threshold}")
            return messages

        recent_count = self.config.recent_turns_keep * 2
        recent_start = max(0, len(messages) - recent_count)
        recent = messages[recent_start:]

        middle_count = self.config.summary_max_turns * 2
        middle_end = recent_start
        middle_start = max(0, middle_end - middle_count)
        middle = messages[middle_start:middle_end]

        old = messages[:middle_start]

        compacted = []
        recall_parts = []

        if old:
            facts = self._extract_facts(old)
            if facts:
                recall_parts.append(f"Key facts:\n{facts}")

        if middle:
            summary = self._summarize(middle)
            if summary:
                recall_parts.append(f"Recent discussion summary:\n{summary}")

        if recall_parts:
            recall_content = "[Recalling from earlier in our conversation]\n\n" + "\n\n".join(recall_parts)
            compacted.append({"role": "assistant", "content": recall_content})

        compacted.extend(recent)

        logger.info(
            f"Compacted {len(messages)} → {len(compacted)} "
            f"(old: {len(old)}, middle: {len(middle)}, recent: {len(recent)})"
        )

        return compacted

    def _extract_facts(self, messages: list[dict[str, Any]]) -> str:
        """Extract key facts from old messages using shared heuristics."""
        facts = extract_facts_from_messages(messages, max_facts=self.config.max_facts)
        return "\n".join(f"- {fact}" for fact in facts)

    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """Summarize middle-section messages using heuristics."""
        user_questions = []
        assistant_conclusions = []

        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue

            role = msg.get("role", "")

            if role == "user":
                for line in content.split("\n"):
                    line = line.strip()
                    if line.endswith("?") and len(line) > 20:
                        user_questions.append(line[:150])

            if role == "assistant" and len(content) > 50:
                for sentence in content.split(".")[:3]:
                    sentence = sentence.strip()
                    if len(sentence) > 30:
                        assistant_conclusions.append(sentence[:150])
                        break

        parts = []
        if user_questions:
            parts.append("User asked about:")
            for q in user_questions[:3]:
                parts.append(f"  - {q}")

        if assistant_conclusions:
            parts.append("Assistant responses:")
            for c in assistant_conclusions[:3]:
                parts.append(f"  - {c}")

        return "\n".join(parts) if parts else "General discussion continued"
