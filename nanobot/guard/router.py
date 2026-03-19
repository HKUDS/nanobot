"""Security and cost-aware routing for the guard layer."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from nanobot.guard.detector import PIIEntity, RuleDetector, SecurityLevel, _LEVEL_RANK

if TYPE_CHECKING:
    from nanobot.config.schema import GuardConfig
    from nanobot.providers.base import LLMProvider


class Complexity(str, Enum):
    SIMPLE = "SIMPLE"
    MEDIUM = "MEDIUM"
    COMPLEX = "COMPLEX"
    REASONING = "REASONING"


def _mask_text(text: str, entities: list[PIIEntity]) -> str:
    """Replace PII spans with type placeholders, right-to-left to preserve offsets."""
    result = text
    for entity in reversed(entities):
        placeholder = f"[{entity.entity_type.upper()}]"
        result = result[: entity.start] + placeholder + result[entity.end :]
    return result


class SecurityRouter:
    """Three-level security classifier and message masker."""

    def __init__(self, config: GuardConfig) -> None:
        self.config = config
        self.rule_detector = RuleDetector(extra_rules=config.extra_rules or [])

    def classify_messages(
        self, messages: list[dict]
    ) -> tuple[SecurityLevel, list[PIIEntity]]:
        """Scan all user-role messages and return the worst security level found."""
        worst = SecurityLevel.S1
        all_entities: list[PIIEntity] = []

        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            texts: list[str] = []
            if isinstance(content, list):
                texts = [
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
            elif isinstance(content, str):
                texts = [content]

            for text in texts:
                entities = self.rule_detector.detect(text)
                all_entities.extend(entities)
                level = self.rule_detector.max_level(entities)
                if _LEVEL_RANK[level] > _LEVEL_RANK[worst]:
                    worst = level
                    if worst == SecurityLevel.S3:
                        return worst, all_entities  # short-circuit

        return worst, all_entities

    def apply_mask(
        self, messages: list[dict], entities: list[PIIEntity]
    ) -> list[dict]:
        """Return a copy of messages with PII entities replaced by placeholders."""
        if not entities:
            return messages
        masked: list[dict] = []
        for msg in messages:
            if msg.get("role") != "user":
                masked.append(msg)
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                masked.append({**msg, "content": _mask_text(content, entities)})
            elif isinstance(content, list):
                new_parts = [
                    {**p, "text": _mask_text(p["text"], entities)}
                    if isinstance(p, dict) and p.get("type") == "text"
                    else p
                    for p in content
                ]
                masked.append({**msg, "content": new_parts})
            else:
                masked.append(msg)
        return masked


_COMPLEXITY_PROMPT = (
    "Classify the complexity of the user's latest request into one of:\n"
    "SIMPLE - trivial lookup, greeting, single-step task\n"
    "MEDIUM - multi-step task, code generation, analysis\n"
    "COMPLEX - long research, complex coding, architectural design\n"
    "REASONING - step-by-step logical reasoning or math\n"
    "Respond with exactly one word: SIMPLE, MEDIUM, COMPLEX, or REASONING."
)


class CostRouter:
    """Task complexity classifier for cost-aware model selection."""

    def __init__(self, config: GuardConfig) -> None:
        self.config = config

    async def classify(
        self, messages: list[dict], provider: LLMProvider
    ) -> Complexity:
        """Ask the provider to classify the task complexity of the last user message."""
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        if isinstance(last_user, list):
            last_user = " ".join(
                p.get("text", "")
                for p in last_user
                if isinstance(p, dict) and p.get("type") == "text"
            )

        classify_messages = [
            {"role": "system", "content": _COMPLEXITY_PROMPT},
            {"role": "user", "content": str(last_user)[:2000]},
        ]
        try:
            response = await provider.chat_with_retry(
                messages=classify_messages,
                tools=None,
                model=self.config.local_detector_model or None,
                max_tokens=10,
                temperature=0.0,
            )
            word = (
                (response.content or "").strip().upper().split()[0]
                if response.content
                else ""
            )
            return Complexity(word) if word in Complexity.__members__ else Complexity.MEDIUM
        except Exception:
            return Complexity.MEDIUM  # safe default
